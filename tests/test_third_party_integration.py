"""§16 step 36 — integration tests for every third-party call. Rather than
duplicate coverage, this file only covers the Blotato/Anthropic calls not
already exercised for real elsewhere in this suite:

  - blotato_client.list_templates()        -> here
  - blotato_client.list_accounts()         -> test_blotato_pool.py
  - blotato_client.create_from_template()  -> test_cross_module.py, test_guardrails.py (real retry)
  - blotato_client.get_creation()          -> test_cross_module.py
  - blotato_client.create_post()           -> NEVER called live by this suite (standing rule) — mocked in test_publish_failure.py
  - blotato_client.get_post()              -> same — mocked in test_publish_failure.py, test_cross_module.py
  - blotato_client.list_posts()            -> here (real, read-only, no side effects)
  - blotato_client.search_published_posts()-> here, against the real published TikTok post (Phase 6)
  - blotato_client.get_post_analytics()    -> here
  - blotato_client.get_top_analytics()     -> here
  - anthropic guardrail calls              -> test_guardrails.py (extensively)

The real published post used below (Dev Test customer, blotato_account_id
51990, https://www.tiktok.com/@stackdifferrent/video/7667329117125217550)
is the same one from Phase 6/7's live testing — reused here rather than
creating a new real post, since this suite never publishes.
"""

from app.lib import blotato_client


def test_list_templates_returns_real_templates():
    templates = blotato_client.list_templates()
    assert isinstance(templates, list)
    assert len(templates) > 0
    assert all("id" in t and "description" in t for t in templates)


def test_list_accounts_returns_real_connected_accounts():
    accounts = blotato_client.list_accounts()
    assert isinstance(accounts, list)


def test_list_posts_recent_window():
    """CONFIRMED (per blotato_client.py's docstring) this only returns the
    last ~hour — just confirming the call itself succeeds and returns the
    documented shape, not that it contains anything specific."""
    result = blotato_client.list_posts(limit=10)
    assert "items" in result or isinstance(result, dict)


def test_search_published_posts_finds_the_real_phase6_post(admin_client):
    """A real, bounded linear scan (mirroring app/lib/analytics.py's own
    resolve_numeric_post_id) confirming the real TikTok post from Phase 6
    is still findable via the search endpoint."""
    found = None
    for offset in range(0, 500, 100):
        page = blotato_client.search_published_posts(limit=100, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        match = next((item for item in items if "7667329117125217550" in (item.get("postUrl") or item.get("url") or "")), None)
        if match:
            found = match
            break
    assert found is not None, "Could not find the real Phase 6 TikTok post via search_published_posts within a 5-page scan"


def test_get_top_analytics_real_call_succeeds():
    top = blotato_client.get_top_analytics(limit=20)
    assert isinstance(top, list)


def test_get_post_analytics_handles_not_yet_synced_gracefully():
    """A 404 from this endpoint means 'not synced yet', not a real error
    (per blotato_client.py's docstring) — confirms calling it on a
    numeric post id that may or may not have synced analytics doesn't
    raise anything OTHER than the documented not-yet-synced case."""
    import requests

    try:
        result = blotato_client.get_post_analytics("1")  # deliberately unlikely to be a real numeric post id
        assert isinstance(result, dict)
    except requests.HTTPError as exc:
        assert exc.response.status_code == 404, f"Expected a 404 (not-yet-synced) for an unknown post id, got {exc.response.status_code}"
