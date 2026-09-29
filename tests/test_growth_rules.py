"""§16 growth-rules build instructions (docs/social-growth-playbook.md,
docs/growth-rules-build-instructions.md), Groups A-D: prompt/generation
rules, hashtag enforcement, and the reweighted engagement score. Pure
functions — no real Blotato/Supabase calls needed.
"""

from app.lib import analytics, blotato_client, growth_rules

_VIDEO_TEMPLATE = {"id": "/base/v2/ai-story-video/5903fe43-514d-40ee-a060-0d6628c5f8fd/v1", "description": "AI Video with AI Voice"}
_IMAGE_TEMPLATE = {"id": "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0", "description": "Single Centered Text Quote"}


def test_growth_direction_applied_only_to_video_templates():
    prompt = "A quick tip about consistency."
    augmented = blotato_client.apply_growth_direction(prompt, _VIDEO_TEMPLATE)
    assert augmented.startswith(prompt)
    assert growth_rules.HOOK_AND_LOOP_VIDEO_DIRECTION in augmented
    assert "15 seconds" in augmented

    unchanged = blotato_client.apply_growth_direction(prompt, _IMAGE_TEMPLATE)
    assert unchanged == prompt


def test_growth_direction_not_duplicated_if_already_present():
    once = blotato_client.apply_growth_direction("A quick tip.", _VIDEO_TEMPLATE)
    twice = blotato_client.apply_growth_direction(once, _VIDEO_TEMPLATE)
    assert twice.count(growth_rules.HOOK_AND_LOOP_VIDEO_DIRECTION) == 1
    assert twice.count("only go longer if the content genuinely") == 1


def test_growth_direction_respects_custom_target_length():
    augmented = blotato_client.apply_growth_direction("A tip.", _VIDEO_TEMPLATE, target_seconds=25)
    assert "25 seconds" in augmented


def test_hashtag_limit_untouched_when_under_the_limit():
    caption = "Great tips today #realestate #tips"
    result, trimmed = growth_rules.enforce_hashtag_limit(caption, "instagram")
    assert result == caption
    assert trimmed is False


def test_hashtag_limit_trims_extras_on_tiktok_and_instagram():
    caption = "Great tips " + " ".join(f"#tag{i}" for i in range(8))
    result, trimmed = growth_rules.enforce_hashtag_limit(caption, "tiktok")
    assert trimmed is True
    assert len([w for w in result.split() if w.startswith("#")]) == 5


def test_hashtag_limit_is_stricter_on_x():
    caption = "Hot take #one #two #three #four"
    result, trimmed = growth_rules.enforce_hashtag_limit(caption, "x")
    assert trimmed is True
    assert len([w for w in result.split() if w.startswith("#")]) == 2


def test_hashtag_limit_defaults_to_permissive_when_platform_unknown():
    caption = " ".join(f"#tag{i}" for i in range(5))
    result, trimmed = growth_rules.enforce_hashtag_limit(caption, None)
    assert trimmed is False  # exactly 5 == DEFAULT_HASHTAG_LIMIT, the permissive TikTok/IG limit


def test_engagement_score_weights_shares_above_comments_above_likes():
    all_likes = {"likes": 10, "comments": 0, "shares": 0}
    all_shares = {"likes": 0, "comments": 0, "shares": 2}
    # 2 shares (2*5=10) should beat 10 likes (10*1=10)... equal at this
    # exact ratio, so use a case that's unambiguous in each direction:
    assert analytics.engagement_score({"likes": 0, "comments": 0, "shares": 3}) > analytics.engagement_score({"likes": 10, "comments": 0, "shares": 0})
    assert analytics.engagement_score({"likes": 0, "comments": 3, "shares": 0}) > analytics.engagement_score({"likes": 5, "comments": 0, "shares": 0})


def test_engagement_score_handles_missing_fields_as_zero():
    assert analytics.engagement_score({}) == 0
    assert analytics.engagement_score({"shares": None, "likes": None, "comments": None}) == 0
