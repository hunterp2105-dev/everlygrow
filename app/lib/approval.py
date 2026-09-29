"""Customer approval queue + publish/delivery dispatch (§16 steps 19-20).

One queue, one set of columns on the shared `generations` row (Phase 5
already put guardrail state there — approval state follows the same
pattern) — covering Social and Video Design & Graphic Creator alike. Only
what happens *after* approval differs by module:
  - social -> real Blotato publish (POST /v2/posts), then poll to
    published/failed, with the same retry-then-escalate pattern as
    guardrails (Phase 5) for publish failures.
  - video_design_graphic_creator -> mark the design_deliverables row
    delivered; no external call, there's nothing to "publish".

Only ever call approve_generation() through the real customer approval UI
(app/views/customer_hub.py) or an explicit, human-confirmed test — this is
the actual gate that makes publishing real per the build packet ("nothing
goes live until guardrails and approval exist"). There is no bypass.

PRIVILEGE NOTE: approve_generation()/request_changes() write fields a
customer's own RLS session cannot (generations only grants customers
SELECT; publish tracking, escalations, and notifications are admin-only
inserts/updates). customer_hub.py therefore calls these with the
service-role client, NOT the customer's own session client — the
customer's own session is used only to look up their verified customer_id
(via their own profile, which they can't spoof). Both functions verify
`customer_id` matches the generation's actual customer_id before doing
anything, so a verified identity is still required; this isn't a bypass
of who can approve what, only of which Postgres role performs the write.
"""

from datetime import datetime, timezone

from app.lib import blotato_client, guardrails, notifications
from app.lib.caps import GUARDRAIL_MAX_RETRIES as PUBLISH_MAX_RETRIES
from app.lib.retry_policy import is_retryable_http_error

_SOCIAL_MODULE_KEY = "social"


def list_connectable_accounts(client, customer_id: str) -> list[dict]:
    """Accounts a customer could actually publish to right now — i.e.
    actually connected by admin, not just queued (see admin_panel's
    Account Connections screen for the connection step itself). Used by
    the target-account picker at approval time (approve_generation's
    target_social_account_id param) and by admin's Escalations "Set
    target account & retry" action (set_target_account_and_retry_publish)."""
    response = (
        client.table("social_accounts")
        .select("id, platform, blotato_account_id")
        .eq("customer_id", customer_id)
        .not_.is_("connected_by_admin_at", "null")
        .execute()
    )
    return response.data or []


def list_pending_approvals(client, customer_id: str) -> list[dict]:
    """Only guardrail-passed generations ever reach the customer — flagged/
    failed ones stay in the admin Escalation Queue and are never shown here."""
    response = (
        client.table("generations")
        .select("*, modules(key)")
        .eq("customer_id", customer_id)
        .eq("guardrail_status", "passed")
        .eq("approval_status", "pending_review")
        .order("created_at")
        .execute()
    )
    return response.data or []


def _verify_ownership(client, generation_id: str, customer_id: str) -> None:
    row = client.table("generations").select("customer_id").eq("id", generation_id).maybe_single().execute()
    actual_customer_id = (row.data or {}).get("customer_id") if row else None
    if actual_customer_id != customer_id:
        raise PermissionError(
            f"Generation {generation_id} belongs to customer {actual_customer_id}, not {customer_id} — refusing to act on it."
        )


def _verify_account_ownership(client, social_account_id: str, customer_id: str) -> None:
    row = client.table("social_accounts").select("customer_id").eq("id", social_account_id).maybe_single().execute()
    actual_customer_id = (row.data or {}).get("customer_id") if row else None
    if actual_customer_id != customer_id:
        raise PermissionError(
            f"Social account {social_account_id} belongs to customer {actual_customer_id}, not {customer_id} — refusing to use it."
        )


def request_changes(client, generation_id: str, feedback: str, customer_id: str) -> None:
    _verify_ownership(client, generation_id, customer_id)
    client.table("generations").update(
        {"approval_status": "changes_requested", "customer_feedback": feedback}
    ).eq("id", generation_id).execute()
    notifications.notify(
        client, recipient_type="admin", type_="customer_requested_changes",
        message=f"Customer requested changes: {feedback}", customer_id=customer_id,
    )


