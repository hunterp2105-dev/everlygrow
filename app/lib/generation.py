"""Generic async generation job handling (§9), for the Social module.

Deliberately ONE start function and ONE poller, used for every template
type (image, slideshow, video, video-with-voiceover) — Blotato's own API
already unifies these into identical job shapes, so duplicating this logic
per content type would just be tracking the same state machine multiple
times for no reason.
"""

from datetime import datetime, timedelta, timezone

from app.lib import blotato_client, credits, growth_rules, guardrails, notifications

_TERMINAL_STATUSES = {"ready", "failed"}

_BLOTATO_TO_INTERNAL = {
    "done": "ready",
    "failed": "failed",
    "creation-from-template-failed": "failed",
    "insufficient-credits": "failed",
}
"""§16 video-naturalness follow-up (2026-09-03): "insufficient-credits" is
a real, documented Blotato terminal status (see blotato_client.py's
create_from_template docstring — it showed up once before, during the
voice-generation investigation) but was missing from this mapping
entirely. Anything not in this dict falls through to "processing" via
_normalize_status's default — so two real generations sat as "processing"
in the DB for the full poll window (and would have eventually been
mislabeled as a generic stuck-job timeout failure) when the actual,
immediately-knowable reason was simply that the account ran out of
credits mid-run. Now a real terminal failure, with the reason surfaced
directly in the admin notification (see _notify_terminal) instead of a
bare "failed"."""

GENERATION_STALE_TIMEOUT_MINUTES = 30
"""§16 step 38 ("video timeout") surfaced a real gap: nothing ever marked a
generation failed if Blotato's job simply never reached a terminal status —
poll_generation would no-op on it forever. §16 step 50 (timing validation)
then found the packet's premise wrong too: real video timing ranged from
under 1 minute to just over 6 minutes across this build's own testing —
nowhere near a fixed "~10 minutes" (§4, corrected). 30 minutes still gives
a wide margin over the real observed range before treating a job as
orphaned rather than slow. This is the one place staleness is checked (not
a background scheduler — this app has none) because it's the one place a
generation's live status is re-checked at all."""

GENERATION_SLOW_WARNING_MINUTES = 6
"""§16 step 50 follow-up: with real video timing this variable and the
existing failure timeout 5x higher, admin had no signal between "still
normal" and "probably stuck" for a job running long. Fires the
`generation_slow` notification exactly once per generation (tracked via
generations.slow_notification_sent_at) — not a failure, not retried,
just a heads-up that this one is taking longer than most."""


def _normalize_status(blotato_status: str) -> str:
    return _BLOTATO_TO_INTERNAL.get(blotato_status, "processing")


def start_generation(
    client,
    customer_id: str,
    module_id: str,
    template_id: str,
    template_description: str,
    prompt: str,
    voice_name: str | None = None,
    target_social_account_id: str | None = None,
    post_caption: str | None = None,
    inputs: dict | None = None,
) -> dict:
    """target_social_account_id/post_caption: Social-only, set at request
    time so everything needed to publish already exists on the row by the
    time a customer approves it (Phase 6, app/lib/approval.py). `inputs`:
    optional template-specific structured inputs (e.g. a character
    description for the Selfie/Consistent-Character template — see
    blotato_client.build_selfie_character_inputs); most templates don't
    need this and blotato_client.create_from_template has its own
    template-aware default when it's omitted."""
    # Real per-template cost is learned in production (see module
    # docstring / credits.py) — snapshot the real Blotato balance now,
    # before the job starts, ONLY if this template has never been
    # measured. poll_generation diffs this against the post-completion
    # balance once the job actually finishes.
    credit_balance_before_start = credits.snapshot_balance_if_unmeasured(client, template_id)

    creation = blotato_client.create_from_template(template_id, prompt, inputs=inputs, voice_name=voice_name)

    inserted = (
        client.table("generations")
        .insert(
            {
                "customer_id": customer_id,
                "module_id": module_id,
                "template_id": template_id,
                "template_description": template_description,
                "prompt": prompt,
                "voice_name": voice_name,
                "target_social_account_id": target_social_account_id,
                "post_caption": post_caption,
                "blotato_creation_id": creation["id"],
                "blotato_status": creation.get("status", "queueing"),
                "status": _normalize_status(creation.get("status", "queueing")),
                "credit_balance_before_start": credit_balance_before_start,
            }
        )
        .execute()
    )
    return inserted.data[0]


def start_text_only_generation(
    client,
    customer_id: str,
    module_id: str,
    post_caption: str,
    target_social_account_id: str | None = None,
) -> dict:
    """§16 growth-rules Group A6: 2026 research shows text-only posts
    reportedly outperform video by ~30% on X, and video there is
    optional, not mandatory the way it is on TikTok/Instagram (see
    growth_rules.py). The only path in this engine with no Blotato media
    job at all — the row is created already 'ready' (nothing async to
    poll) and goes through the same ready-transition handling as any
    other generation reaching 'ready' (see _handle_ready_transition), so
    guardrails/credit-logging/notifications/approval all work identically
    either way, and this never has to duplicate that logic."""
    inserted = (
        client.table("generations")
        .insert(
            {
                "customer_id": customer_id,
                "module_id": module_id,
                "template_id": growth_rules.TEXT_ONLY_TEMPLATE_ID,
                "template_description": "Text-only post (X)",
                "prompt": post_caption,
                "post_caption": post_caption,
                "target_social_account_id": target_social_account_id,
                "blotato_status": "text-only",
                "status": "ready",
            }
        )
        .execute()
        .data[0]
    )
    _notify_terminal(client, inserted)
    return _handle_ready_transition(client, inserted)


