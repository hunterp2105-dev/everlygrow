"""Guardrail pipeline (§6), applied uniformly across both modules.

Six categories from §6, but only four of them are actual Claude calls:

1. Brand/tone consistency        -> Claude
2. Basic content safety          -> Claude
3. Factual/claims accuracy       -> Claude
4. Competitor/legal-sensitive    -> Claude
5. Voice selection compliance    -> deterministic code check (§6: "stock
   voices only, no cloning in MVP" — since there is no upload/cloning path
   anywhere in this product, this can only ever fail if a future bug
   introduces a voice value outside Blotato's stock list; not something an
   LLM needs to judge)
6. Quality bar ("premium, not AI  -> deferred, not automated (§6 says so
   slop")                           explicitly: "automated checks (1-5) are
                                     reliable, 'does this look premium' isn't
                                     reliably automatable yet — the mandatory
                                     customer approval step does most of the
                                     real work here")

Runs once, right when a generation's underlying Blotato job reaches
"ready" — wired into generation.poll_generation so it's the same code path
for Social and Video Design & Graphic Creator alike, per §16.

Retry/escalation (§9): a flagged/failed result retries the same generation
(same template/prompt) up to GUARDRAIL_MAX_RETRIES times; once exhausted,
it's written to the `escalations` table and an admin notification fires —
never fails silently.
"""

import json
import os
from datetime import datetime, timezone

from app.lib import blotato_client, credits, growth_rules, notifications
from app.lib.caps import GUARDRAIL_MAX_RETRIES
from app.lib.retry_policy import is_retryable_http_error

_ENGINE_FAILURE_MAX_ATTEMPTS = 2
"""Retries of the Claude call itself (not a content regeneration — see
_retry() below for that) when the call fails transiently (429/5xx/network).
A permanent failure (bad key, malformed request) breaks out immediately."""

CATEGORIES_FOR_CLAUDE = [
    "brand_tone_consistency",
    "content_safety",
    "factual_claims_accuracy",
    "competitor_legal_sensitive",
]

CATEGORY_LABELS = {
    "brand_tone_consistency": "Brand/tone consistency",
    "content_safety": "Basic content safety",
    "factual_claims_accuracy": "Factual/claims accuracy",
    "competitor_legal_sensitive": "Competitor/legal-sensitive topic filtering",
    "voice_selection_compliance": "Voice selection (voiceover only)",
    "quality_bar": "Quality bar",
}

_MODEL = "claude-sonnet-5"


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set (see .env.example) to run guardrail checks.")
    import anthropic

    return anthropic.Anthropic(api_key=key)


_RESULT_TOOL = {
    "name": "report_guardrail_results",
    "description": "Report the guardrail evaluation for each category.",
    "strict": True,
    # §16 admin follow-up (2026-09-29): same latent gap found and fixed in
    # content_ideas.py's tool — a forced tool-use call can occasionally
    # deviate from the declared schema without `strict: true` (confirmed
    # live on that tool; this one has never visibly failed, likely
    # because its schema is much simpler, but the exposure is identical).
    # Requires `additionalProperties: false` at every object level.
    "input_schema": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "object",
                "properties": {
                    cat: {
                        "type": "object",
                        "properties": {
                            "verdict": {"type": "string", "enum": ["pass", "flag", "fail"]},
                            "note": {"type": "string"},
                        },
                        "required": ["verdict", "note"],
                        "additionalProperties": False,
                    }
                    for cat in CATEGORIES_FOR_CLAUDE
                },
                "required": CATEGORIES_FOR_CLAUDE,
                "additionalProperties": False,
            }
        },
        "required": ["categories"],
        "additionalProperties": False,
    },
}


def _voice_selection_check(generation: dict) -> dict:
    voice_name = generation.get("voice_name")
    if not voice_name:
        return {"verdict": "pass", "note": "No voice used."}
    if voice_name in blotato_client.VOICES:
        return {"verdict": "pass", "note": f"Stock voice '{voice_name}' — no cloning path exists in this product."}
    return {"verdict": "fail", "note": f"Voice '{voice_name}' is not a recognized stock voice — should never happen."}


def _quality_bar_check() -> dict:
    return {
        "verdict": "pass",
        "note": "Not automated per §6 — deferred to mandatory customer approval.",
    }


