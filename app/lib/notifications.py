"""Notification center (§9): one insert path for every trigger, in-app
list/mark-read, and the email dispatch decision for time-sensitive types.

§9's full trigger list and where each one now actually fires:
  - generation ready for admin review  -> generation._notify_terminal
  - guardrail flag                     -> guardrails._retry / _escalate
  - content ready for customer approval -> guardrails.review_ready_generation (passed branch)
  - ticket response                    -> tickets.reply (both directions: admin->customer
                                           fires "ticket_response", customer->admin fires
                                           "new_ticket_message" — wired in Phase 10)
  - publish success/failure            -> approval.poll_publish / _handle_publish_failure
  - optimizer suggestion               -> optimizer.generate_suggestions
  - warm-up complete                   -> admin_panel._render_account_connections
  - credit/cost threshold              -> credits.check_credit_threshold
  - Blotato pool cap approaching       -> credits.check_pool_cap
  - generation stuck/timed out         -> generation.poll_generation (staleness check,
                                           reuses the existing "generation_failed" trigger)
  - generation running unusually long  -> generation.poll_generation / _notify_slow
                                           ("generation_slow" — §16 step 50; not a failure,
                                           fires once per generation past
                                           GENERATION_SLOW_WARNING_MINUTES, well short of the
                                           staleness timeout above)
"""

from datetime import datetime, timezone

from app.lib import email_client

TIME_SENSITIVE_TYPES = {
    "guardrail_escalation",
    "publish_escalation",
    "credit_threshold",
    "pool_cap_approaching",
}
"""§9: "email for time-sensitive items" — the ones that need admin
attention soon, not just FYI. Not specified exhaustively in the packet;
this is the readable starting set — escalations (something is stuck) and
threshold warnings (something needs a decision soon)."""


def notify(client, recipient_type: str, type_: str, message: str, customer_id: str | None = None) -> dict:
    row = (
        client.table("notifications")
        .insert(
            {
                "recipient_type": recipient_type,
                "customer_id": customer_id,
                "type": type_,
                "message": message,
                "email_status": "pending" if type_ in TIME_SENSITIVE_TYPES else "not_applicable",
            }
        )
        .execute()
        .data[0]
    )
    if row["email_status"] == "pending":
        _dispatch_email(client, row)
    return row


def _dispatch_email(client, notification: dict) -> None:
    result = email_client.send_email(
        to=email_client.resolve_recipient(client, notification),
        subject=f"[EverlyGrow] {notification['type'].replace('_', ' ').title()}",
        body=notification["message"],
    )
    client.table("notifications").update(
        {
            "email_status": "sent" if result["sent"] else "failed",
            "email_sent_at": datetime.now(timezone.utc).isoformat() if result["sent"] else None,
        }
    ).eq("id", notification["id"]).execute()


def list_notifications(client, recipient_type: str, customer_id: str | None = None, unread_only: bool = False) -> list[dict]:
    query = client.table("notifications").select("*").eq("recipient_type", recipient_type).order("created_at", desc=True)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    if unread_only:
        query = query.eq("read_status", False)
    return query.execute().data or []


def mark_read(client, notification_id: str) -> None:
    client.table("notifications").update({"read_status": True}).eq("id", notification_id).execute()


def unread_count(client, recipient_type: str, customer_id: str | None = None) -> int:
    query = client.table("notifications").select("id", count="exact").eq("recipient_type", recipient_type).eq("read_status", False)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    return query.execute().count or 0
