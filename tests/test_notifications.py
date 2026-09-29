"""§16 step 42 — notification test. Exercises the core notify()/list/
mark_read/unread_count mechanics directly, then confirms a representative
sample of the real triggers listed in notifications.py's module docstring
actually fire through their real call sites (not just that notify() itself
works in isolation) — credits.check_credit_threshold and
credits.check_pool_cap. The full trigger list is exercised end-to-end
elsewhere too (guardrail retry/escalation in test_guardrails.py, publish
retry/escalation in test_publish_failure.py, ticket messaging already
covered live in Phase 10) — this file focuses on the notification
mechanics and the two cost/pool triggers not covered by those.
"""

from app.lib import credits, notifications


def test_notify_insert_list_mark_read_unread_count(admin_client, temp_customer):
    notifications.notify(
        admin_client, recipient_type="customer", type_="approval_ready",
        message="Test notification", customer_id=temp_customer["id"],
    )
    unread = notifications.list_notifications(admin_client, recipient_type="customer", customer_id=temp_customer["id"], unread_only=True)
    assert len(unread) == 1
    assert notifications.unread_count(admin_client, recipient_type="customer", customer_id=temp_customer["id"]) == 1

    notifications.mark_read(admin_client, unread[0]["id"])
    assert notifications.unread_count(admin_client, recipient_type="customer", customer_id=temp_customer["id"]) == 0


def test_time_sensitive_types_get_email_status_pending_others_not_applicable(admin_client, temp_customer):
    time_sensitive = notifications.notify(
        admin_client, recipient_type="admin", type_="credit_threshold",
        message="Time-sensitive test", customer_id=temp_customer["id"],
    )
    fyi = notifications.notify(
        admin_client, recipient_type="admin", type_="generation_ready",
        message="FYI test", customer_id=temp_customer["id"],
    )
    # email_client.send_email is stubbed disabled (EMAIL_SENDING_DISABLED),
    # so a time-sensitive notification's dispatch attempt resolves to
    # "failed" (stub reports not-sent), not "sent" — the real signal here
    # is that dispatch was ATTEMPTED at all (not left "pending" forever),
    # which only happens for time-sensitive types.
    updated = admin_client.table("notifications").select("email_status").eq("id", time_sensitive["id"]).maybe_single().execute().data
    assert updated["email_status"] in ("sent", "failed"), "Time-sensitive notification's email dispatch was never attempted"
    assert fyi["email_status"] == "not_applicable"


def test_credit_threshold_trigger_fires_once_per_billing_period(admin_client, temp_customer):
    admin_client.table("customers").update({"credit_budget": 10}).eq("id", temp_customer["id"]).execute()
    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]

    for _ in range(3):
        gen = admin_client.table("generations").insert(
            {"customer_id": temp_customer["id"], "module_id": module_id, "template_id": "t", "prompt": "p", "media_url": "http://example.com/v.mp4"}
        ).execute().data[0]
        credits.log_credit_usage(admin_client, gen)  # template_id "t" is unmeasured -> FALLBACK_ESTIMATED_COST (50) each, well over the 10-credit budget

    fired = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "credit_threshold").execute().data
    assert len(fired) == 1, f"Expected exactly one credit_threshold notification (no spam across repeated crossings), got {len(fired)}"


def test_credit_threshold_does_not_fire_when_no_budget_configured(admin_client, temp_customer):
    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]
    gen = admin_client.table("generations").insert(
        {"customer_id": temp_customer["id"], "module_id": module_id, "template_id": "t", "prompt": "p", "media_url": "http://example.com/v.mp4"}
    ).execute().data[0]
    credits.log_credit_usage(admin_client, gen)

    fired = admin_client.table("notifications").select("*").eq("customer_id", temp_customer["id"]).eq("type", "credit_threshold").execute().data
    assert fired == [], "credit_threshold fired even though this customer has no credit_budget configured"


def test_pool_cap_trigger_fires_at_threshold_and_not_below(admin_client):
    pool = admin_client.table("blotato_account_pools").insert(
        {"plan_tier": "creator", "connected_account_count": 5, "cap": 10}
    ).execute().data[0]
    try:
        credits.check_pool_cap(admin_client, pool)  # 5/10 = 50%, below the 90% threshold
        fired_below = admin_client.table("notifications").select("*").eq("type", "pool_cap_approaching").ilike("message", f"%{pool['id']}%").execute().data
        assert fired_below == [], "pool_cap_approaching fired below threshold"

        admin_client.table("blotato_account_pools").update({"connected_account_count": 9}).eq("id", pool["id"]).execute()
        pool_at_threshold = admin_client.table("blotato_account_pools").select("*").eq("id", pool["id"]).maybe_single().execute().data
        credits.check_pool_cap(admin_client, pool_at_threshold)  # 9/10 = 90%, at threshold

        fired_at = admin_client.table("notifications").select("*").eq("type", "pool_cap_approaching").ilike("message", f"%{pool['id']}%").execute().data
        assert len(fired_at) == 1
    finally:
        admin_client.table("notifications").delete().eq("type", "pool_cap_approaching").ilike("message", f"%{pool['id']}%").execute()
        admin_client.table("blotato_account_pools").delete().eq("id", pool["id"]).execute()
