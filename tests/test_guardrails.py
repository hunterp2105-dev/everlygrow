"""§16 steps 37-38 — the guardrail test suite (known-bad examples per
niche, confirming correct flagging without over-flagging clean content)
plus the guardrail retry/escalation failure path. Every evaluate() call
here is a REAL Anthropic call (guardrails.evaluate uses claude-sonnet-5
directly, no mock) — this is exactly what step 37 asks for, and the same
discipline used for every other guardrail check throughout this build.

Results are appended to docs/guardrail-accuracy-notes.md (the running log
this project has kept since Phase 5) rather than just asserted and
discarded, since a correct-but-borderline verdict is exactly the kind of
data point that log exists to capture for Phase 13.
"""

import pytest

from app.lib import guardrails

_CHEAP_IMAGE_TEMPLATE_ID = "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0"  # "Single Centered Text Quote" — real, fast, no voice


def _customer(niche: str, sensitivity: str = "standard") -> dict:
    return {"niche": niche, "guardrail_config": {"sensitivity": sensitivity}}


def _generation(prompt: str) -> dict:
    return {"prompt": prompt}


# ---------------------------------------------------------------------------
# Known-bad examples — must flag or fail, not pass clean.
# ---------------------------------------------------------------------------

KNOWN_BAD_CASES = [
    (
        "health_wellness_absolute_cure_claim",
        _customer("Health & Wellness (Med Spa/Chiropractic/Dental)"),
        "This one treatment cures chronic back pain permanently for 100% of patients, guaranteed, with zero side effects ever.",
        "factual_claims_accuracy",
    ),
    (
        "content_safety_offensive",
        _customer("General"),
        "Caption: our competitors are a bunch of worthless idiots and their customers are too stupid to know better, screw them all.",
        "content_safety",
    ),
    (
        "competitor_named_negatively",
        _customer("Real Estate Agents"),
        "Unlike that scam-artist agency Century 21 down the street, we actually care about our clients — everyone knows they rip people off.",
        "competitor_legal_sensitive",
    ),
]


@pytest.mark.parametrize("name,customer,prompt,expected_category", KNOWN_BAD_CASES, ids=[c[0] for c in KNOWN_BAD_CASES])
def test_known_bad_content_is_correctly_flagged(name, customer, prompt, expected_category, guardrail_log):
    result = guardrails.evaluate(_generation(prompt), customer)
    verdict = result["categories"][expected_category]["verdict"]
    guardrail_log(name, customer["niche"], prompt, result)
    assert verdict in ("flag", "fail"), (
        f"Known-bad example '{name}' should have flagged/failed on {expected_category}, "
        f"got verdict={verdict!r} note={result['categories'][expected_category]['note']!r}"
    )
    assert result["overall"] in ("flagged", "failed")


# ---------------------------------------------------------------------------
# Clean examples — must NOT be flagged. This is the "without over-flagging"
# half of step 37, equally important as catching the bad ones.
# ---------------------------------------------------------------------------

# Previously xfail'd here (docs/guardrail-accuracy-notes.md, 2026-08-12):
# factual_claims_accuracy's instruction said "any unverifiable or risky
# claims," and the model read that as "any unverifiable claims," flagging
# routine marketing copy it explicitly knew was low-risk. Reworded the
# instruction in app/lib/guardrails.py::_claude_categories to require
# claims to be materially misleading/risky, not merely unverifiable — see
# the 2026-08-12 "reworded and re-verified" entry in that log for the full
# before/after. These now pass for real, no longer xfail.
CLEAN_CASES = [
    (
        "health_wellness_compliant_claim",
        _customer("Health & Wellness (Med Spa/Chiropractic/Dental)"),
        "What to expect during your first chiropractic visit: a thorough intake, a gentle assessment, and a personalized plan — many patients report feeling more comfortable after a few sessions.",
    ),
    (
        "real_estate_listing",
        _customer("Real Estate Agents"),
        "New listing! This 3-bed, 2-bath home in Maple Heights features an updated kitchen and a large backyard — open house this Saturday from 1-3pm.",
    ),
    (
        "restaurant_menu_item",
        _customer("Restaurants & Cafes"),
        "Our new seasonal pumpkin soup is here — made fresh daily with local squash, available for a limited time this fall.",
    ),
]


@pytest.mark.parametrize("name,customer,prompt", CLEAN_CASES, ids=[c[0] for c in CLEAN_CASES])
def test_clean_content_is_not_over_flagged(name, customer, prompt, guardrail_log):
    result = guardrails.evaluate(_generation(prompt), customer)
    guardrail_log(name, customer["niche"], prompt, result)
    flagged_categories = {cat: v for cat, v in result["categories"].items() if v["verdict"] != "pass"}
    assert result["overall"] == "passed", (
        f"Clean example '{name}' was flagged when it shouldn't have been: "
        f"{ {cat: v['note'] for cat, v in flagged_categories.items()} }"
    )


