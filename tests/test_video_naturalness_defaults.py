"""§16 video-naturalness finding, UPDATED 2026-08-27 — the original
2026-08-24 finding (preferring a b-roll-inclusive template) was retracted:
that template requires a real `avatarVideoUrl` this app never supplied,
and Blotato was silently substituting a fixed fallback clip every time —
confirmed by direct user report that every generated video showed the
same person regardless of prompt. See docs/phase13-validation-notes.md's
2026-08-27 retraction entry for the full story.

`preferred_video_template` is neutral again (no template preferred) until
a real replacement is tested with its actual required inputs. What's
still tested here: template classification, the neutral fallback
behavior, and the natural-pacing prompt direction — which is unaffected
by the avatar bug (confirmed on "AI Video with AI Voice", a template with
no avatar-footage requirement) and is still applied, just no longer
claimed sufficient on its own. Pure functions, no real Blotato calls
needed.
"""

from app.lib import blotato_client, design

_IMAGE_TEMPLATE = {"id": "9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0", "description": "Single Centered Text Quote"}
_AVATAR_TEMPLATE = {"id": "/base/v2/ai-story-video/5903fe43-514d-40ee-a060-0d6628c5f8fd/v1", "description": "AI Video with AI Voice"}
_BROLL_TEMPLATE = {"id": "/base/v2/ai-avatar-broll/7c26a1cd-d5b3-42da-9c73-2413333873b3/v1", "description": "AI Avatar with AI Generated B-roll"}
_SELFIE_TEMPLATE = {"id": "/base/v2/ai-selfie-video/57f5a565-fd17-458b-be43-4a2d8ccaca75/v1", "description": "AI Selfie Talking Video with Consistent Character"}


def test_is_video_template_classifies_correctly():
    assert blotato_client.is_video_template(_IMAGE_TEMPLATE) is False
    assert blotato_client.is_video_template(_AVATAR_TEMPLATE) is True
    assert blotato_client.is_video_template(_BROLL_TEMPLATE) is True


def test_preferred_video_template_is_neutral_picks_first_video_template_in_list_order():
    # Retracted (2026-08-27): this used to assert the b-roll template won
    # regardless of order. No template is preferred anymore — whichever
    # video template appears first in the input list wins, full stop.
    templates = [_IMAGE_TEMPLATE, _AVATAR_TEMPLATE, _SELFIE_TEMPLATE, _BROLL_TEMPLATE]
    preferred = blotato_client.preferred_video_template(templates)
    assert preferred == _AVATAR_TEMPLATE

    reordered = [_IMAGE_TEMPLATE, _BROLL_TEMPLATE, _AVATAR_TEMPLATE, _SELFIE_TEMPLATE]
    assert blotato_client.preferred_video_template(reordered) == _BROLL_TEMPLATE


def test_preferred_video_template_returns_none_with_no_video_templates_at_all():
    assert blotato_client.preferred_video_template([_IMAGE_TEMPLATE]) is None


def test_natural_pacing_direction_applied_only_to_video_templates():
    plain_prompt = "A short video of a small business owner opening their shop."
    augmented = blotato_client.apply_natural_pacing_direction(plain_prompt, _AVATAR_TEMPLATE)
    assert augmented.startswith(plain_prompt)
    assert blotato_client.NATURAL_PACING_VIDEO_DIRECTION in augmented

    unchanged = blotato_client.apply_natural_pacing_direction(plain_prompt, _IMAGE_TEMPLATE)
    assert unchanged == plain_prompt


def test_natural_pacing_direction_not_duplicated_if_already_present():
    already_has_it = f"A short video. {blotato_client.NATURAL_PACING_VIDEO_DIRECTION}"
    result = blotato_client.apply_natural_pacing_direction(already_has_it, _AVATAR_TEMPLATE)
    assert result.count(blotato_client.NATURAL_PACING_VIDEO_DIRECTION) == 1


def test_design_categorize_templates_still_matches_shared_classifier():
    templates = [_IMAGE_TEMPLATE, _AVATAR_TEMPLATE, _BROLL_TEMPLATE]
    images, videos = design.categorize_templates(templates)
    assert images == [_IMAGE_TEMPLATE]
    assert videos == [_AVATAR_TEMPLATE, _BROLL_TEMPLATE]


def test_build_selfie_character_inputs_uses_default_when_none_given():
    inputs = blotato_client.build_selfie_character_inputs("A quick tip about consistency.")
    assert inputs["characterDescription"] == blotato_client.DEFAULT_SELFIE_CHARACTER_DESCRIPTION
    assert inputs["scenes"] == [{"description": "A quick tip about consistency.", "narration": "A quick tip about consistency."}]
    assert inputs["style"] == "realistic"