def approve_generation(
    client,
    generation: dict,
    approved_by_user_id: str,
    customer_id: str,
    target_social_account_id: str | None = None,
) -> dict:
    """Marks approved, then dispatches by module. Returns the updated
    generation row. `customer_id` must be the caller's own verified
    customer_id (see module docstring) — checked against the generation's
    actual customer_id before any write happens.

    `target_social_account_id` (§16 target-account-picker follow-up,
    2026-09-06): only written if this generation doesn't already have one
    (an admin-set target from Generate (Social) always wins — this never
    silently overrides it) and only after confirming it actually belongs
    to this customer, same ownership discipline as everything else here.
    Always exactly one account, never "post to all" — deliberate: content
    here is generally shaped for one platform, and posting everywhere
    would burn the daily cap without the customer expecting it. Customer
    UI (customer_hub.py) only offers this param when the customer has more
    than one connected account and none is set yet; if none is passed and
    the row still has no target, _publish's existing escalation path
    below is what catches it — this is the fix for the common case, not a
    new bypass of that fallback."""
    _verify_ownership(client, generation["id"], customer_id)

    update = {
        "approval_status": "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": approved_by_user_id,
    }
    if target_social_account_id and not generation.get("target_social_account_id"):
        _verify_account_ownership(client, target_social_account_id, customer_id)
        update["target_social_account_id"] = target_social_account_id

    updated = (
        client.table("generations")
        .update(update)
        .eq("id", generation["id"])
        .execute()
        .data[0]
    )

    module = client.table("modules").select("key").eq("id", updated["module_id"]).maybe_single().execute()
    module_key = (module.data or {}).get("key") if module else None

    if module_key == _SOCIAL_MODULE_KEY:
        return _publish(client, updated)

    # Video Design & Graphic Creator: no publish step, just mark delivered.
    client.table("design_deliverables").update(
        {
            "status": "delivered",
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "file_url": updated.get("media_url") or (updated.get("image_urls") or [None])[0],
        }
    ).eq("generation_id", updated["id"]).execute()
    return updated


# Per-platform required `target` fields, from Blotato's API reference.
# Confirmed live for tiktok (a first real publish attempt 400'd with the
# exact missing-fields list until these were added). facebook/pinterest/
# youtube are per the same reference table but NOT yet confirmed against a
# real call — verify before relying on them.
_PLATFORM_TARGET_DEFAULTS = {
    "tiktok": {
        "privacyLevel": "PUBLIC_TO_EVERYONE",
        "disabledComments": False,
        "disabledDuet": False,
        "disabledStitch": False,
        "isBrandedContent": False,
        "isYourBrand": True,
        "isAiGenerated": True,  # factually accurate for this product — every post here is AI-generated
    },
}


def build_post_payload(generation: dict, social_account: dict) -> dict:
    """The exact payload that would go to POST /v2/posts — factored out so
    it can be shown to a human for review before the first-ever real call,
    without duplicating the request-shape logic."""
    platform = social_account["platform"]
    content = {
        "text": generation.get("post_caption") or "",
        "mediaUrls": generation.get("image_urls") or ([generation["media_url"]] if generation.get("media_url") else []),
        "platform": platform,
    }
    target = {"targetType": platform, **_PLATFORM_TARGET_DEFAULTS.get(platform, {})}
    return {"account_id": social_account["blotato_account_id"], "content": content, "target": target}


def _publish(client, generation: dict) -> dict:
    # Found live (2026-09-06): a real customer approval crashed the whole
    # request instead of reaching the escalation path below, because
    # generation["target_social_account_id"] was None (this generation was
    # started with no connected account selected — see
    # admin_panel._render_generate_social, which allows Generate to run
    # without one and only warns) and supabase-py's .eq() has no special
    # case for None — it sends the literal string "None" as the filter
    # value, which Postgres then rejects as an invalid uuid (error
    # 22P02) before the query can return zero rows. Guard against it
    # explicitly rather than relying on the query to fail safely.
    target_id = generation.get("target_social_account_id")
    if not target_id:
        _escalate_publish(client, generation, {"error": "No target social account set on this generation."})
        return generation

    account = (
        client.table("social_accounts")
        .select("*")
        .eq("id", target_id)
        .maybe_single()
        .execute()
        .data
    )
    if not account:
        _escalate_publish(client, generation, {"error": f"Target social account {target_id} no longer exists."})
        return generation

    payload = build_post_payload(generation, account)
    try:
        result = blotato_client.create_post(**payload)
    except Exception as exc:  # noqa: BLE001
        return _handle_publish_failure(client, generation, {"error": str(exc)}, retryable=is_retryable_http_error(exc))

    return (
        client.table("generations")
        .update({"blotato_post_id": result["postSubmissionId"], "publish_status": "publishing"})
        .eq("id", generation["id"])
        .execute()
        .data[0]
    )


