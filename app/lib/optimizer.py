"""Per-platform optimizer (§8.2, §16 step 24): watches performance,
suggests strategy changes for admin approval. Advisory only — approving a
suggestion here doesn't change anything automatically, it's a queue for
admin judgment, per §8.2 ("surfaced to admin — advisory only").

Rule-based, not ML (§14 explicitly defers "Advanced ML-driven self-learning/
optimizer" to later) — compares a customer's most recent post on a platform
against their own prior average on that same platform. Needs at least 2
prior posts to have a baseline; with this little real data so far, expect
this to mostly find nothing to suggest yet — that's correct, not broken.
"""

from app.lib import notifications
from app.lib.analytics import engagement_score

UNDERPERFORM_THRESHOLD = 0.5
"""Flag if the latest post's engagement is under half the customer's own
prior average on that platform. Not specified in the packet — a starting
point, easy to tune once there's enough real data to judge against."""


def generate_suggestions(client, customer_id: str) -> list[dict]:
    response = (
        client.table("analytics_snapshots")
        .select("*, generations(target_social_account_id, social_accounts(platform))")
        .eq("customer_id", customer_id)
        .order("collected_at")
        .execute()
    )
    by_platform: dict[str, list[dict]] = {}
    for snap in response.data or []:
        gen = snap.get("generations") or {}
        platform = (gen.get("social_accounts") or {}).get("platform")
        if platform:
            by_platform.setdefault(platform, []).append(snap)

    created = []
    for platform, snaps in by_platform.items():
        if len(snaps) < 3:  # need a real baseline (2+ prior) plus the latest
            continue
        *prior, latest = snaps
        prior_avg = sum(engagement_score(s) for s in prior) / len(prior)
        latest_score = engagement_score(latest)
        if prior_avg > 0 and latest_score < prior_avg * UNDERPERFORM_THRESHOLD:
            suggestion = (
                client.table("optimizer_suggestions")
                .insert(
                    {
                        "customer_id": customer_id,
                        "platform": platform,
                        "trigger_metric": f"engagement {latest_score} vs. prior average {prior_avg:.1f}",
                        "proposed_change": (
                            f"Recent {platform} content is underperforming this customer's own recent average "
                            f"by more than {int((1 - UNDERPERFORM_THRESHOLD) * 100)}%. Consider a different "
                            f"template/style or a niche playbook angle that's performed better elsewhere."
                        ),
                    }
                )
                .execute()
                .data[0]
            )
            notifications.notify(
                client, recipient_type="admin", type_="optimizer_suggestion",
                message=f"New optimizer suggestion for {platform}: {suggestion['trigger_metric']}",
                customer_id=customer_id,
            )
            created.append(suggestion)
    return created


def list_pending_suggestions(client, customer_id: str | None = None) -> list[dict]:
    query = client.table("optimizer_suggestions").select("*, customers(name)").eq("status", "pending")
    if customer_id:
        query = query.eq("customer_id", customer_id)
    return query.order("created_at").execute().data or []


def resolve_suggestion(client, suggestion_id: str, status: str) -> None:
    from datetime import datetime, timezone

    client.table("optimizer_suggestions").update(
        {"status": status, "resolved_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", suggestion_id).execute()