def _handle_ready_transition(client, result: dict) -> dict:
    """Everything that happens the instant a generation becomes 'ready' —
    cost learning, credit logging, guardrails — identically whether it
    got there via a real Blotato job finishing (poll_generation) or a
    text-only post that was never a Blotato job to begin with
    (start_text_only_generation). A flag/fail from guardrails may retry
    (resets status back to 'processing') or escalate, so re-fetch to
    return the row's true current state."""
    _maybe_learn_template_cost(client, result)
    credits.log_credit_usage(client, result)
    guardrails.review_ready_generation(client, result)
    return client.table("generations").select("*").eq("id", result["id"]).maybe_single().execute().data


def poll_generation(client, generation: dict) -> dict:
    """Checks one generation's real Blotato status and updates the row.
    No-ops if already terminal. Fires an admin notification exactly once,
    on the transition into a terminal state — identically for every content
    type, per §9's failure/ready notification triggers."""
    if generation["status"] in _TERMINAL_STATUSES:
        return generation

    creation = blotato_client.get_creation(generation["blotato_creation_id"])
    new_blotato_status = creation.get("status", generation["blotato_status"])
    new_status = _normalize_status(new_blotato_status)

    slow_notification_sent_at = generation.get("slow_notification_sent_at")
    if new_status == "processing":
        created_at = datetime.fromisoformat(generation["created_at"])
        age = datetime.now(timezone.utc) - created_at
        if age > timedelta(minutes=GENERATION_STALE_TIMEOUT_MINUTES):
            new_blotato_status = "timeout-exceeded"
            new_status = "failed"
        elif age > timedelta(minutes=GENERATION_SLOW_WARNING_MINUTES) and not slow_notification_sent_at:
            _notify_slow(client, generation)
            slow_notification_sent_at = datetime.now(timezone.utc).isoformat()

    update = {
        "blotato_status": new_blotato_status,
        "status": new_status,
        "media_url": creation.get("mediaUrl"),
        "image_urls": creation.get("imageUrls"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "slow_notification_sent_at": slow_notification_sent_at,
    }
    updated = (
        client.table("generations").update(update).eq("id", generation["id"]).execute()
    )
    result = updated.data[0]

    if new_status in _TERMINAL_STATUSES:
        _notify_terminal(client, result)
        if new_status == "ready":
            result = _handle_ready_transition(client, result)

    return result


def _maybe_learn_template_cost(client, generation: dict) -> None:
    """Finishes what start_generation (or guardrails._retry) started: if
    this generation was snapshotted as an unmeasured-template attempt,
    diff the real balance now against that snapshot and persist it as
    this template's first real cost measurement. No-ops if this
    generation was never snapshotted, or if another concurrent generation
    of the same template already measured it in the meantime."""
    before = generation.get("credit_balance_before_start")
    if before is None:
        return

    _, is_measured = credits.cost_for_template(client, generation["template_id"])
    if not is_measured:
        after = blotato_client.get_credit_balance()
        measured_cost = max(0, before - after)
        client.table("template_costs").insert(
            {"template_id": generation["template_id"], "credit_cost": measured_cost}
        ).execute()
    client.table("generations").update({"credit_balance_before_start": None}).eq("id", generation["id"]).execute()


def _notify_slow(client, generation: dict) -> None:
    notifications.notify(
        client,
        recipient_type="admin",
        type_="generation_slow",
        message=(
            f"Still processing, taking longer than usual: "
            f"{generation.get('template_description') or generation['template_id']} "
            f"(over {GENERATION_SLOW_WARNING_MINUTES} minutes so far — not necessarily stuck, "
            f"real video render times have ranged up to ~6 minutes in this build's own testing; "
            f"will escalate to a real failure only past {GENERATION_STALE_TIMEOUT_MINUTES} minutes)."
        ),
        customer_id=generation["customer_id"],
    )


def _notify_terminal(client, generation: dict) -> None:
    if generation["status"] == "ready":
        message = f"Generation ready for review: {generation.get('template_description') or generation['template_id']}"
        notif_type = "generation_ready"
    else:
        # Surface the actual reason (e.g. "insufficient-credits",
        # "timeout-exceeded") rather than a bare "failed" — the reason is
        # immediately actionable (top up credits vs. investigate a stuck
        # job) and shouldn't require admin to go dig through the row.
        reason = generation.get("blotato_status")
        reason_suffix = f" ({reason})" if reason and reason != "failed" else ""
        message = f"Generation failed{reason_suffix}: {generation.get('template_description') or generation['template_id']}"
        notif_type = "generation_failed"

    notifications.notify(client, recipient_type="admin", type_=notif_type, message=message, customer_id=generation["customer_id"])
