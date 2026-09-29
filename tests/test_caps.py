"""§16 step 39 — cap/limit tests across both modules. Confirmed via §5's
review: caps are soft (flag but allow) by design, not a hard block —
these tests check the flag/count math is right, not that anything gets
blocked, since nothing is meant to.

UPDATE (post-Phase-12 follow-up): platforms_per_customer and both
media_uploads caps were found unchecked when this file was first written,
and have since been wired up (see test_platforms_per_customer_cap_flags_
without_blocking and test_media_uploads_cap_counts_ready_generations_by_
type below) — soft, matching every other cap. chat_edit_regenerations_per_
generation is intentionally NOT wired: there is no chat-based editing
feature built anywhere in the app at all (no regenerate/edit action
exists), so generations.edit_count never moves off its default of 0 —
that's a missing feature, not a missing check, and out of scope here.
"""

from datetime import datetime, timedelta, timezone

from app.lib import design, onboarding
from app.lib.caps import DEFAULT_CAPS
from app.views.admin_panel import _media_uploads_this_month, _posts_published_today


def test_default_caps_cover_both_modules():
    assert "social" in DEFAULT_CAPS
    assert "video_design_graphic_creator" in DEFAULT_CAPS
    assert DEFAULT_CAPS["social"]["posts_per_day"] == 3
    assert DEFAULT_CAPS["video_design_graphic_creator"]["design_deliverables_per_week"] == 3
    assert DEFAULT_CAPS["video_design_graphic_creator"]["standalone_videos_per_week"] == 1


def test_social_posts_per_day_counts_only_published_today(admin_client, temp_customer):
    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]
    now = datetime.now(timezone.utc)

    def make_generation(published: bool, when: datetime) -> dict:
        row = admin_client.table("generations").insert(
            {"customer_id": temp_customer["id"], "module_id": module_id, "template_id": "t", "prompt": "p"}
        ).execute().data[0]
        update = {"publish_status": "published" if published else "not_published"}
        if published:
            update["approved_at"] = when.isoformat()
        admin_client.table("generations").update(update).eq("id", row["id"]).execute()
        return row

    make_generation(published=True, when=now)  # counts
    make_generation(published=True, when=now - timedelta(days=2))  # too old, doesn't count
    make_generation(published=False, when=now)  # not published, doesn't count

    count = _posts_published_today(admin_client, temp_customer["id"])
    assert count == 1, f"Expected exactly 1 post published today to count against the cap, got {count}"


def test_design_cap_usage_flags_without_blocking(admin_client, temp_customer):
    caps = DEFAULT_CAPS["video_design_graphic_creator"]

    for i in range(caps["design_deliverables_per_week"] + 2):
        gen = admin_client.table("generations").insert(
            {"customer_id": temp_customer["id"], "module_id": _social_module_id(admin_client), "template_id": "t", "prompt": "p"}
        ).execute().data[0]
        admin_client.table("design_deliverables").insert(
            {"generation_id": gen["id"], "customer_id": temp_customer["id"], "type": "flyer", "occasion": "test"}
        ).execute()

    usage = design.check_cap_usage(admin_client, temp_customer["id"], "flyer", caps)
    assert usage["used"] == caps["design_deliverables_per_week"] + 2
    assert usage["limit"] == caps["design_deliverables_per_week"]
    assert usage["within_cap"] is False, "Cap usage should flag as over, even though nothing actually blocks the request"


def test_design_cap_usage_separates_video_from_flyer_ad(admin_client, temp_customer):
    """standalone_videos_per_week and design_deliverables_per_week are
    tracked independently — a customer maxed out on flyers should still
    show as within-cap on videos."""
    caps = DEFAULT_CAPS["video_design_graphic_creator"]
    for _ in range(caps["design_deliverables_per_week"] + 1):
        gen = admin_client.table("generations").insert(
            {"customer_id": temp_customer["id"], "module_id": _social_module_id(admin_client), "template_id": "t", "prompt": "p"}
        ).execute().data[0]
        admin_client.table("design_deliverables").insert(
            {"generation_id": gen["id"], "customer_id": temp_customer["id"], "type": "ad", "occasion": "test"}
        ).execute()

    flyer_usage = design.check_cap_usage(admin_client, temp_customer["id"], "flyer", caps)
    video_usage = design.check_cap_usage(admin_client, temp_customer["id"], "video", caps)
    assert flyer_usage["within_cap"] is False
    assert video_usage["used"] == 0
    assert video_usage["within_cap"] is True