def poll_publish(client, generation: dict) -> dict:
    """Analogous to generation.poll_generation / Phase 5's guardrail
    check — same job-tracking shape, new state machine. Call repeatedly
    (e.g. from an admin/customer 'check status' button) until terminal."""
    if generation["publish_status"] in ("published", "failed"):
        return generation

    post = blotato_client.get_post(generation["blotato_post_id"])
    # Confirmed live against our first real post: GET /posts/:postSubmissionId
    # returns {postSubmissionId, status, publicUrl} — a bare "status" field
    # and "publicUrl", not the {state:{type,postUrl}} shape this code
    # guessed before ever calling it for real.
    status = post.get("status")

    if status == "published":
        updated = (
            client.table("generations")
            .update(
                {
                    "publish_status": "published",
                    "post_url": post.get("publicUrl"),
                    "published_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", generation["id"])
            .execute()
            .data[0]
        )
        notifications.notify(
            client, recipient_type="admin", type_="publish_success",
            message=f"Published: {generation.get('template_description') or generation['template_id']} — {post.get('publicUrl')}",
            customer_id=generation["customer_id"],
        )
        return updated
    if status == "failed":
        return _handle_publish_failure(client, generation, {"blotato_state": post})

    return generation


def _handle_publish_failure(client, generation: dict, details: dict, retryable: bool = True) -> dict:
    if retryable and generation["publish_retry_count"] < PUBLISH_MAX_RETRIES:
        updated = (
            client.table("generations")
            .update({"publish_retry_count": generation["publish_retry_count"] + 1, "publish_status": "not_published"})
            .eq("id", generation["id"])
            .execute()
            .data[0]
        )
        notifications.notify(
            client, recipient_type="admin", type_="publish_retry",
            message=f"Publish failed — retrying (attempt {updated['publish_retry_count']}/{PUBLISH_MAX_RETRIES}).",
            customer_id=generation["customer_id"],
        )
        return _publish(client, updated)

    updated = (
        client.table("generations")
        .update({"publish_status": "failed"})
        .eq("id", generation["id"])
        .execute()
        .data[0]
    )
    _escalate_publish(client, updated, details)
    return updated


def set_target_account_and_retry_publish(
    client, generation: dict, social_account_id: str, escalation_id: str
) -> dict:
    """Admin-side fix (Escalations' "Set target account & retry") for a
    generation that got approved with no target account, then escalated
    (see _publish's "no target account set" branch). Sets the account,
    resolves the escalation that was blocking it, and republishes through
    the exact same _publish() path any other publish uses — not a
    special-cased one-off. Admin-side call (service-role client), so no
    ownership re-check here — same privilege boundary as every other
    admin action in this module."""
    updated = (
        client.table("generations")
        .update({"target_social_account_id": social_account_id})
        .eq("id", generation["id"])
        .execute()
        .data[0]
    )
    guardrails.resolve_escalation(client, escalation_id, "Target account set by admin; retried publish.")
    return _publish(client, updated)


def _escalate_publish(client, generation: dict, details: dict) -> None:
    client.table("escalations").insert(
        {
            "generation_id": generation["id"],
            "customer_id": generation["customer_id"],
            "reason": "publish",
            "details": details,
        }
    ).execute()
    notifications.notify(
        client, recipient_type="admin", type_="publish_escalation",
        message=f"Publish escalation: {generation.get('template_description') or generation['template_id']} failed after {PUBLISH_MAX_RETRIES} retries.",
        customer_id=generation["customer_id"],
    )
