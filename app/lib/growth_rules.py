"""Growth Rules knowledge base — §16 growth-rules build instructions
(docs/social-growth-playbook.md, docs/growth-rules-build-instructions.md).

Single source of truth for the UNIVERSAL, platform-level facts distilled
from the 2026 growth research — referenced by video prompt direction
(blotato_client.apply_growth_direction), caption/hashtag enforcement
(enforce_hashtag_limit), the niche playbook display (admin_panel), and
posting-time guidance (Generate (Social), Calendar).

Deliberately kept in CODE, not duplicated into every niche_playbooks row:
these facts (hook formula, platform format-by-goal, hashtag limits,
posting-time windows, growth timeline) are the same regardless of niche —
duplicating them per-row would just be N copies of the same text that can
drift out of sync. What's genuinely niche-specific already has a home
(niche_playbooks.content_pillars / example_angles / best_practices).

HONESTY NOTE (Group D): the research's #1 and #2 success signals —
completion rate/watch time and saves — are NOT available anywhere in this
product. Confirmed against Blotato's real API responses (see
blotato_client.get_top_analytics/get_post_analytics — they return only
views/likes/comments/shares, never watch time or saves), and
analytics_snapshots.watch_time has never been populated by any real data
source. engagement_score() below is reweighted to favor shares (the
research's #3 signal, and the strongest one we actually have) over
comments and likes — it is NOT claiming to measure retention, because we
can't.
"""

import re

# ---------------------------------------------------------------------------
# A1/A3 — hook + loop direction, appended to video generation prompts.
# See blotato_client.apply_growth_direction, which applies this alongside
# the existing NATURAL_PACING_VIDEO_DIRECTION.
# ---------------------------------------------------------------------------

HOOK_AND_LOOP_VIDEO_DIRECTION = (
    "Open with the payoff, the surprising visual, the bold claim, or the specific question the viewer "
    "needs answered — in the first 1-3 seconds. Never a slow intro, a greeting, a logo, or setup before "
    "the payoff; state the value in the very first frame, explain after. Where it fits naturally, end on "
    "a line or frame that ties back to the opening, to invite a rewatch."
)
"""2026 research (Part 2.5): ~71% of viewers decide whether to keep
watching within the first 3 seconds; a failed hook means nothing else in
the video matters, since most viewers never see it."""

DEFAULT_VIDEO_LENGTH_SECONDS = 15
"""A2: default short-form video to ~10-20s unless the content genuinely
needs longer — a default admin/customer can override via the prompt
itself, never a hard cap."""


# ---------------------------------------------------------------------------
# A5 — hashtag limits, hard-enforced (not just prompt guidance).
# ---------------------------------------------------------------------------

HASHTAG_LIMITS = {"tiktok": 5, "instagram": 5, "x": 2}
DEFAULT_HASHTAG_LIMIT = 5
"""Used when the target platform isn't known yet at generation time (see
admin_panel._render_generate_social — a target account is optional at
this stage). Defaults to the more permissive TikTok/Instagram limit
rather than X's stricter one, since under-trimming is the safer direction
when the platform is still unknown; the stricter X limit is applied for
real once a target account IS selected."""

_HASHTAG_PATTERN = re.compile(r"#\w+")


def enforce_hashtag_limit(caption: str, platform: str | None = None) -> tuple[str, bool]:
    """Returns (caption, was_trimmed). Keeps the first N hashtags in their
    original position and removes the rest — real enforcement, per A5's
    explicit "enforce in generation logic, not just prompt guidance.\""""
    limit = HASHTAG_LIMITS.get(platform, DEFAULT_HASHTAG_LIMIT)
    matches = list(_HASHTAG_PATTERN.finditer(caption))
    if len(matches) <= limit:
        return caption, False
    trimmed = caption
    for match in reversed(matches[limit:]):
        trimmed = trimmed[: match.start()].rstrip() + trimmed[match.end() :]
    return trimmed, True


# ---------------------------------------------------------------------------
# B1/B2 — universal principles + platform format-by-goal guidance, shown
# in the Playbooks screen (universal, above the niche-specific editor) and
# near the Generate (Social) caption field.
# ---------------------------------------------------------------------------

UNIVERSAL_PRINCIPLES = (
    "Retention/watch-time and shares beat likes on every platform — design for people to watch to the "
    "end and want to send this to someone, not just tap like. Authentic, real-feeling content "
    "consistently outperforms polished/corporate-feeling content in 2026. Follower count is not a "
    "direct ranking factor on TikTok/Instagram Reels — a new account with a great post can outreach a "
    "huge one."
)

GROWTH_TIMELINE_EXPECTATION = (
    "Realistic timeline to set with customers: 3-6 months for visible traction, 6-12 months for "
    "consistent inquiries/sales, with consistent posting. This is a compounding investment, not an "
    "overnight result — nobody goes viral in week one."
)

PLATFORM_FORMAT_GUIDANCE = {
    "tiktok": "Short vertical video, hook in frame one — a native feel, not a repost from elsewhere.",
    "instagram": (
        "Reels for reach with new audiences; carousels for saves/education with an existing audience; "
        "Stories for driving link clicks. Pick the format by goal, not one default for everything."
    ),
    "x": (
        "Text-first: a conversation-starting take, question, or data point — video is optional here, "
        "not mandatory the way it is on TikTok/Instagram. Any link goes in a reply, never the main post."
    ),
}


# ---------------------------------------------------------------------------
# C1 — posting-time defaults. ADVISORY ONLY: this product publishes
# immediately on customer approval (approval.py — there is no "schedule
# for later" feature anywhere in this codebase), so these are surfaced as
# guidance for WHEN to generate/approve, not an automatic scheduler.
# Building real scheduling would be a genuinely new feature, not a rule
# baked into the existing generator — flagged, not silently assumed.
# ---------------------------------------------------------------------------

POSTING_TIME_GUIDANCE = {
    "tiktok": "Tue-Thu 2-6 PM local tends to perform best (test Saturday too) — aim to approve/publish 1-2 hours before this account's real peak activity.",
    "instagram": "Tue-Thu 9 AM-12 PM local tends to perform best; Wednesday is often the single strongest day.",
    "x": "Tue-Thu mornings tend to perform best, but X's early-velocity dependence means posting when this account's specific audience is actually online matters more than a fixed slot.",
}


# ---------------------------------------------------------------------------
# A6 — X's text-first path. A real generation.py sentinel template_id (see
# generation.start_text_only_generation): this is never sent to Blotato,
# there's no media job at all for it, so it costs 0 real credits — see
# credits.cost_for_template's special case for this exact id.
# ---------------------------------------------------------------------------
TEXT_ONLY_TEMPLATE_ID = "text-only-x-post"
