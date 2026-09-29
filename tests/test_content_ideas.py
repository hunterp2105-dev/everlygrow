"""§16 admin follow-up (2026-09-29): customer-facing content-idea
suggestions (app/lib/content_ideas.py) — the customer-side mirror of
admin's playbook suggestions. generate_batch() makes a REAL Claude call
(same discipline as test_guardrails.py's real evaluate() calls — this
isn't Blotato's real publish endpoint, which is the one call this
codebase never makes automatically) so the caching/refresh logic and the
real cost-logging are both tested against real behavior, not a mock.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.lib import content_ideas


def test_needs_refresh_true_when_no_ideas_exist(admin_client, temp_customer):
    assert content_ideas.needs_refresh(admin_client, temp_customer["id"]) is True


def _insert_idea(admin_client, customer_id, status="active", batch_generated_at=None):
    return admin_client.table("customer_content_ideas").insert(
        {
            "customer_id": customer_id,
            "title": "Test idea",
            "detail": "Test detail.",
            "category": "trust_building",
            "status": status,
            "batch_generated_at": (batch_generated_at or datetime.now(timezone.utc)).isoformat(),
        }
    ).execute().data[0]


def test_needs_refresh_false_for_a_fresh_batch_with_enough_active(admin_client, temp_customer):
    for _ in range(3):
        _insert_idea(admin_client, temp_customer["id"], status="active")
    assert content_ideas.needs_refresh(admin_client, temp_customer["id"]) is False


def test_needs_refresh_true_when_batch_is_stale(admin_client, temp_customer):
    stale = datetime.now(timezone.utc) - timedelta(days=content_ideas.REFRESH_AFTER_DAYS + 1)
    for _ in range(5):
        _insert_idea(admin_client, temp_customer["id"], status="active", batch_generated_at=stale)
    assert content_ideas.needs_refresh(admin_client, temp_customer["id"]) is True


def test_needs_refresh_true_when_too_few_active_remain(admin_client, temp_customer):
    _insert_idea(admin_client, temp_customer["id"], status="active")
    _insert_idea(admin_client, temp_customer["id"], status="used")
    _insert_idea(admin_client, temp_customer["id"], status="used")
    assert content_ideas.needs_refresh(admin_client, temp_customer["id"]) is True


def test_generate_batch_real_call_creates_ideas_and_logs_real_cost(admin_client, temp_customer):
    admin_client.table("customers").update({"niche": "Real Estate Agents"}).eq("id", temp_customer["id"]).execute()

    ideas = content_ideas.generate_batch(admin_client, temp_customer["id"])

    assert len(ideas) == content_ideas.BATCH_SIZE
    for idea in ideas:
        assert idea["category"] in content_ideas.CATEGORIES
        assert idea["title"]
        assert idea["detail"]
        assert idea["status"] == "active"

    usage = (
        admin_client.table("credit_usage_log")
        .select("*")
        .eq("customer_id", temp_customer["id"])
        .eq("cost_source", "claude_content_ideas")
        .execute()
        .data
    )
    assert len(usage) == 1
    assert usage[0]["credit_cost"] > 0
    assert usage[0]["cost_is_measured"] is True
    assert usage[0]["generation_id"] is None


def test_generate_batch_dismisses_the_previous_active_batch(admin_client, temp_customer):
    old = _insert_idea(admin_client, temp_customer["id"], status="active")

    content_ideas.generate_batch(admin_client, temp_customer["id"])

    old_after = admin_client.table("customer_content_ideas").select("status").eq("id", old["id"]).maybe_single().execute().data
    assert old_after["status"] == "dismissed"


def test_get_or_refresh_ideas_does_not_call_claude_again_when_cache_is_fresh(admin_client, temp_customer):
    for _ in range(5):
        _insert_idea(admin_client, temp_customer["id"], status="active")

    with patch("app.lib.content_ideas._client") as mock_client:
        result = content_ideas.get_or_refresh_ideas(admin_client, temp_customer["id"])

    mock_client.assert_not_called()
    assert len(result) == 5


def test_mark_used_changes_status(admin_client, temp_customer):
    idea = _insert_idea(admin_client, temp_customer["id"], status="active")
    content_ideas.mark_used(admin_client, idea["id"])
    updated = admin_client.table("customer_content_ideas").select("status").eq("id", idea["id"]).maybe_single().execute().data
    assert updated["status"] == "used"
