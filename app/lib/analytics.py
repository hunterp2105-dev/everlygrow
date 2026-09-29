"""Analytics pull (API + manual), and the self-learning tracker's
tagging/ranking logic (§16 steps 21-23).

Both API-pulled and manually-entered metrics land in the same
`analytics_snapshots` table (see migration 0009's note on why) — so
top_performers() below works identically regardless of source, which is
exactly what §5a asks for ("feeding the same tracker/optimizer logic").
"""

from datetime import datetime, timezone

import requests as requests_lib

from app.lib import blotato_client

_METRIC_KEYS = {"commentsCount": "comments", "likesCount": "likes", "sharesCount": "shares", "viewsCount": "views"}


_RESOLVE_MAX_PAGES = 5
"""GET /published-posts is a linear scan, not date-sorted in a way you can
binary search (confirmed live — see blotato_client.search_published_posts).
Bounded to 5x100=500 posts back; a post older than that won't resolve here
and needs a wider search or a smarter index if this becomes a real need."""


def resolve_numeric_post_id(client, generation: dict) -> str | None:
    """Blotato's analytics endpoints key posts by a numeric id we're never
    given directly (POST /posts only returns postSubmissionId). Resolve it
    once, by searching published-posts for this generation's post_url, and
    cache it on the row."""
    if generation.get("blotato_numeric_post_id"):
        return generation["blotato_numeric_post_id"]
    if not generation.get("post_url"):
        return None

    match = None
    for page in range(_RESOLVE_MAX_PAGES):
        items = blotato_client.search_published_posts(limit=100, offset=page * 100).get("items", [])
        if not items:
            break
        match = next((p for p in items if p.get("postUrl") == generation["post_url"]), None)
        if match:
            break
    if not match:
        return None

    client.table("generations").update({"blotato_numeric_post_id": match["id"]}).eq("id", generation["id"]).execute()
    return match["id"]


def _platform_for(generation: dict, client) -> str | None:
    if not generation.get("target_social_account_id"):
        return None
    account = (
        client.table("social_accounts")
        .select("platform")
        .eq("id", generation["target_social_account_id"])
        .maybe_single()
        .execute()
    )
    return (account.data or {}).get("platform") if account else None


def _store_snapshot(client, generation: dict, platform: str, metrics: dict, source: str, entered_by: str | None = None) -> dict:
    return (
        client.table("analytics_snapshots")
        .insert(
            {
                "generation_id": generation["id"],
                "customer_id": generation["customer_id"],
                "platform": platform,
                "source": source,
                "views": metrics.get("views"),
                "likes": metrics.get("likes"),
                "comments": metrics.get("comments"),
                "shares": metrics.get("shares"),
                "reach": metrics.get("reach"),
                "watch_time": metrics.get("watch_time"),
                "entered_by": entered_by,
            }
        )
        .execute()
        .data[0]
    )


def pull_api_analytics(client, generation: dict) -> dict | None:
    """Tries the per-post endpoint first (fresher once synced), falls back
    to matching this post in the aggregate top-performers pull (confirmed
    live to have data sooner — see blotato_client.get_top_analytics).
    Returns the stored snapshot, or None if no data is available yet
    (not an error — analytics can take up to 24h to sync per §4)."""
    platform = _platform_for(generation, client)
    if platform is None:
        return None

    numeric_id = resolve_numeric_post_id(client, generation)
    if numeric_id:
        try:
            data = blotato_client.get_post_analytics(numeric_id)
            metrics = {"views": data.get("views"), "likes": data.get("likes"), "comments": data.get("comments"), "shares": data.get("shares")}
            return _store_snapshot(client, generation, platform, metrics, source="api")
        except requests_lib.exceptions.HTTPError as exc:
            if exc.response.status_code != 404:
                raise  # 404 = "not synced yet", anything else is a real error

    if generation.get("post_url"):
        for item in blotato_client.get_top_analytics():
            if item.get("postUrl") == generation["post_url"]:
                raw = (item.get("latestMetrics") or {}).get("metrics", {})
                metrics = {_METRIC_KEYS[k]: int(v) for k, v in raw.items() if k in _METRIC_KEYS}
                return _store_snapshot(client, generation, platform, metrics, source="api")

    return None


def log_manual_metrics(client, generation: dict, entered_by: str, views=None, likes=None, comments=None, shares=None) -> dict:
    """§5a: manual TikTok metrics entry — same table, same downstream
    tracker/optimizer logic as API-pulled data, clearly labeled `manual`."""
    platform = _platform_for(generation, client) or "tiktok"
    return _store_snapshot(
        client, generation, platform,
        {"views": views, "likes": likes, "comments": comments, "shares": shares},
        source="manual", entered_by=entered_by,
    )


_SHARE_WEIGHT = 5
_COMMENT_WEIGHT = 2
_LIKE_WEIGHT = 1
"""§16 growth-rules Group D1: 2026 research ranks completion rate/watch
time and saves above shares, and shares above comments/likes — but
completion rate, watch time, and saves are NOT available anywhere in this
product. Confirmed against Blotato's real API responses
(blotato_client.get_top_analytics/get_post_analytics return only
views/likes/comments/shares, never watch time or saves), and
analytics_snapshots.watch_time has never been populated by any real data
source. This weighting reflects the highest-priority signal we actually
HAVE (shares) over comments and likes — it does not claim to measure
retention, because we can't. Revisit if Blotato ever exposes more."""


def engagement_score(snapshot: dict) -> int:
    return (
        (snapshot.get("shares") or 0) * _SHARE_WEIGHT
        + (snapshot.get("comments") or 0) * _COMMENT_WEIGHT
        + (snapshot.get("likes") or 0) * _LIKE_WEIGHT
    )


def top_performers(client, niche: str | None = None, template_id: str | None = None, limit: int = 10) -> list[dict]:
    """§16 step 23: tag by style/template/niche, surface best performers.
    Latest snapshot per generation is used as that post's current
    standing (a post accrues more engagement over time; we want its most
    recent read, not its first)."""
    response = (
        client.table("analytics_snapshots")
        .select("*, generations(id, template_id, template_description, prompt, customer_id, customers(niche))")
        .order("collected_at", desc=True)
        .execute()
    )
    latest_by_generation: dict[str, dict] = {}
    for snap in response.data or []:
        gen = snap.get("generations")
        if not gen:
            continue
        if template_id and gen.get("template_id") != template_id:
            continue
        if niche and (gen.get("customers") or {}).get("niche") != niche:
            continue
        if gen["id"] not in latest_by_generation:  # first hit per id = most recent, since already ordered desc
            latest_by_generation[gen["id"]] = {**snap, "generation": gen}

    ranked = sorted(latest_by_generation.values(), key=engagement_score, reverse=True)
    return ranked[:limit]
