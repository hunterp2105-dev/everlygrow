"""Email sending — STUBBED pending a real provider (Resend/SendGrid/
Postmark/etc.), same pattern as blotato_client's publish stub before
Phase 6: the real trigger logic and call site exist now, only the actual
network send is disabled. Search for EMAIL_SENDING_DISABLED before wiring
a real provider.

When wiring a real provider: add its API key to .env (never hardcode),
implement the actual HTTP call in send_email(), and flip
EMAIL_SENDING_DISABLED to False. Nothing else in the notification system
needs to change — app/lib/notifications.py already calls this at the
right point for every time-sensitive trigger.
"""

from app.lib import supabase_client

EMAIL_SENDING_DISABLED = True


def send_email(to: str | None, subject: str, body: str) -> dict:
    if not EMAIL_SENDING_DISABLED:
        raise RuntimeError("send_email() should not be reachable while EMAIL_SENDING_DISABLED is True.")
    if not to:
        return {"sent": False, "reason": "No recipient email resolved."}
    return {"sent": False, "reason": "Email sending is stubbed pending a real provider.", "would_have_sent": {"to": to, "subject": subject, "body": body}}


def resolve_recipient(client, notification: dict) -> str | None:
    if notification["recipient_type"] == "customer":
        if not notification.get("customer_id"):
            return None
        customer = client.table("customers").select("email").eq("id", notification["customer_id"]).maybe_single().execute()
        return (customer.data or {}).get("email") if customer else None

    # Admin: no stored "admin contact email" field anywhere — resolve via
    # the one profiles row with role='admin' and look up its auth email.
    # Needs the service-role client for the admin.list_users() call;
    # best-effort, since sending is stubbed anyway.
    try:
        admin_client = supabase_client.get_supabase_admin_client()
        profile = client.table("profiles").select("id").eq("role", "admin").limit(1).maybe_single().execute()
        admin_id = (profile.data or {}).get("id") if profile else None
        if not admin_id:
            return None
        user = admin_client.auth.admin.get_user_by_id(admin_id)
        return user.user.email if user and user.user else None
    except Exception:  # noqa: BLE001 - recipient resolution failing shouldn't crash the notify path
        return None