def _social_module_id(admin_client) -> str:
    return admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]


def test_media_uploads_cap_counts_ready_generations_by_type(admin_client, temp_customer):
    module_id = _social_module_id(admin_client)

    def make(status: str, media_url: str | None) -> None:
        admin_client.table("generations").insert(
            {"customer_id": temp_customer["id"], "module_id": module_id, "template_id": "t", "prompt": "p", "status": status, "media_url": media_url}
        ).execute()

    make("ready", None)  # image
    make("ready", None)  # image
    make("ready", "http://example.com/v.mp4")  # video
    make("processing", None)  # not ready yet — must not count
    make("failed", "http://example.com/v.mp4")  # failed — must not count

    assert _media_uploads_this_month(admin_client, temp_customer["id"], "image") == 2
    assert _media_uploads_this_month(admin_client, temp_customer["id"], "video") == 1


def test_platforms_per_customer_cap_flags_without_blocking(admin_client):
    """Onboarding is idempotent/resumable by design — calling
    provision_customer twice for the same customer (adding more platforms
    the second time) is exactly the real Resume Onboarding path, not a
    test-only trick. Lowers the cap between calls since the real
    3-platform default can never be exceeded (only tiktok/instagram/x
    exist to request). provision_customer creates its own customer row
    (not the temp_customer fixture's), so this test cleans up everything
    it creates directly rather than relying on that fixture."""
    import uuid

    from tests.conftest import delete_auth_user, make_auth_user

    email = f"phase12-platforms-cap-{uuid.uuid4().hex[:8]}@example.com"
    customer_id = None
    try:
        # Pre-create the auth user so onboarding._ensure_invited_user's
        # invite_user_by_email() call hits the "already registered"
        # idempotent fallback (a lookup) instead of actually attempting to
        # send a real invite email — invite_user_by_email goes through
        # Supabase's real email pipeline and its rate limit, unlike
        # admin.create_user (what make_auth_user uses), which sends nothing.
        make_auth_user(email)
        payload = {
            "email": email,
            "business_name": f"Phase12 Platforms Cap Test {uuid.uuid4().hex[:8]}",
            "niche": "General",
            "selected_module_keys": ["social"],
            "platform_sources": {"tiktok": "existing"},
        }
        result = onboarding.provision_customer(admin_client, admin_client, payload)
        assert result["errors"] == [], f"First onboarding pass should succeed cleanly: {result['errors']}"
        customer_id = result["customer_id"]
        assert customer_id is not None

        social_module_id = _social_module_id(admin_client)
        admin_client.table("customer_modules").update({"caps": {"platforms_per_customer": 1}}).eq(
            "customer_id", customer_id
        ).eq("module_id", social_module_id).execute()

        intake = admin_client.table("onboarding_intakes").select("id").eq("email", email).maybe_single().execute().data
        intake_shape = {"id": intake["id"], "customer_id": customer_id, "email": email, "payload": payload}

        payload2 = dict(payload)
        payload2["platform_sources"] = {"instagram": "existing", "x": "existing"}
        result2 = onboarding.provision_customer(admin_client, admin_client, payload2, intake=intake_shape)

        assert result2["errors"] == [], f"Exceeding a soft cap should not produce an error: {result2['errors']}"
        assert any("over the 1-platform cap" in step for step in result2["steps_completed"]), (
            f"Expected an over-cap note in steps_completed, got: {result2['steps_completed']}"
        )

        accounts = admin_client.table("social_accounts").select("platform").eq("customer_id", customer_id).execute().data
        assert len(accounts) == 3, "All 3 platforms should still have been queued despite exceeding the cap (soft, not blocking)"
    finally:
        delete_auth_user(email)
        admin_client.table("onboarding_intakes").delete().eq("email", email).execute()
        if customer_id:
            admin_client.table("customers").delete().eq("id", customer_id).execute()
