"""§16 step 38 — the "video timeout" failure path. This is the gap
surfaced and fixed while writing this test (see app/lib/generation.py's
GENERATION_STALE_TIMEOUT_MINUTES docstring): before this phase, a
generation stuck in Blotato's 'processing' state forever had no path to
ever becoming 'failed' — poll_generation would no-op on it indefinitely.

Mocks only blotato_client.get_creation (Blotato's own service can't be
made to actually hang on demand for a test) — everything else (the real
Supabase row, the real staleness math, the real terminal-transition
notification) runs for real.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.lib import generation


def _make_generation(admin_client, customer_id: str, module_id: str, created_at: datetime) -> dict:
    row = admin_client.table("generations").insert(
        {
            "customer_id": customer_id,
            "module_id": module_id,
            "template_id": "t",
            "prompt": "p",
            "blotato_creation_id": "fake-creation-id",
            "blotato_status": "generating-media",
            "status": "processing",
        }
    ).execute().data[0]
    admin_client.table("generations").update({"created_at": created_at.isoformat()}).eq("id", row["id"]).execute()
    return admin_client.table("generations").select("*").eq("id", row["id"]).maybe_single().execute().data


def _social_module_id(admin_client) -> str:
    return admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]


def test_generation_stuck_processing_past_timeout_gets_marked_failed(admin_client, temp_customer):
    old_created_at = datetime.now(timezone.utc) - timedelta(minutes=generation.GENERATION_STALE_TIMEOUT_MINUTES + 5)
    row = _make_generation(admin_client, temp_customer["id"], _social_module_id(admin_client), old_created_at)

    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        # Blotato itself still reports it as processing/never-resolved —
        # exactly the orphaned-job scenario this fix targets.
        mock_get_creation.return_value = {"status": "generating-media"}
        result = generation.poll_generation(admin_client, row)

    assert result["status"] == "failed"
    assert result["blotato_status"] == "timeout-exceeded"

    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "generation_failed").execute().data
    assert len(notif) == 1, "Timed-out generation should fire the same generation_failed notification as any other failure"


def test_generation_still_within_timeout_window_is_left_processing(admin_client, temp_customer):
    recent_created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    row = _make_generation(admin_client, temp_customer["id"], _social_module_id(admin_client), recent_created_at)

    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        mock_get_creation.return_value = {"status": "generating-media"}
        result = generation.poll_generation(admin_client, row)

    assert result["status"] == "processing", "A generation well within the timeout window should not be force-failed"


def test_generation_that_genuinely_finishes_is_unaffected_by_staleness_check(admin_client, temp_customer):
    """The staleness check must only kick in when Blotato is STILL
    reporting non-terminal — a genuinely-finished job (even an old one,
    e.g. after a slow real video render) must resolve normally."""
    old_created_at = datetime.now(timezone.utc) - timedelta(minutes=generation.GENERATION_STALE_TIMEOUT_MINUTES + 5)
    row = _make_generation(admin_client, temp_customer["id"], _social_module_id(admin_client), old_created_at)

    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        mock_get_creation.return_value = {"status": "done", "mediaUrl": "http://example.com/v.mp4"}
        with patch("app.lib.guardrails.review_ready_generation") as mock_guardrails:
            mock_guardrails.return_value = {"overall": "passed", "categories": {}}
            result = generation.poll_generation(admin_client, row)

    assert result["status"] == "ready"
    assert result["blotato_status"] == "done"


def test_slow_running_generation_fires_intermediate_notification_once(admin_client, temp_customer):
    """§16 step 50: a job past GENERATION_SLOW_WARNING_MINUTES but still
    well short of the failure timeout should get a real-time heads-up
    notification — not silence, and not a failure."""
    old_created_at = datetime.now(timezone.utc) - timedelta(minutes=generation.GENERATION_SLOW_WARNING_MINUTES + 1)
    row = _make_generation(admin_client, temp_customer["id"], _social_module_id(admin_client), old_created_at)

    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        mock_get_creation.return_value = {"status": "generating-media"}
        result = generation.poll_generation(admin_client, row)

    assert result["status"] == "processing", "Should still be processing, not failed, this far below the staleness timeout"
    assert result["slow_notification_sent_at"] is not None

    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "generation_slow").execute().data
    assert len(notif) == 1

    # Poll again — same job, still slow. Must NOT re-notify.
    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        mock_get_creation.return_value = {"status": "generating-media"}
        result2 = generation.poll_generation(admin_client, result)

    assert result2["status"] == "processing"
    notif_after_second_poll = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "generation_slow").execute().data
    assert len(notif_after_second_poll) == 1, "Should not fire a second 'still slow' notification for the same generation"


def test_insufficient_credits_is_a_real_terminal_failure_with_reason_surfaced(admin_client, temp_customer):
    """Found live (2026-09-03): two real generations hit Blotato's real
    "insufficient-credits" status and sat as "processing" forever because
    it was missing from _BLOTATO_TO_INTERNAL — anything unmapped falls
    through to "processing". Confirms it's now a real failure, and that
    the reason is surfaced in the notification rather than a bare
    "failed"."""
    row = _make_generation(admin_client, temp_customer["id"], _social_module_id(admin_client), datetime.now(timezone.utc))

    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        mock_get_creation.return_value = {"status": "insufficient-credits"}
        result = generation.poll_generation(admin_client, row)

    assert result["status"] == "failed"
    assert result["blotato_status"] == "insufficient-credits"

    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "generation_failed").execute().data
    assert len(notif) == 1
    assert "insufficient-credits" in notif[0]["message"]


def test_generation_below_slow_warning_threshold_does_not_notify(admin_client, temp_customer):
    recent_created_at = datetime.now(timezone.utc) - timedelta(minutes=generation.GENERATION_SLOW_WARNING_MINUTES - 1)
    row = _make_generation(admin_client, temp_customer["id"], _social_module_id(admin_client), recent_created_at)

    with patch("app.lib.blotato_client.get_creation") as mock_get_creation:
        mock_get_creation.return_value = {"status": "generating-media"}
        result = generation.poll_generation(admin_client, row)

    assert result["status"] == "processing"
    assert result["slow_notification_sent_at"] is None
    notif = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "generation_slow").execute().data
    assert notif == []