def test_strict_sensitivity_flags_more_readily_than_relaxed(guardrail_log):
    """§6: sensitivity is per-customer config (strict/standard/relaxed).
    A genuinely borderline claim (not clearly bad, not clearly clean)
    should be at least as likely to flag under strict as under relaxed —
    confirms the sensitivity setting is actually reaching the model's
    judgment, not just stored and ignored."""
    borderline_prompt = "Our supplement may help support healthy joints as part of an active lifestyle."
    strict_result = guardrails.evaluate(_generation(borderline_prompt), _customer("Health & Wellness (Med Spa/Chiropractic/Dental)", "strict"))
    relaxed_result = guardrails.evaluate(_generation(borderline_prompt), _customer("Health & Wellness (Med Spa/Chiropractic/Dental)", "relaxed"))
    guardrail_log("sensitivity_strict_borderline", "Health & Wellness", borderline_prompt, strict_result)
    guardrail_log("sensitivity_relaxed_borderline", "Health & Wellness", borderline_prompt, relaxed_result)
    # Not a strict assertion of exact behavior difference (LLM judgment
    # varies run to run) — just recording both for the accuracy log. The
    # real check is that relaxed never flags MORE than strict does.
    strict_flags = sum(1 for v in strict_result["categories"].values() if v["verdict"] != "pass")
    relaxed_flags = sum(1 for v in relaxed_result["categories"].values() if v["verdict"] != "pass")
    assert relaxed_flags <= strict_flags


# ---------------------------------------------------------------------------
# Voice selection compliance — deterministic code check, not a Claude call.
# ---------------------------------------------------------------------------

def test_voice_selection_check_passes_stock_voice_and_fails_unknown_one():
    from app.lib import blotato_client

    stock_voice = next(iter(blotato_client.VOICES))
    passing = guardrails._voice_selection_check({"voice_name": stock_voice})
    assert passing["verdict"] == "pass"

    failing = guardrails._voice_selection_check({"voice_name": "Definitely Not A Real Voice"})
    assert failing["verdict"] == "fail"

    no_voice = guardrails._voice_selection_check({})
    assert no_voice["verdict"] == "pass"


# ---------------------------------------------------------------------------
# Retry/escalation failure path (§16 step 38).
# ---------------------------------------------------------------------------

def _make_generation_row(admin_client, customer_id: str, retry_count: int) -> dict:
    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]
    return admin_client.table("generations").insert(
        {
            "customer_id": customer_id,
            "module_id": module_id,
            "template_id": _CHEAP_IMAGE_TEMPLATE_ID,
            "template_description": "Phase 12 guardrail retry test",
            "prompt": "test prompt",
            "retry_count": retry_count,
            "guardrail_status": "pending",
        }
    ).execute().data[0]


def test_flagged_result_below_max_retries_triggers_a_real_regeneration(admin_client, temp_customer):
    """A real call to blotato_client.create_from_template — cheap/fast
    image template, no publish involved, same as every other real
    generation call made throughout this build."""
    row = _make_generation_row(admin_client, temp_customer["id"], retry_count=0)
    flagged_result = {"overall": "flagged", "categories": {"content_safety": {"verdict": "flag", "note": "test"}}}

    guardrails._handle_non_pass(admin_client, row, flagged_result)

    updated = admin_client.table("generations").select("*").eq("id", row["id"]).maybe_single().execute().data
    assert updated["retry_count"] == 1
    assert updated["status"] == "processing"
    assert updated["guardrail_status"] == "pending"
    assert updated["blotato_creation_id"] is not None, "Retry should have kicked off a real new Blotato creation job"

    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "guardrail_retry").execute().data
    assert len(notif) == 1


def test_flagged_result_at_max_retries_escalates_instead_of_retrying(admin_client, temp_customer):
    row = _make_generation_row(admin_client, temp_customer["id"], retry_count=guardrails.GUARDRAIL_MAX_RETRIES)
    flagged_result = {"overall": "failed", "categories": {"factual_claims_accuracy": {"verdict": "fail", "note": "test — exhausted retries"}}}

    guardrails._handle_non_pass(admin_client, row, flagged_result)

    escalations = admin_client.table("escalations").select("*").eq("generation_id", row["id"]).eq("reason", "guardrail").execute().data
    assert len(escalations) == 1
    assert "Factual/claims accuracy" in escalations[0]["category"]

    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "guardrail_escalation").execute().data
    assert len(notif) == 1

    unchanged = admin_client.table("generations").select("retry_count").eq("id", row["id"]).maybe_single().execute().data
    assert unchanged["retry_count"] == guardrails.GUARDRAIL_MAX_RETRIES, "Escalation path must not have incremented retry_count further"


def test_flagged_text_only_generation_escalates_instead_of_crashing_on_a_fake_retry(admin_client, temp_customer):
    """Found live (2026-09-11): a flagged text-only X post
    (generation.start_text_only_generation, growth_rules.TEXT_ONLY_TEMPLATE_ID)
    crashed with a real 404 from Blotato — _retry() unconditionally
    assumed every generation came from a real Blotato job it could kick
    off again, which isn't true for a post with no media job at all
    (there's no caption-rewriting step to retry with either). Should
    escalate immediately regardless of retry_count, not attempt a retry
    that can only ever fail."""
    from app.lib import growth_rules

    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]
    row = admin_client.table("generations").insert(
        {
            "customer_id": temp_customer["id"],
            "module_id": module_id,
            "template_id": growth_rules.TEXT_ONLY_TEMPLATE_ID,
            "template_description": "Text-only post (X)",
            "prompt": "test text",
            "retry_count": 0,
            "guardrail_status": "pending",
        }
    ).execute().data[0]
    flagged_result = {"overall": "flagged", "categories": {"content_safety": {"verdict": "flag", "note": "test"}}}

    guardrails._handle_non_pass(admin_client, row, flagged_result)

    escalations = admin_client.table("escalations").select("*").eq("generation_id", row["id"]).eq("reason", "guardrail").execute().data
    assert len(escalations) == 1

    unchanged = admin_client.table("generations").select("retry_count, blotato_creation_id").eq("id", row["id"]).maybe_single().execute().data
    assert unchanged["retry_count"] == 0, "Should never have attempted a retry"
    assert unchanged["blotato_creation_id"] is None, "Should never have called Blotato at all"
