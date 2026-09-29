"""Customer-facing content-idea suggestions (§16 admin follow-up,
2026-09-29) — the customer-side mirror of admin's playbook suggestions
(admin_panel._render_playbook_suggestions), shown in the customer's
Request tab (customer_hub._render_requests) so a content request starts
from a concrete, tailored idea instead of a blank box.

A REAL Claude call (claude-sonnet-5, the same model guardrails.py already
uses) grounded in this customer's actual niche playbook, brand profile,
and upcoming holidays (calendar.holidays_in_range) plus the growth
research already in the system (growth_rules.py) — never generic filler.

CACHING DISCIPLINE: generated in a batch and stored (customer_content_ideas
table), NOT called live on every page view — see needs_refresh(). This app
has no background scheduler at all (confirmed when real per-platform
scheduling was investigated for the growth-rules work), so "refresh on a
schedule" here means what every other lazily-refreshed thing in this
codebase means: checked at view time, regenerated only when actually
stale, not a real cron job.

PRIVILEGE NOTE: same pattern as approval.py/intake.py — a customer's own
RLS session can only SELECT customer_content_ideas (migration 0016);
every function here is written to run with the service-role client, and
customer_hub.py calls it that way using the caller's own verified
customer_id.

COST: every batch generation is a real Claude call and is logged for real
— see credits.log_claude_usage — into the same ledger Blotato generation
costs already use.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from app.lib import calendar as calendar_module
from app.lib import credits, growth_rules

_MODEL = "claude-sonnet-5"
BATCH_SIZE = 8
REFRESH_AFTER_DAYS = 21
REFRESH_BELOW_ACTIVE_COUNT = 2

CATEGORIES = ["transformation", "behind_the_scenes", "trust_building", "search_optimized", "seasonal"]
CATEGORY_LABELS = {
    "transformation": "Transformation / results",
    "behind_the_scenes": "Behind the scenes",
    "trust_building": "Trust-building",
    "search_optimized": "Search-optimized",
    "seasonal": "Seasonal",
}

_RESULT_TOOL = {
    "name": "report_content_ideas",
    "description": "Report a batch of tailored content ideas for this specific business.",
    "strict": True,
    # §16 admin follow-up (2026-09-29): found live — without `strict`, a
    # real call once returned `ideas` as a list of JSON-encoded strings
    # instead of objects (a real, if occasional, model deviation from the
    # declared schema, not a client-side parsing bug — confirmed by
    # reproducing the exact same call shape multiple times, most of which
    # returned correctly-shaped objects). `strict: true` has the API
    # enforce schema compliance server-side rather than hoping the model
    # complies, per Anthropic's own strict-tool-use guidance. Requires
    # `additionalProperties: false` at every object level.
    "input_schema": {
        "type": "object",
        "properties": {
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short, specific idea title — usable as a request subject line.",
                        },
                        "detail": {
                            "type": "string",
                            "description": "1-2 sentences elaborating the idea — usable as the request message.",
                        },
                        "category": {"type": "string", "enum": CATEGORIES},
                    },
                    "required": ["title", "detail", "category"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["ideas"],
        "additionalProperties": False,
    },
}


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set (see .env.example) to generate content ideas.")
    import anthropic

    return anthropic.Anthropic(api_key=key)


def needs_refresh(client, customer_id: str) -> bool:
    """True if there's no cached batch yet, the newest batch is stale
    (>REFRESH_AFTER_DAYS old), or too few ideas from it are still
    actionable (fewer than REFRESH_BELOW_ACTIVE_COUNT still 'active')."""
    rows = (
        client.table("customer_content_ideas")
        .select("status, batch_generated_at")
        .eq("customer_id", customer_id)
        .order("batch_generated_at", desc=True)
        .execute()
        .data
        or []
    )
    if not rows:
        return True
    newest_batch_at = datetime.fromisoformat(rows[0]["batch_generated_at"])
    if datetime.now(timezone.utc) - newest_batch_at > timedelta(days=REFRESH_AFTER_DAYS):
        return True
    active_count = sum(1 for r in rows if r["status"] == "active")
    return active_count < REFRESH_BELOW_ACTIVE_COUNT


def _gather_context(client, customer_id: str) -> dict:
    customer = (
        client.table("customers")
        .select("*, niche_playbooks(*)")
        .eq("id", customer_id)
        .maybe_single()
        .execute()
        .data
        or {}
    )
    playbook = customer.get("niche_playbooks") or {}
    today = datetime.now(timezone.utc).date()
    upcoming_holidays = calendar_module.holidays_in_range(client, today, today + timedelta(days=90), niche=customer.get("niche"))
    return {
        "business_name": customer.get("name") or "this business",
        "niche": customer.get("niche") or "General",
        "brand_profile": customer.get("brand_profile") or {},
        "content_pillars": playbook.get("content_pillars") or [],
        "example_angles": playbook.get("example_angles") or [],
        "best_practices": playbook.get("best_practices") or "",
        "upcoming_holidays": [
            {"name": h["title"], "date": h["date"].isoformat(), "idea_seed": h.get("content_idea_prompt")}
            for h in upcoming_holidays[:10]
        ],
    }


def generate_batch(client, customer_id: str) -> list[dict]:
    """Real Claude call — see module docstring for the caching discipline
    that keeps this from running on every Request-tab view."""
    context = _gather_context(client, customer_id)

    prompt = (
        f"Business: {context['business_name']} (niche: {context['niche']})\n"
        f"Brand profile: {json.dumps(context['brand_profile'])}\n"
        f"Existing content pillars for this niche: {context['content_pillars']}\n"
        f"Existing example angles for this niche: {context['example_angles']}\n"
        f"Niche best practices: {context['best_practices']}\n"
        f"Upcoming holidays/awareness days (next 90 days): {json.dumps(context['upcoming_holidays'])}\n\n"
        f"Growth research principles to apply: {growth_rules.UNIVERSAL_PRINCIPLES}\n\n"
        f"Generate {BATCH_SIZE} specific, tailored content ideas for THIS business — not generic "
        "advice, and not just a restatement of the pillars/angles above (build on them, don't repeat "
        "them verbatim). Each idea must be concrete enough that someone could act on it immediately, "
        "naming real specifics implied by the business/niche rather than placeholders. Cover a mix "
        "across these categories: transformation/results, behind-the-scenes, trust-building, "
        "search-optimized (answers a real question this niche's customers actually search for), and "
        "seasonal (tied to one of the upcoming holidays/awareness days listed above, using its "
        "idea_seed if given — skip seasonal ideas entirely if none fit naturally, don't force it). "
        "Weight roughly 30% of the ideas toward search-optimized angles. Call report_content_ideas "
        "with the full batch."
    )

    response = _client().messages.create(
        model=_MODEL,
        max_tokens=2048,
        tools=[_RESULT_TOOL],
        tool_choice={"type": "tool", "name": "report_content_ideas"},
        messages=[{"role": "user", "content": prompt}],
    )
    ideas = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "report_content_ideas":
            ideas = block.input["ideas"]
    if ideas is None:
        raise RuntimeError("Claude did not return a report_content_ideas tool call.")
    # `strict: true` on the tool (see _RESULT_TOOL) should make this
    # unreachable — kept as a clear, specific failure instead of a
    # confusing raw TypeError on the dict-access below, in case a future
    # API/model change ever reintroduces the deviation this was added for.
    if not all(isinstance(idea, dict) for idea in ideas):
        raise RuntimeError(f"Claude returned malformed content ideas (expected objects): {ideas!r}")

    # Retire the old batch (superseded, not deleted — keeps a real history
    # of what's been suggested) and cost-log this real call BEFORE
    # inserting the new batch, so a failure partway through insert still
    # leaves the real spend accounted for.
    client.table("customer_content_ideas").update({"status": "dismissed"}).eq("customer_id", customer_id).eq(
        "status", "active"
    ).execute()
    credits.log_claude_usage(client, customer_id, response.usage, cost_source="claude_content_ideas")

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "customer_id": customer_id,
            "title": idea["title"],
            "detail": idea["detail"],
            "category": idea["category"],
            "status": "active",
            "batch_generated_at": now,
        }
        for idea in ideas
    ]
    return client.table("customer_content_ideas").insert(rows).execute().data


def list_active_ideas(client, customer_id: str) -> list[dict]:
    return (
        client.table("customer_content_ideas")
        .select("*")
        .eq("customer_id", customer_id)
        .eq("status", "active")
        .order("created_at")
        .execute()
        .data
        or []
    )


def mark_used(client, idea_id: str) -> None:
    client.table("customer_content_ideas").update({"status": "used"}).eq("id", idea_id).execute()


def get_or_refresh_ideas(client, customer_id: str) -> list[dict]:
    """The one entry point customer_hub.py needs — hides the cache-check
    from the UI layer entirely."""
    if needs_refresh(client, customer_id):
        return generate_batch(client, customer_id)
    return list_active_ideas(client, customer_id)