def test_build_selfie_character_inputs_uses_explicit_override():
    inputs = blotato_client.build_selfie_character_inputs(
        "A quick tip about consistency.", character_description="A tall man with a beard, wearing glasses."
    )
    assert inputs["characterDescription"] == "A tall man with a beard, wearing glasses."


def test_create_from_template_auto_builds_selfie_inputs_when_none_supplied():
    from unittest.mock import patch

    with patch("app.lib.blotato_client.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"item": {"id": "fake", "status": "queueing"}}
        mock_post.return_value.raise_for_status.return_value = None
        blotato_client.create_from_template(blotato_client.SELFIE_CHARACTER_TEMPLATE_ID, "A quick tip.")

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["inputs"]["characterDescription"] == blotato_client.DEFAULT_SELFIE_CHARACTER_DESCRIPTION
    assert sent_payload["inputs"]["scenes"] == [{"description": "A quick tip.", "narration": "A quick tip."}]


def test_create_from_template_blanks_the_watemark_default_placeholder():
    """§16 growth-rules Group E2 investigation (2026-09-11): confirmed via
    Blotato's own docs that this template's real `watemark` (their typo)
    parameter defaults to the literal placeholder text "Watemark" shown
    on screen if never set — always blank it unless the caller wants
    different on-screen text."""
    from unittest.mock import patch

    with patch("app.lib.blotato_client.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"item": {"id": "fake", "status": "queueing"}}
        mock_post.return_value.raise_for_status.return_value = None
        blotato_client.create_from_template(blotato_client.MINIMAL_STYLE_TEMPLATE_ID, "A quick tip.")

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["inputs"]["watemark"] == ""


def test_create_from_template_respects_an_explicit_watemark_value():
    from unittest.mock import patch

    with patch("app.lib.blotato_client.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"item": {"id": "fake", "status": "queueing"}}
        mock_post.return_value.raise_for_status.return_value = None
        blotato_client.create_from_template(
            blotato_client.MINIMAL_STYLE_TEMPLATE_ID, "A quick tip.", inputs={"watemark": "@ourhandle"}
        )

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["inputs"]["watemark"] == "@ourhandle"


def test_create_from_template_respects_explicit_inputs_for_selfie_template():
    from unittest.mock import patch

    explicit_inputs = blotato_client.build_selfie_character_inputs("A quick tip.", "A specific custom character.")
    with patch("app.lib.blotato_client.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"item": {"id": "fake", "status": "queueing"}}
        mock_post.return_value.raise_for_status.return_value = None
        blotato_client.create_from_template(blotato_client.SELFIE_CHARACTER_TEMPLATE_ID, "A quick tip.", inputs=explicit_inputs)

    sent_payload = mock_post.call_args.kwargs["json"]
    assert sent_payload["inputs"]["characterDescription"] == "A specific custom character."


# ---------------------------------------------------------------------------
# §16 growth-rules Group E1, blocked 2026-09-17: "Combine Clips and Apply
# Basic Edits" has a real, unvetted music-URL passthrough (musicConfig.url)
# — Blotato doesn't host, vet, or license the track, and TikTok business
# accounts may only use Commercial-Music-Library-cleared or original audio.
# A real account-safety risk (a customer's real connected account could be
# muted/removed), blocked at the source until licensed-audio handling is
# deliberately built for it — see BLOCKED_TEMPLATE_IDS's docstring and
# docs/growth-rules-build-instructions.md's "growth features still to build".
# ---------------------------------------------------------------------------

_BLOCKED_COMBINE_CLIPS_ID = "/base/v2/combine-clips/c306ae43-1dcc-4f45-ac2b-88e75430ffd8/v1"


def test_blocked_template_is_filtered_out_of_the_real_live_template_list():
    """Real call — confirms the block actually reaches Blotato's current
    real template list, not just a hardcoded id string that might be
    stale or already renamed on their side."""
    templates = blotato_client.list_templates()
    assert all(t["id"] not in blotato_client.BLOCKED_TEMPLATE_IDS for t in templates)
    assert _BLOCKED_COMBINE_CLIPS_ID in blotato_client.BLOCKED_TEMPLATE_IDS, (
        "The id this test/BLOCKED_TEMPLATE_IDS assumes may be stale — re-check against "
        "list_templates() if this assertion ever fails"
    )


def test_create_from_template_refuses_the_blocked_template_even_if_called_directly():
    """Defense-in-depth: even if a caller bypasses list_templates() (e.g. a
    stale cached template list fetched before this block existed), the
    real account-safety risk is still refused here, not just filtered
    from the picker."""
    import pytest

    with pytest.raises(ValueError, match="blocked"):
        blotato_client.create_from_template(_BLOCKED_COMBINE_CLIPS_ID, "A quick tip.")
