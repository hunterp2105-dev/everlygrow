"""Cost-model restructure follow-up to §16 step 49: real per-template
Blotato credit costs are learned in production (template_costs, migration
0012) rather than guessed from an image/video binary classification. This
tests the learning mechanism itself — snapshot before an unmeasured
template's job starts, diff after it finishes, persist — using a REAL
Blotato generation (cheap image template) for the "unmeasured" path, and
mocked balance reads for the already-measured / fallback paths (no need
to spend real credits re-proving arithmetic).
"""

import uuid
from unittest.mock import patch

from app.lib import credits, generation


def _social_module_id(admin_client) -> str:
    return admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]


def test_cost_for_template_returns_measured_flag_correctly(admin_client):
    measured_id = "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0"  # seeded by migration 0012
    cost, is_measured = credits.cost_for_template(admin_client, measured_id)
    assert is_measured is True
    assert cost == 0  # the real measured value seeded for this template

    unmeasured_id = f"never-used-template-{uuid.uuid4().hex[:8]}"
    cost, is_measured = credits.cost_for_template(admin_client, unmeasured_id)
    assert is_measured is False
    assert cost == credits.FALLBACK_ESTIMATED_COST


def test_snapshot_balance_if_unmeasured_skips_already_measured_templates(admin_client):
    measured_id = "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0"
    with patch("app.lib.blotato_client.get_credit_balance") as mock_balance:
        result = credits.snapshot_balance_if_unmeasured(admin_client, measured_id)
    assert result is None
    mock_balance.assert_not_called()


def test_snapshot_balance_if_unmeasured_calls_real_balance_for_new_template(admin_client):
    unmeasured_id = f"never-used-template-{uuid.uuid4().hex[:8]}"
    with patch("app.lib.blotato_client.get_credit_balance") as mock_balance:
        mock_balance.return_value = 500
        result = credits.snapshot_balance_if_unmeasured(admin_client, unmeasured_id)
    assert result == 500
    mock_balance.assert_called_once()


def test_generation_learns_real_cost_for_a_genuinely_new_template(admin_client, temp_customer):
    """Real end-to-end: a template never seen before gets its real cost
    learned via a real Blotato generation, persisted to template_costs,
    then used (not the fallback) for this same generation's credit_usage_log
    entry. Cleans up the learned row afterward so re-running this test
    doesn't just hit the 'already measured' path."""
    template_id = "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0"  # cheap/fast, but treated as brand-new for this test
    admin_client.table("template_costs").delete().eq("template_id", template_id).execute()
    try:
        gen = generation.start_generation(
            admin_client,
            customer_id=temp_customer["id"],
            module_id=_social_module_id(admin_client),
            template_id=template_id,
            template_description="Phase 13 cost-learning test",
            prompt="A short quote about persistence.",
        )
        assert gen["credit_balance_before_start"] is not None, "Should have snapshotted balance for a genuinely unmeasured template"

        import time

        deadline = time.monotonic() + 120
        while gen["status"] == "processing" and time.monotonic() < deadline:
            time.sleep(5)
            gen = generation.poll_generation(admin_client, gen)
        assert gen["status"] == "ready", f"Real generation never finished (blotato_status={gen.get('blotato_status')})"

        learned = admin_client.table("template_costs").select("*").eq("template_id", template_id).maybe_single().execute().data
        assert learned is not None, "Real completion should have persisted a learned cost row"
        assert learned["credit_cost"] >= 0

        gen_row = admin_client.table("generations").select("credit_balance_before_start, estimated_credit_cost").eq("id", gen["id"]).maybe_single().execute().data
        assert gen_row["credit_balance_before_start"] is None, "Snapshot column should be cleared once learned"
        assert gen_row["estimated_credit_cost"] == learned["credit_cost"], "This generation's own log should use the freshly-learned cost, not the fallback"

        # .maybe_single() here used to assume one credit_usage_log row per
        # generation — wrong whenever a guardrail retry happens (found live
        # 2026-09-03: this test's real Claude guardrail call flagged the
        # first attempt, _retry() reused this same generation row for a
        # second real Blotato job, and poll_generation correctly logged
        # usage again for that second real job, since it really did cost
        # real credits). Assert against the most recent entry instead of
        # assuming exactly one.
        usage_rows = (
            admin_client.table("credit_usage_log")
            .select("cost_is_measured, credit_cost, created_at")
            .eq("generation_id", gen["id"])
            .order("created_at", desc=True)
            .execute()
            .data
        )
        assert usage_rows, "Expected at least one credit_usage_log entry for this generation"
        assert usage_rows[0]["cost_is_measured"] is True
    finally:
        # Restore the real seeded measurement (0 credits) rather than
        # leaving whatever this test run happened to measure.
        admin_client.table("template_costs").delete().eq("template_id", template_id).execute()
        admin_client.table("template_costs").insert({"template_id": template_id, "credit_cost": 0}).execute()
