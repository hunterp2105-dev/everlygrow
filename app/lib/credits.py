"""Credit & Cost Tracking (§10, §16 step 29).

Real per-template Blotato credit costs are LEARNED in production, not
pre-populated by hand: `template_costs` (migration 0012) starts seeded
with the three data points measured manually during Phase 13 validation
(see docs/phase13-validation-notes.md), and gains a new row the first
time any other template is actually used — see generation.py's
_maybe_start_cost_measurement/_maybe_finish_cost_measurement, which
snapshot Blotato's real GET /v2/credits balance immediately before a
generation starts and again immediately after it finishes.

This replaced an earlier ESTIMATED_COST_PER_TYPE model that guessed cost
from the image/video binary classification (5x for video) — real
measurement showed that guess had the wrong SHAPE, not just wrong
numbers: one image template cost more than the video template tested,
and another image template cost nothing. Cost tracks the template, not
the output media type.

Flag, don't hard-block (§10, and already the established pattern for
every other cap in this codebase) — crossing a budget threshold notifies
admin, it never blocks a generation.
"""

from datetime import datetime, timezone

from app.lib import blotato_client, growth_rules, notifications

FALLBACK_ESTIMATED_COST = 50
"""Used only for a template_id with no row yet in `template_costs` —
i.e. a template that has never actually been used in production. Set to
the highest of the three initial real measurements (TV Wall Infographic,
50 credits) rather than an average: underestimating is the actual product
risk here (a budget-threshold warning firing too late to matter), so a
conservative starting guess is safer than a "typical" one. Every use of
this fallback is flagged (credit_usage_log.cost_is_measured = False) so
admin can see which historical entries were a real measurement vs. a
guess, and it matters less over time as more templates get measured."""

CREDIT_THRESHOLD_FRACTION = 0.8
"""Notify once a customer crosses 80% of their budget. Not specified in
the packet — a reasonable starting point."""

CREDIT_USD_RATE = 0.006
"""$6.00 per 1,000 Blotato credits = $0.006/credit — confirmed live via
Blotato's GET /v2/credits pricing (docs/phase13-validation-notes.md).
Real Claude API spend (USD) is converted into this SAME credit unit
(see log_claude_usage) so every real cost — Blotato generation or Claude
API call — lands in one coherent ledger, rather than mixing incompatible
units into one summed "credits this period" number."""

CLAUDE_PRICING_PER_MTOK = {
    # $/1M tokens. Confirmed 2026-09-29 against Anthropic's published
    # pricing. cache_write/cache_read only apply if a call ever uses
    # prompt caching — neither guardrails nor content_ideas do today, but
    # the fields are included so a real cache-using call is priced
    # correctly the moment one exists, not silently undercounted.
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
}


def claude_usage_cost_usd(usage, model: str = "claude-sonnet-5") -> float:
    """Real USD cost from a Messages API response's `usage` object.
    Raises KeyError for an unpriced model — deliberately, rather than
    silently returning 0 for a model this table hasn't been told about."""
    pricing = CLAUDE_PRICING_PER_MTOK[model]
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_write_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_write_tokens * pricing["cache_write"]
        + cache_read_tokens * pricing["cache_read"]
    ) / 1_000_000


def log_claude_usage(client, customer_id: str, usage, cost_source: str, model: str = "claude-sonnet-5") -> dict:
    """§16 admin follow-up (2026-09-29): found live that NO Claude API
    call anywhere in this codebase was ever cost-logged — including
    guardrail evaluations running on every generation — meaning the
    Credit & Cost Tracker was undercounting real spend. Logs a real
    Claude call's cost into the SAME credit_usage_log ledger Blotato
    spend already uses, converted from real USD to the same credit unit
    (CREDIT_USD_RATE) so both sources sum correctly into one total.
    `generation_id` is None — this isn't tied to a Blotato generation
    job; `cost_source` distinguishes it for anyone who needs to break the
    total back down (e.g. 'guardrail_evaluation', 'claude_content_ideas').
    """
    usd_cost = claude_usage_cost_usd(usage, model)
    credit_cost = usd_cost / CREDIT_USD_RATE
    billing_period = datetime.now(timezone.utc).strftime("%Y-%m")
    entry = (
        client.table("credit_usage_log")
        .insert(
            {
                "customer_id": customer_id,
                "generation_id": None,
                "credit_cost": credit_cost,
                "billing_period": billing_period,
                "cost_is_measured": True,
                "cost_source": cost_source,
            }
        )
        .execute()
        .data[0]
    )
    check_credit_threshold(client, customer_id)
    return entry


