"""§16 step 44 — Blotato pool test. Covers the pool-cap notification logic
(credits.check_pool_cap — the read-side "approaching cap" warning, also
exercised in test_notifications.py) plus a real, safe call against
Blotato's actual account-listing endpoint to confirm the pool's
connected_account_count is at least plausible against reality (a genuine
cross-check, not just internal bookkeeping)."""

from app.lib import blotato_client


def test_real_blotato_account_pool_matches_live_connected_accounts(admin_client):
    """Cross-checks the one real blotato_account_pools row's
    connected_account_count against Blotato's own live account list — a
    real GET call, no side effects. If these drift far apart the pool
    bookkeeping (incremented in admin_panel._mark_connected) isn't being
    kept honest against reality."""
    pools = admin_client.table("blotato_account_pools").select("*").execute().data
    assert len(pools) >= 1, "No blotato_account_pools row exists — §5's pool seed migration should have created one"

    live_accounts = blotato_client.list_accounts()
    assert isinstance(live_accounts, list)

    total_tracked = sum(p["connected_account_count"] for p in pools)
    # Not asserting exact equality — pool bookkeeping only increments when
    # an admin marks an account connected through this app; a Blotato
    # account connected directly in Blotato's own dashboard, outside this
    # app, would never be reflected here. Only flag if tracked count
    # exceeds what's actually live, which would mean bookkeeping drifted
    # ahead of reality (a real bug), not behind it (an expected gap).
    assert total_tracked <= len(live_accounts) + 5, (
        f"Tracked connected_account_count ({total_tracked}) is implausibly higher than Blotato's live "
        f"account list ({len(live_accounts)}) — pool bookkeeping may be double-counting."
    )


def test_pool_cap_not_reset_by_repeated_checks(admin_client):
    """check_pool_cap's de-dupe (don't re-notify while an unread warning
    for this pool is still open) shouldn't itself increment or reset
    anything on the pool row — confirms it's a pure read-and-maybe-notify,
    no side effects on blotato_account_pools."""
    from app.lib import credits

    pool = admin_client.table("blotato_account_pools").insert(
        {"plan_tier": "creator", "connected_account_count": 95, "cap": 100}
    ).execute().data[0]
    try:
        credits.check_pool_cap(admin_client, pool)
        credits.check_pool_cap(admin_client, pool)
        credits.check_pool_cap(admin_client, pool)

        unchanged = admin_client.table("blotato_account_pools").select("connected_account_count, cap").eq("id", pool["id"]).maybe_single().execute().data
        assert unchanged == {"connected_account_count": 95, "cap": 100}

        fired = admin_client.table("notifications").select("id").eq("type", "pool_cap_approaching").ilike("message", f"%{pool['id']}%").execute().data
        assert len(fired) == 1, "check_pool_cap should not re-notify on repeated calls while the warning is still unread"
    finally:
        admin_client.table("notifications").delete().eq("type", "pool_cap_approaching").ilike("message", f"%{pool['id']}%").execute()
        admin_client.table("blotato_account_pools").delete().eq("id", pool["id"]).execute()
