"""§16 step 38 — publish retry/failure path. Mocks ONLY the two outbound
Blotato HTTP calls (blotato_client.create_post / get_post) — never the
real endpoint, per the standing rule established at the Phase 6 gate
(Blotato's real publish endpoint is never called by an automated test,
since it posts to a customer's real connected account). Everything around
those two calls — retry counting, is_retryable_http_error's 4xx-vs-5xx
distinction, escalation rows, notifications — runs for real against the
live Supabase project.
"""

from unittest.mock import Mock, patch

from app.lib import approval
from app.lib.caps import GUARDRAIL_MAX_RETRIES as PUBLISH_MAX_RETRIES


def _make_approved_generation(admin_client, customer_id: str, social_account_id: str | None) -> dict:
    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]
    row = admin_client.table("generations").insert(
        {
            "customer_id": customer_id,
            "module_id": module_id,
            "template_id": "t",
            "prompt": "p",
            "post_caption": "test caption",
            "target_social_account_id": social_account_id,
            "publish_status": "not_published",
            "publish_retry_count": 0,
        }
    ).execute().data[0]
    return row


def _http_error(status_code: int) -> Exception:
    exc = Exception(f"HTTP {status_code}")
    exc.response = Mock(status_code=status_code)
    return exc


def test_permanent_failure_escalates_immediately_without_retrying(admin_client, temp_customer):
    social_account = admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "instagram", "source": "existing", "blotato_account_id": "fake-id"}
    ).execute().data[0]
    gen = _make_approved_generation(admin_client, temp_customer["id"], social_account["id"])

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        mock_create_post.side_effect = _http_error(400)  # malformed request — permanent, per retry_policy
        result = approval._publish(admin_client, gen)

    assert mock_create_post.call_count == 1, "A permanent (400) failure should not be retried at all"
    assert result["publish_status"] == "failed"

    escalations = admin_client.table("escalations").select("*").eq("generation_id", gen["id"]).eq("reason", "publish").execute().data
    assert len(escalations) == 1
    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "publish_escalation").execute().data
    assert len(notif) == 1


def test_transient_failure_retries_up_to_max_then_escalates(admin_client, temp_customer):
    social_account = admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "instagram", "source": "existing", "blotato_account_id": "fake-id"}
    ).execute().data[0]
    gen = _make_approved_generation(admin_client, temp_customer["id"], social_account["id"])

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        mock_create_post.side_effect = _http_error(503)  # transient — retryable per retry_policy
        result = approval._publish(admin_client, gen)

    # One initial attempt + PUBLISH_MAX_RETRIES retries, each of which
    # re-enters _publish via _handle_publish_failure's recursive retry.
    assert mock_create_post.call_count == 1 + PUBLISH_MAX_RETRIES
    assert result["publish_status"] == "failed"
    assert result["publish_retry_count"] == PUBLISH_MAX_RETRIES

    escalations = admin_client.table("escalations").select("*").eq("generation_id", gen["id"]).eq("reason", "publish").execute().data
    assert len(escalations) == 1

    retry_notifs = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "publish_retry").execute().data
    assert len(retry_notifs) == PUBLISH_MAX_RETRIES


def test_successful_publish_after_one_transient_retry(admin_client, temp_customer):
    social_account = admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "instagram", "source": "existing", "blotato_account_id": "fake-id"}
    ).execute().data[0]
    gen = _make_approved_generation(admin_client, temp_customer["id"], social_account["id"])

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        mock_create_post.side_effect = [_http_error(503), {"postSubmissionId": "fake-submission-id"}]
        result = approval._publish(admin_client, gen)

    assert mock_create_post.call_count == 2
    assert result["publish_status"] == "publishing"
    assert result["blotato_post_id"] == "fake-submission-id"

    escalations = admin_client.table("escalations").select("*").eq("generation_id", gen["id"]).execute().data
    assert escalations == [], "A publish that succeeds on retry should never escalate"


def test_publish_with_no_target_account_escalates_instead_of_crashing(admin_client, temp_customer):
    """Found live (2026-09-06): a real customer's first-ever approval that
    reached _publish crashed with a postgrest 22P02 error instead of
    reaching the "no account" escalation path below — because
    target_social_account_id was None (this generation was started with no
    connected account selected) and supabase-py's .eq() has no special
    case for None, so it sent the literal string "None" as the filter
    value, which Postgres rejected as an invalid uuid before the query
    could return zero rows. _publish now checks for a missing
    target_social_account_id before ever querying for it."""
    gen = _make_approved_generation(admin_client, temp_customer["id"], social_account_id=None)

    with patch("app.lib.blotato_client.create_post") as mock_create_post:
        result = approval._publish(admin_client, gen)

    assert mock_create_post.call_count == 0, "Should never reach the real Blotato call with no target account"
    assert result["publish_status"] == "not_published", "Should be left alone, not marked failed/publishing"
    assert result["blotato_post_id"] is None

    escalations = admin_client.table("escalations").select("*").eq("generation_id", gen["id"]).eq("reason", "publish").execute().data
    assert len(escalations) == 1
    assert "No target social account" in escalations[0]["details"]["error"]


def test_poll_publish_records_published_url_and_notifies(admin_client, temp_customer):
    social_account = admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "instagram", "source": "existing", "blotato_account_id": "fake-id"}
    ).execute().data[0]
    gen = _make_approved_generation(admin_client, temp_customer["id"], social_account["id"])
    admin_client.table("generations").update({"publish_status": "publishing", "blotato_post_id": "fake-submission-id"}).eq("id", gen["id"]).execute()
    gen = admin_client.table("generations").select("*").eq("id", gen["id"]).maybe_single().execute().data

    with patch("app.lib.blotato_client.get_post") as mock_get_post:
        mock_get_post.return_value = {"postSubmissionId": "fake-submission-id", "status": "published", "publicUrl": "https://example.com/p/123"}
        result = approval.poll_publish(admin_client, gen)

    assert result["publish_status"] == "published"
    assert result["post_url"] == "https://example.com/p/123"
    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "publish_success").execute().data
    assert len(notif) == 1