def generation_type(generation: dict) -> str:
    """Public — used by admin_panel._media_uploads_this_month to classify
    image vs. video for the §7 media-upload caps. NOT used for cost
    anymore (see module docstring) — cost is now keyed by template_id."""
    return "video" if generation.get("media_url") else "image"


def cost_for_template(client, template_id: str) -> tuple[float, bool]:
    """Returns (cost, is_measured). is_measured=False means template_id
    has no real measurement yet and this is FALLBACK_ESTIMATED_COST.

    §16 growth-rules Group A6 special case: a text-only X post
    (generation.start_text_only_generation) never calls Blotato at all —
    there's no media job to cost anything — so it's a real, measured 0,
    not the fallback guess a genuinely-unmeasured template would get."""
    if template_id == growth_rules.TEXT_ONLY_TEMPLATE_ID:
        return 0, True
    row = client.table("template_costs").select("credit_cost").eq("template_id", template_id).maybe_single().execute()
    if row and row.data:
        return row.data["credit_cost"], True
    return FALLBACK_ESTIMATED_COST, False


def snapshot_balance_if_unmeasured(client, template_id: str) -> int | None:
    """Call right before kicking off a real Blotato generation job for
    template_id (generation.start_generation, guardrails._retry). Returns
    the current real credit balance — to be stored as this generation's
    `credit_balance_before_start` and diffed once the job finishes (see
    generation._maybe_learn_template_cost) — only if template_id has no
    measured cost yet. Returns None (skip the extra API call; nothing to
    learn) once it's already measured."""
    _, is_measured = cost_for_template(client, template_id)
    if is_measured:
        return None
    return blotato_client.get_credit_balance()


def log_credit_usage(client, generation: dict) -> dict:
    cost, is_measured = cost_for_template(client, generation["template_id"])
    billing_period = datetime.now(timezone.utc).strftime("%Y-%m")

    client.table("generations").update({"estimated_credit_cost": cost}).eq("id", generation["id"]).execute()
    entry = (
        client.table("credit_usage_log")
        .insert(
            {
                "customer_id": generation["customer_id"],
                "generation_id": generation["id"],
                "credit_cost": cost,
                "billing_period": billing_period,
                "cost_is_measured": is_measured,
                "cost_source": "blotato_generation",
            }
        )
        .execute()
        .data[0]
    )
    check_credit_threshold(client, generation["customer_id"])
    return entry


def usage_this_period(client, customer_id: str) -> float:
    billing_period = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = (
        client.table("credit_usage_log")
        .select("credit_cost")
        .eq("customer_id", customer_id)
        .eq("billing_period", billing_period)
        .execute()
        .data
        or []
    )
    return sum(r["credit_cost"] for r in rows)


def check_credit_threshold(client, customer_id: str) -> None:
    customer = client.table("customers").select("credit_budget").eq("id", customer_id).maybe_single().execute()
    budget = (customer.data or {}).get("credit_budget") if customer else None
    if not budget:
        return  # no budget configured — nothing to flag against

    used = usage_this_period(client, customer_id)
    if used >= budget * CREDIT_THRESHOLD_FRACTION:
        # Soft flag, not a hard block — and don't spam: only notify once
        # per billing period per customer.
        billing_period = datetime.now(timezone.utc).strftime("%Y-%m")
        existing = (
            client.table("notifications")
            .select("id")
            .eq("customer_id", customer_id)
            .eq("type", "credit_threshold")
            .gte("created_at", f"{billing_period}-01")
            .execute()
            .data
        )
        if existing:
            return
        notifications.notify(
            client,
            recipient_type="admin",
            type_="credit_threshold",
            message=f"Customer has used {used:.0f}/{budget:.0f} estimated credits this billing period ({used/budget:.0%}).",
            customer_id=customer_id,
        )


POOL_CAP_THRESHOLD_FRACTION = 0.9
"""Notify once a pool is at 90% of its connection cap. Not specified in
the packet — a reasonable starting point."""


def check_pool_cap(client, pool: dict) -> None:
    if pool["connected_account_count"] < pool["cap"] * POOL_CAP_THRESHOLD_FRACTION:
        return
    existing = (
        client.table("notifications")
        .select("id")
        .eq("type", "pool_cap_approaching")
        .ilike("message", f"%{pool['id']}%")
        .eq("read_status", False)
        .execute()
        .data
    )
    if existing:
        return  # don't re-notify while an unread warning for this pool is still open
    notifications.notify(
        client,
        recipient_type="admin",
        type_="pool_cap_approaching",
        message=f"Blotato pool {pool['id']} ({pool['plan_tier']}) is at {pool['connected_account_count']}/{pool['cap']} connections.",
    )
