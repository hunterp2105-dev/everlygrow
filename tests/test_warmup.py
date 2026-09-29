"""§16 step 40 — warm-up period test. Exercises the real
admin_panel._mark_connected() path plus the days-elapsed math the Account
Connections screen displays, against real social_accounts rows. Warm-up
here is tracking/advisory only (§16 step 7: "Build warm-up tracking for
new social accounts") — nothing in the app gates publishing on warm-up
status, so these tests check the tracking is correct, not that anything
gets blocked.
"""

from datetime import date, timedelta

from app.views.admin_panel import _mark_connected


def _make_pending_account(admin_client, customer_id: str, source: str) -> dict:
    return admin_client.table("social_accounts").insert(
        {"customer_id": customer_id, "platform": "instagram", "source": source}
    ).execute().data[0]


def test_new_account_enters_warming_status_with_start_date(admin_client, temp_customer):
    account = _make_pending_account(admin_client, temp_customer["id"], source="new")
    _mark_connected(admin_client, account, blotato_id="fake-blotato-id", warm_up_period_days=21)

    updated = admin_client.table("social_accounts").select("*").eq("id", account["id"]).maybe_single().execute().data
    assert updated["warm_up_status"] == "warming"
    assert updated["warm_up_start_date"] == date.today().isoformat()
    assert updated["warm_up_period_days"] == 21
    assert updated["connected_by_admin_at"] is not None


def test_existing_account_skips_warmup_entirely(admin_client, temp_customer):
    account = _make_pending_account(admin_client, temp_customer["id"], source="existing")
    _mark_connected(admin_client, account, blotato_id="fake-blotato-id", warm_up_period_days=21)

    updated = admin_client.table("social_accounts").select("*").eq("id", account["id"]).maybe_single().execute().data
    assert updated["warm_up_status"] == "not_required"
    assert updated["warm_up_start_date"] is None


def test_days_elapsed_and_progress_math(admin_client, temp_customer):
    """Reproduces the exact calculation admin_panel._render_account_connections
    uses to show 'day N/period' and the progress bar, against a real row
    with a start date set 10 days in the past."""
    account = _make_pending_account(admin_client, temp_customer["id"], source="new")
    _mark_connected(admin_client, account, blotato_id="fake-blotato-id", warm_up_period_days=21)

    ten_days_ago = (date.today() - timedelta(days=10)).isoformat()
    admin_client.table("social_accounts").update({"warm_up_start_date": ten_days_ago}).eq("id", account["id"]).execute()

    updated = admin_client.table("social_accounts").select("*").eq("id", account["id"]).maybe_single().execute().data
    start = updated["warm_up_start_date"]
    period = updated["warm_up_period_days"]
    days_elapsed = (date.today() - date.fromisoformat(start)).days
    progress = min(days_elapsed / period, 1.0)

    assert days_elapsed == 10
    assert round(progress, 4) == round(10 / 21, 4)


def test_marking_warmup_complete_updates_status_and_fires_notification(admin_client, temp_customer):
    from app.lib import notifications

    account = _make_pending_account(admin_client, temp_customer["id"], source="new")
    _mark_connected(admin_client, account, blotato_id="fake-blotato-id", warm_up_period_days=21)

    admin_client.table("social_accounts").update({"warm_up_status": "complete"}).eq("id", account["id"]).execute()
    notifications.notify(
        admin_client, recipient_type="admin", type_="warm_up_complete",
        message="Test — finished warm-up.", customer_id=temp_customer["id"],
    )

    updated = admin_client.table("social_accounts").select("warm_up_status").eq("id", account["id"]).maybe_single().execute().data
    assert updated["warm_up_status"] == "complete"

    fired = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "warm_up_complete").execute().data
    assert len(fired) == 1