def _claude_categories(generation: dict, customer: dict) -> dict:
    sensitivity = (customer.get("guardrail_config") or {}).get("sensitivity", "standard")
    niche = customer.get("niche", "General")

    content_parts = [
        {
            "type": "text",
            "text": (
                f"Customer niche: {niche}\n"
                f"Guardrail sensitivity: {sensitivity} (strict = flag readily on any ambiguity; "
                f"standard = flag clear issues; relaxed = only flag obvious violations)\n\n"
                f"Generation prompt (what was requested): {generation.get('prompt')}\n\n"
                "Evaluate this generated content against these categories:\n"
                "- brand_tone_consistency: does this read as generic AI output vs. authentic for the stated niche?\n"
                "- content_safety: any NSFW or offensive content?\n"
                "- factual_claims_accuracy: claims that would be materially misleading or risky if "
                "false — especially medical/financial/legal outcome claims, guarantees ('cures', "
                "'guaranteed', '100%'), or superiority claims over competitors. Do NOT flag routine, "
                "low-stakes descriptive marketing details (e.g. 'made fresh daily', a listing's stated "
                "bed/bath count, 'many customers love this') just because they're technically "
                "unverifiable from the text alone — flag only claims where being wrong would actually "
                "mislead or harm someone.\n"
                "- competitor_legal_sensitive: does it name competitors or touch legally sensitive topics?\n\n"
                "Call report_guardrail_results with a verdict + short note for each category."
            ),
        }
    ]
    if generation.get("image_urls"):
        for url in generation["image_urls"][:3]:
            content_parts.append({"type": "image", "source": {"type": "url", "url": url}})

    response = _client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        tools=[_RESULT_TOOL],
        tool_choice={"type": "tool", "name": "report_guardrail_results"},
        messages=[{"role": "user", "content": content_parts}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "report_guardrail_results":
            return {"categories": block.input["categories"], "usage": response.usage}
    raise RuntimeError("Claude did not return a report_guardrail_results tool call.")


def evaluate(generation: dict, customer: dict) -> dict:
    """Deliberately takes no `client` — this must stay callable standalone
    for guardrail-accuracy testing (see test_guardrails.py's known-bad/
    clean-example suites) without a real customer_id to log cost against.
    `usage` (the real Messages API usage object) is carried through in the
    return value instead, so the one real call site with an actual
    customer_id — review_ready_generation below — can log the real cost;
    see credits.log_claude_usage."""
    claude_result = _claude_categories(generation, customer)
    categories = dict(claude_result["categories"])
    categories["voice_selection_compliance"] = _voice_selection_check(generation)
    categories["quality_bar"] = _quality_bar_check()

    verdicts = {v["verdict"] for v in categories.values()}
    if "fail" in verdicts:
        overall = "failed"
    elif "flag" in verdicts:
        overall = "flagged"
    else:
        overall = "passed"

    return {"categories": categories, "overall": overall, "usage": claude_result["usage"]}


def review_ready_generation(client, generation: dict, customer: dict | None = None) -> dict:
    """Call this exactly once, right when a generation transitions to
    'ready' (see generation.poll_generation). Runs the same for Social and
    Video Design & Graphic Creator generations alike."""
    if customer is None:
        customer_response = (
            client.table("customers").select("*").eq("id", generation["customer_id"]).maybe_single().execute()
        )
        customer = customer_response.data if customer_response else {}

    result = None
    last_exc = None
    for attempt in range(_ENGINE_FAILURE_MAX_ATTEMPTS):
        try:
            result = evaluate(generation, customer)
            break
        except Exception as exc:  # noqa: BLE001 - never let a guardrail-engine error block the pipeline silently
            last_exc = exc
            if not is_retryable_http_error(exc):
                break  # permanent (e.g. bad API key, malformed request) — retrying is pointless

    if result is None:
        client.table("generations").update(
            {
                "guardrail_status": "flagged",
                "guardrail_results": {"error": str(last_exc)},
                "guardrail_checked_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", generation["id"]).execute()
        _escalate(client, generation, category=None, details={"error": f"Guardrail evaluation itself failed: {last_exc}"})
        return {"overall": "flagged", "error": str(last_exc)}

    # §16 admin follow-up (2026-09-29): log the real Claude spend for this
    # evaluation — found live that this call has run on every generation
    # since Phase 5 without ever being cost-logged. Logged here (not
    # inside evaluate()/_claude_categories) because this is the one real
    # call site with an actual customer_id to log against — see
    # evaluate()'s docstring. Only the successful attempt's usage is
    # logged; an attempt that raised before returning a response has no
    # usage to measure, and _ENGINE_FAILURE_MAX_ATTEMPTS discards those.
    if result.get("usage") is not None:
        credits.log_claude_usage(client, generation["customer_id"], result["usage"], cost_source="guardrail_evaluation")

    updated = (
        client.table("generations")
        .update(
            {
                "guardrail_status": result["overall"],
                "guardrail_results": result["categories"],
                "guardrail_checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", generation["id"])
        .execute()
        .data[0]
    )

    if result["overall"] in ("flagged", "failed"):
        _handle_non_pass(client, updated, result)
    else:
        # §9: "content ready for customer approval" — this is the actual
        # moment that becomes true: guardrail-passed content is what
        # approval.list_pending_approvals shows customers, nothing else.
        notifications.notify(
            client,
            recipient_type="customer",
            type_="approval_ready",
            message=f"New content is ready for your review: {generation.get('template_description') or generation['template_id']}",
            customer_id=generation["customer_id"],
        )

    return result


def _handle_non_pass(client, generation: dict, result: dict) -> None:
    # Found live (2026-09-11): a flagged text-only X post
    # (generation.start_text_only_generation, growth_rules.TEXT_ONLY_TEMPLATE_ID)
    # crashed with a real 404 from Blotato here — _retry() unconditionally
    # assumes every generation came from a real Blotato job it can kick
    # off again, which isn't true for a post with no media job at all.
    # There's no automated way to rewrite the text itself (no caption-
    # generation step exists), so straight to escalation instead of a
    # retry that can never succeed.
    is_retryable = generation["template_id"] != growth_rules.TEXT_ONLY_TEMPLATE_ID
    if is_retryable and generation["retry_count"] < GUARDRAIL_MAX_RETRIES:
        _retry(client, generation)
    else:
        flagged_categories = [cat for cat, v in result["categories"].items() if v["verdict"] != "pass"]
        _escalate(
            client,
            generation,
            category=", ".join(CATEGORY_LABELS.get(c, c) for c in flagged_categories),
            details=result["categories"],
        )


def _retry(client, generation: dict) -> None:
    # A retry kicks off a brand-new Blotato job — if this template's cost
    # is still unmeasured, re-snapshot the balance now (the ORIGINAL
    # attempt's snapshot, if any, is stale for this new job and gets
    # overwritten below) rather than measuring the combined cost of both
    # attempts against the first snapshot.
    credit_balance_before_start = credits.snapshot_balance_if_unmeasured(client, generation["template_id"])

    creation = blotato_client.create_from_template(
        generation["template_id"], generation["prompt"], voice_name=generation.get("voice_name")
    )
    client.table("generations").update(
        {
            "retry_count": generation["retry_count"] + 1,
            "blotato_creation_id": creation["id"],
            "blotato_status": creation.get("status", "queueing"),
            "status": "processing",
            "guardrail_status": "pending",
            "guardrail_results": None,
            "credit_balance_before_start": credit_balance_before_start,
            "media_url": None,
            "image_urls": None,
        }
    ).eq("id", generation["id"]).execute()

    notifications.notify(
        client,
        recipient_type="admin",
        type_="guardrail_retry",
        message=(
            f"Guardrail flagged '{generation.get('template_description') or generation['template_id']}' "
            f"— retrying automatically (attempt {generation['retry_count'] + 1}/{GUARDRAIL_MAX_RETRIES})."
        ),
        customer_id=generation["customer_id"],
    )


def _escalate(client, generation: dict, category: str | None, details: dict) -> None:
    client.table("escalations").insert(
        {
            "generation_id": generation["id"],
            "customer_id": generation["customer_id"],
            "reason": "guardrail",
            "category": category,
            "details": details,
        }
    ).execute()
    notifications.notify(
        client,
        recipient_type="admin",
        type_="guardrail_escalation",
        message=(
            f"Guardrail escalation: '{generation.get('template_description') or generation['template_id']}' "
            f"failed review after {GUARDRAIL_MAX_RETRIES} retries — needs admin attention."
        ),
        customer_id=generation["customer_id"],
    )


def list_open_escalations(client) -> list[dict]:
    response = (
        client.table("escalations")
        .select("*, generations(*), customers(name)")
        .eq("status", "open")
        .order("created_at")
        .execute()
    )
    return response.data or []


def resolve_escalation(client, escalation_id: str, resolution_note: str) -> None:
    client.table("escalations").update(
        {
            "status": "resolved",
            "resolution_note": resolution_note,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", escalation_id).execute()


def retry_escalated_generation(client, generation: dict) -> None:
    """Admin-triggered manual retry, bypassing the auto-retry cap — used
    from the Escalation Queue when admin wants to try again anyway."""
    _retry(client, generation)
