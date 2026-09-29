"""§16 target-account-picker follow-up (2026-09-06): the fix for the real
"approved but no target account" escalation found live in production —
approve_generation() can now be given a target account at approval time
(customer_hub.py's picker), and admin has a matching "Set target account &
retry" fix for one already stuck (see approval.set_target_account_and_retry_publish).

Mocks ONLY blotato_client.create_post — never the real publish endpoint,
per the standing rule established at the Phase 6 gate. Everything around
it (ownership checks, escalation resolution, the real DB writes) runs for
real against the live Supabase project.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.lib import approval


def _social_module_id(admin_client) -> str:
    return admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]


def _make_pending_generation(admin_client, customer_id: str, target_social_account_id: str | None = None) -> dict:
    return admin_client.table("generations").insert(
        {
            "customer_id": customer_id,
            "module_id": _social_module_id(admin_client),
            "template_id": "t",
            "prompt": "p",
            "post_caption": "test caption",
            "guardrail_status": "passed",
            "approval_status": "pending_review",
            "target_social_account_id": target_social_account_id,
            "publish_status": "not_published",
            "publish_retry_count": 0,
        }
    ).execute().data[0]


def _make_connected_account(admin_client, customer_id: str, platform: str = "instagram") -> dict:
    return admin_client.table("social_accounts").insert(
        {
            "customer_id": customer_id,
            "platform": platform,
            "source": "existing",
            "blotato_account_id": f"fake-{platform}-id",
            "connected_by_admin_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute().data[0]


def test_approve_generation_uses_picked_account_when_none_set(admin_client, temp_customer):
    account = _make_connected_account(admin_client, temp_customer["id"])
    gen = _make_pending_generation(admin_client, temp_customer["id"])

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        mock_create_post.return_value = {"postSubmissionId": "fake-submission-id"}
        result = approval.approve_generation(
            admin_client, gen, approved_by_user_id=None, customer_id=temp_customer["id"],
            target_social_account_id=account["id"],
        )

    assert result["target_social_account_id"] == account["id"]
    assert result["publish_status"] == "publishing"
    mock_create_post.assert_called_once()


def test_approve_generation_never_overrides_an_already_set_target_account(admin_client, temp_customer):
    """An admin-set target from Generate (Social) always wins — the
    picker only fills in a gap, it never silently overrides a choice
    already made."""
    original_account = _make_connected_account(admin_client, temp_customer["id"], platform="instagram")
    other_account = _make_connected_account(admin_client, temp_customer["id"], platform="tiktok")
    gen = _make_pending_generation(admin_client, temp_customer["id"], target_social_account_id=original_account["id"])

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        mock_create_post.return_value = {"postSubmissionId": "fake-submission-id"}
        result = approval.approve_generation(
            admin_client, gen, approved_by_user_id=None, customer_id=temp_customer["id"],
            target_social_account_id=other_account["id"],
        )

    assert result["target_social_account_id"] == original_account["id"]


def test_approve_generation_rejects_an_account_belonging_to_another_customer(admin_client, temp_customer_pair):
    customer_a, customer_b = temp_customer_pair
    account_b = _make_connected_account(admin_client, customer_b["id"])
    gen_a = _make_pending_generation(admin_client, customer_a["id"])

    with pytest.raises(PermissionError):
        approval.approve_generation(
            admin_client, gen_a, approved_by_user_id=None, customer_id=customer_a["id"],
            target_social_account_id=account_b["id"],
        )

    unchanged = admin_client.table("generations").select("target_social_account_id, approval_status").eq("id", gen_a["id"]).maybe_single().execute().data
    assert unchanged["target_social_account_id"] is None
    assert unchanged["approval_status"] == "pending_review", "The whole approval should be rejected, not partially applied"


def test_set_target_account_and_retry_publish_resolves_escalation_and_republishes(admin_client, temp_customer):
    """Reproduces the exact real-world stuck state: approved, no target
    account, escalated — then verifies admin's fix action resolves it."""
    account = _make_connected_account(admin_client, temp_customer["id"])
    gen = admin_client.table("generations").insert(
        {
            "customer_id": temp_customer["id"],
            "module_id": _social_module_id(admin_client),
            "template_id": "t",
            "prompt": "p",
            "post_caption": "test caption",
            "guardrail_status": "passed",
            "approval_status": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "target_social_account_id": None,
            "publish_status": "not_published",
            "publish_retry_count": 0,
        }
    ).execute().data[0]
    escalation = admin_client.table("escalations").insert(
        {
            "generation_id": gen["id"],
            "customer_id": temp_customer["id"],
            "reason": "publish",
            "details": {"error": "No target social account set on this generation."},
        }
    ).execute().data[0]

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        mock_create_post.return_value = {"postSubmissionId": "fake-submission-id"}
        result = approval.set_target_account_and_retry_publish(admin_client, gen, account["id"], escalation["id"])

    assert result["target_social_account_id"] == account["id"]
    assert result["publish_status"] == "publishing"
    mock_create_post.assert_called_once()

    resolved_escalation = admin_client.table("escalations").select("status").eq("id", escalation["id"]).maybe_single().execute().data
    assert resolved_escalation["status"] == "resolved"


def test_list_connectable_accounts_excludes_unconnected(admin_client, temp_customer):
    connected = _make_connected_account(admin_client, temp_customer["id"])
    admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "x", "source": "new"}
    ).execute()  # queued but never connected — connected_by_admin_at stays null

    accounts = approval.list_connectable_accounts(admin_client, temp_customer["id"])

    assert [a["id"] for a in accounts] == [connected["id"]]
