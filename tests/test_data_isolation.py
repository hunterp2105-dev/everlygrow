"""§16 step 43 — data isolation. Two real customer sessions, two
independent Supabase clients (see conftest.signed_in_customer_client_factory
for why independent clients, not the app's session_state-cached one — this
is the exact multi-tenant session-bleed shape Phase 1 found and fixed), each
signed in as a genuine auth user with a real RLS-scoped session — not the
service-role client. Confirms customer A's session cannot read customer B's
rows across every customer-facing table, and that writes are scoped too.
"""

from app.lib import tickets


def test_customer_cannot_read_other_customers_generations(admin_client, temp_customer_pair, signed_in_customer_client_factory):
    customer_a, customer_b = temp_customer_pair
    module_id = admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]

    gen_b = admin_client.table("generations").insert(
        {"customer_id": customer_b["id"], "module_id": module_id, "template_id": "test-template", "prompt": "isolation test"}
    ).execute().data[0]

    client_a = signed_in_customer_client_factory(customer_a["id"])

    visible_to_a = client_a.table("generations").select("*").eq("id", gen_b["id"]).execute().data
    assert visible_to_a == [], "Customer A's session could read Customer B's generation row"

    all_visible_to_a = client_a.table("generations").select("id").execute().data
    assert all(row["id"] != gen_b["id"] for row in all_visible_to_a)


def test_customer_cannot_read_other_customers_record(temp_customer_pair, signed_in_customer_client_factory):
    customer_a, customer_b = temp_customer_pair
    client_a = signed_in_customer_client_factory(customer_a["id"])

    visible = client_a.table("customers").select("*").eq("id", customer_b["id"]).execute().data
    assert visible == [], "Customer A's session could read Customer B's customer record"

    own_record = client_a.table("customers").select("*").eq("id", customer_a["id"]).execute().data
    assert len(own_record) == 1, "Customer A's session could not even read their OWN record"


def test_customer_cannot_read_other_customers_notifications(admin_client, temp_customer_pair, signed_in_customer_client_factory):
    customer_a, customer_b = temp_customer_pair
    admin_client.table("notifications").insert(
        {"recipient_type": "customer", "customer_id": customer_b["id"], "type": "approval_ready", "message": "for B only"}
    ).execute()

    client_a = signed_in_customer_client_factory(customer_a["id"])
    visible = client_a.table("notifications").select("*").eq("customer_id", customer_b["id"]).execute().data
    assert visible == [], "Customer A's session could read a notification addressed to Customer B"


def test_customer_cannot_write_to_other_customers_tickets(admin_client, temp_customer_pair, signed_in_customer_client_factory):
    """Tickets has a genuine `for all` policy for customers on their own
    rows (see app/lib/tickets.py's module docstring) — confirms that
    breadth doesn't accidentally extend to another customer's rows."""
    customer_a, customer_b = temp_customer_pair
    client_a = signed_in_customer_client_factory(customer_a["id"])

    # Attempting to create a ticket under B's customer_id from A's session:
    # the insert either fails outright (RLS with_check) or, if it somehow
    # succeeds at the DB layer, A's own session must never be able to SEE
    # it afterward reading back as B's.
    try:
        tickets.create_ticket(client_a, customer_b["id"], "spoofed subject", "spoofed message", sender_id=None)
    except Exception:
        pass  # RLS rejecting the write outright is the expected/correct outcome

    leaked = admin_client.table("tickets").select("*").eq("customer_id", customer_b["id"]).eq("subject", "spoofed subject").execute().data
    assert leaked == [], "Customer A's session was able to create a ticket recorded under Customer B's customer_id"


def test_customer_session_has_no_service_role_privileges(temp_customer_pair, signed_in_customer_client_factory):
    """A customer's own session must never be able to do what only the
    service-role client should (e.g. writing another customer's approval
    state) — this is the exact boundary approval.py's privilege note
    depends on being real, not just documented."""
    customer_a, customer_b = temp_customer_pair
    client_a = signed_in_customer_client_factory(customer_a["id"])

    result = (
        client_a.table("generations")
        .update({"approval_status": "approved"})
        .eq("customer_id", customer_b["id"])
        .execute()
    )
    assert result.data == [], "Customer A's session was able to update a generation belonging to Customer B"
