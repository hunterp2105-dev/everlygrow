"""§16 step 41 — cross-module test. Generates real content through BOTH
Social and Video Design & Graphic Creator for the same customer in one
pass, using cheap/fast real image templates (no voice, no video render —
keeps real Blotato wait time to under a minute each), and confirms the
Hub's shared surfaces (approval queue, calendar) reflect both correctly —
proving the "one generic engine, module_id is just a tag" architecture
(app/lib/generation.py) actually holds across modules, not just within one.

Mocks only the two Blotato publish HTTP calls for the Social side (per the
standing rule — never call the real publish endpoint from an automated
test). The Video Design side needs no mocking at all: it has no publish
step, so its full pipeline (generation -> guardrails -> approval ->
delivered) runs completely for real.
"""

import time
from unittest.mock import patch

from app.lib import approval, calendar as calendar_module, design, generation

_SOCIAL_TEMPLATE_ID = "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0"  # Single Centered Text Quote (image, fast)
_DESIGN_TEMPLATE_ID = "013904bf-6b3b-43f4-bb1f-f1964a38c29b"  # TV Wall Infographic (image, fast)


def _poll_until_ready(admin_client, generation_row: dict, timeout_seconds: int = 180) -> dict:
    deadline = time.monotonic() + timeout_seconds
    row = generation_row
    while row["status"] == "processing" and time.monotonic() < deadline:
        time.sleep(5)
        row = generation.poll_generation(admin_client, row)
    return row


def test_social_and_design_generation_both_reflected_in_hub(admin_client, temp_customer):
    from datetime import date, timedelta

    modules = {m["key"]: m for m in admin_client.table("modules").select("id, key").execute().data}
    social_module_id = modules["social"]["id"]
    design_module_id = modules["video_design_graphic_creator"]["id"]

    social_account = admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "instagram", "source": "existing", "blotato_account_id": "fake-id"}
    ).execute().data[0]

    social_gen = generation.start_generation(
        admin_client,
        customer_id=temp_customer["id"],
        module_id=social_module_id,
        template_id=_SOCIAL_TEMPLATE_ID,
        template_description="Phase 12 cross-module test — Social",
        prompt="A short motivational quote about consistency for a general small business audience.",
        target_social_account_id=social_account["id"],
        post_caption="Consistency beats intensity. #smallbusiness",
    )
    design_request = design.create_design_request(
        admin_client,
        customer_id=temp_customer["id"],
        module_id=design_module_id,
        deliverable_type="flyer",
        occasion="Phase 12 cross-module test — Design",
        template_id=_DESIGN_TEMPLATE_ID,
        template_description="Phase 12 cross-module test — Design",
        prompt="A simple infographic flyer with 3 quick tips for a general small business audience.",
    )

    social_gen = _poll_until_ready(admin_client, social_gen)
    design_gen = _poll_until_ready(admin_client, design_request["generation"])

    assert social_gen["status"] == "ready", f"Social generation never reached ready (Blotato status: {social_gen.get('blotato_status')})"
    assert design_gen["status"] == "ready", f"Design generation never reached ready (Blotato status: {design_gen.get('blotato_status')})"

    # Both went through the SAME real guardrail pipeline (app/lib/guardrails.py)
    # regardless of module — re-fetch to see the post-guardrail state.
    social_gen = admin_client.table("generations").select("*").eq("id", social_gen["id"]).maybe_single().execute().data
    design_gen = admin_client.table("generations").select("*").eq("id", design_gen["id"]).maybe_single().execute().data
    assert social_gen["guardrail_status"] in ("passed", "flagged", "failed")
    assert design_gen["guardrail_status"] in ("passed", "flagged", "failed")

    # Hub surface #1: the approval queue (shared across modules) — should
    # show whichever of the two actually passed guardrails as pending
    # customer review, tagged with the right module.
    pending = approval.list_pending_approvals(admin_client, temp_customer["id"])
    pending_ids = {row["id"] for row in pending}
    if social_gen["guardrail_status"] == "passed":
        assert social_gen["id"] in pending_ids
    if design_gen["guardrail_status"] == "passed":
        assert design_gen["id"] in pending_ids

    # Approve whichever passed. Social's publish call is mocked (standing
    # rule); Design has no publish step at all — runs for real.
    if social_gen["guardrail_status"] == "passed":
        with patch("app.lib.blotato_client.create_post") as mock_create_post, patch("app.lib.blotato_client.get_post") as mock_get_post:
            mock_create_post.return_value = {"postSubmissionId": "fake-cross-module-submission"}
            mock_get_post.return_value = {"status": "published", "publicUrl": "https://example.com/cross-module-test"}
            approval.approve_generation(admin_client, social_gen, approved_by_user_id=None, customer_id=temp_customer["id"])
            approval.poll_publish(admin_client, admin_client.table("generations").select("*").eq("id", social_gen["id"]).maybe_single().execute().data)

    if design_gen["guardrail_status"] == "passed":
        approval.approve_generation(admin_client, design_gen, approved_by_user_id=None, customer_id=temp_customer["id"])

    # Hub surface #2: the calendar — should now show a "post" event (Social,
    # once published) and/or a "deliverable" event (Design, once delivered),
    # for the SAME customer, via the exact same customer_calendar() call.
    events = calendar_module.customer_calendar(admin_client, temp_customer["id"], date.today() - timedelta(days=1), date.today() + timedelta(days=1))
    event_types = {e["type"] for e in events}
    if social_gen["guardrail_status"] == "passed":
        assert "post" in event_types, "Published Social content did not appear as a calendar 'post' event"
    if design_gen["guardrail_status"] == "passed":
        assert "deliverable" in event_types, "Delivered Design content did not appear as a calendar 'deliverable' event"

    assert social_gen["guardrail_status"] == "passed" or design_gen["guardrail_status"] == "passed", (
        "Both generations were flagged/failed by guardrails — inconclusive for the Hub-reflection assertions above "
        "(re-run; this is guardrail variance, not a cross-module architecture problem)."
    )
