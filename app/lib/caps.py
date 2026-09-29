"""Default per-module caps (§7), written into customer_modules.caps at
onboarding time. Admin can override per customer later — these are just the
starting point."""

DEFAULT_CAPS = {
    "social": {
        "platforms_per_customer": 3,
        "posts_per_day": 3,
        "media_uploads_images": 20,
        "media_uploads_videos": 5,
        "chat_edit_regenerations_per_generation": 5,
    },
    "video_design_graphic_creator": {
        "design_deliverables_per_week": 3,
        "standalone_videos_per_week": 1,
        "chat_edit_regenerations_per_generation": 5,
    },
}

DEFAULT_WARM_UP_PERIOD_DAYS = 21
"""Starting default only — the real value lives on each social_accounts row
(warm_up_period_days) and is editable per account in Account Connections."""

GUARDRAIL_MAX_RETRIES = 2
"""§9: guardrail (and publish) failures auto-retry before escalating to
admin, rather than failing silently. Not specified in the build packet —
a reasonable starting point, easy to change once there's real data on how
often retries actually resolve a flag."""
