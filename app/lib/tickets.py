"""Tickets/Requests (§4a Hub-core feature; §16 step 30's "ticket inbox").

Both sides of the same feature, built together: a customer submitting a
request and an admin never seeing it (or vice versa) isn't a working
ticket system — it's the same "dead code" gap Phase 9 flagged for the
"ticket response" notification trigger, which becomes real here.

Status model: 'open' = needs admin attention (customer sent the latest
message), 'pending' = awaiting the customer (admin sent the latest
message), 'resolved' = closed by admin. Not specified in the packet;
a reasonable minimal state machine for a two-party thread.

PRIVILEGE NOTE: tickets/ticket_messages RLS already grants customers a
genuine `for all` policy on their own rows (Phase 1) — unlike generations,
no ownership-check workaround is needed for the ticket writes themselves.
But `notifications` only grants admin insert; a customer session calling
notifications.notify(recipient_type="admin", ...) after creating/replying
to their own ticket would fail under RLS. So the notification side effect
always goes through the service-role client here, regardless of which
client was passed for the ticket/message writes — same reasoning as
approval.py's privilege note, narrower in scope (only this one insert).
"""

from app.lib import notifications, supabase_client


def create_ticket(client, customer_id: str, subject: str, first_message: str, sender_id: str) -> dict:
    ticket = (
        client.table("tickets")
        .insert({"customer_id": customer_id, "subject": subject, "status": "open"})
        .execute()
        .data[0]
    )
    client.table("ticket_messages").insert(
        {"ticket_id": ticket["id"], "sender_role": "customer", "sender_id": sender_id, "body": first_message}
    ).execute()
    notifications.notify(
        supabase_client.get_supabase_admin_client(), recipient_type="admin", type_="new_ticket_message",
        message=f"New ticket from customer: {subject}", customer_id=customer_id,
    )
    return ticket


def reply(client, ticket_id: str, sender_role: str, sender_id: str | None, body: str, customer_id: str) -> dict:
    client.table("ticket_messages").insert(
        {"ticket_id": ticket_id, "sender_role": sender_role, "sender_id": sender_id, "body": body}
    ).execute()

    new_status = "pending" if sender_role == "admin" else "open"
    updated_ticket = client.table("tickets").update({"status": new_status}).eq("id", ticket_id).execute().data[0]

    admin_client = supabase_client.get_supabase_admin_client()
    if sender_role == "admin":
        # §9's "ticket response" trigger — the customer-facing counterpart.
        notifications.notify(
            admin_client, recipient_type="customer", type_="ticket_response",
            message=f"Your admin replied to '{updated_ticket['subject']}'.", customer_id=customer_id,
        )
    else:
        # Not explicitly named in §9's trigger list, but an admin ticket
        # inbox with no way to know a new message arrived isn't usable —
        # a natural, minimal extension, not a literal packet requirement.
        notifications.notify(
            admin_client, recipient_type="admin", type_="new_ticket_message",
            message=f"New reply on '{updated_ticket['subject']}'.", customer_id=customer_id,
        )
    return updated_ticket


def list_tickets(client, customer_id: str | None = None, status: str | None = None) -> list[dict]:
    query = client.table("tickets").select("*, customers(name)").order("created_at", desc=True)
    if customer_id:
        query = query.eq("customer_id", customer_id)
    if status:
        query = query.eq("status", status)
    return query.execute().data or []


def get_thread(client, ticket_id: str) -> list[dict]:
    return (
        client.table("ticket_messages")
        .select("*")
        .eq("ticket_id", ticket_id)
        .order("created_at")
        .execute()
        .data
        or []
    )


def resolve_ticket(client, ticket_id: str) -> None:
    client.table("tickets").update({"status": "resolved"}).eq("id", ticket_id).execute()
