"""§16 Client Intake Questionnaire (2026-09-10): a customer's first login
shows this instead of their normal Hub (see customer_hub.py) — real
business answers come straight from the customer once, instead of admin
typing a guess into Onboard Customer on their behalf. This tests
app/lib/intake.py's actual data-writing logic against the live Supabase
project; the Streamlit form itself is exercised via AppTest separately
(see the live verification in conversation, not a permanent test — file
uploads and a real customer session are awkward to drive headlessly here,
so the form's field wiring was verified by hand against the real app).
"""

from app.lib import intake


def test_needs_intake_true_for_a_fresh_customer_with_no_completed_at(admin_client, temp_customer):
    row = admin_client.table("customers").select("intake_completed_at").eq("id", temp_customer["id"]).maybe_single().execute().data
    assert intake.needs_intake(row) is True


def test_submit_intake_marks_complete_and_stores_verbatim_responses(admin_client, temp_customer):
    responses = {
        "business_name": "Test Biz",
        "industry": "Real Estate Agents",
        "goal": "Bring in more calls",
        "logo_choice": intake.LOGO_SKIP,
        "brand_colors_fonts": "",
        "platforms": ["instagram", "tiktok"],
        "platform_sources": {"instagram": intake.ACCOUNT_EXISTING, "tiktok": intake.ACCOUNT_NEW},
        "tone": "Casual and friendly",
        "frequency": "A few times a week",
        "contact_email": "owner@testbiz.example",
        "notes": "",
    }

    intake.submit_intake(admin_client, temp_customer["id"], responses)

    updated = admin_client.table("customers").select("*").eq("id", temp_customer["id"]).maybe_single().execute().data
    assert intake.needs_intake(updated) is False
    assert updated["intake_responses"] == responses
    assert updated["name"] == "Test Biz"
    assert updated["niche"] == "Real Estate Agents"
    assert updated["email"] == "owner@testbiz.example"
    assert updated["brand_profile"]["tone_voice"] == "Casual and friendly"
    assert updated["plan_caps"]["posting_frequency"] == "A few times a week"


def test_submit_intake_resolves_the_real_niche_playbook_from_the_answer(admin_client, temp_customer):
    """Admin's original guess at Onboard Customer time shouldn't win over
    what the customer actually says here — the playbook link should
    follow the customer's real answer."""
    real_estate_playbook = (
        admin_client.table("niche_playbooks")
        .select("id")
        .eq("niche", "Real Estate Agents")
        .eq("is_default", False)
        .maybe_single()
        .execute()
        .data
    )
    responses = {
        "business_name": "Test Realty",
        "industry": "Real Estate Agents",
        "goal": "More listing inquiries",
        "logo_choice": intake.LOGO_SKIP,
        "brand_colors_fonts": "",
        "platforms": ["instagram"],
        "platform_sources": {"instagram": intake.ACCOUNT_EXISTING},
        "tone": "Professional and polished",
        "frequency": "Daily",
        "contact_email": "agent@testrealty.example",
        "notes": "",
    }

    intake.submit_intake(admin_client, temp_customer["id"], responses)

    updated = admin_client.table("customers").select("niche_playbook_id").eq("id", temp_customer["id"]).maybe_single().execute().data
    assert updated["niche_playbook_id"] == real_estate_playbook["id"]


def test_submit_intake_queues_the_chosen_platforms_as_real_social_accounts(admin_client, temp_customer):
    responses = {
        "business_name": "Test Biz",
        "industry": "General",
        "goal": "Awareness",
        "logo_choice": intake.LOGO_SKIP,
        "brand_colors_fonts": "",
        "platforms": ["x"],
        "platform_sources": {"x": intake.ACCOUNT_NEW},
        "tone": "Bold and energetic",
        "frequency": "Not sure — recommend something",
        "contact_email": "owner@testbiz.example",
        "notes": "",
    }

    intake.submit_intake(admin_client, temp_customer["id"], responses)

    accounts = admin_client.table("social_accounts").select("*").eq("customer_id", temp_customer["id"]).execute().data
    assert len(accounts) == 1
    assert accounts[0]["platform"] == "x"
    assert accounts[0]["source"] == "new"
    assert accounts[0]["warm_up_status"] == "pending_connection"


def test_submit_intake_does_not_duplicate_an_already_queued_platform(admin_client, temp_customer):
    admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "instagram", "source": "existing"}
    ).execute()

    responses = {
        "business_name": "Test Biz",
        "industry": "General",
        "goal": "Awareness",
        "logo_choice": intake.LOGO_SKIP,
        "brand_colors_fonts": "",
        "platforms": ["instagram"],
        "platform_sources": {"instagram": intake.ACCOUNT_EXISTING},
        "tone": "Bold and energetic",
        "frequency": "Daily",
        "contact_email": "owner@testbiz.example",
        "notes": "",
    }

    intake.submit_intake(admin_client, temp_customer["id"], responses)

    accounts = admin_client.table("social_accounts").select("id").eq("customer_id", temp_customer["id"]).eq("platform", "instagram").execute().data
    assert len(accounts) == 1


def test_existing_customers_were_grandfathered_by_the_migration(admin_client):
    """The migration backfills intake_completed_at for every customer that
    existed at migration time — a real, already-active customer should
    never suddenly be blocked by this gate."""
    real_estate = (
        admin_client.table("customers")
        .select("intake_completed_at")
        .eq("name", "Niche Validation - Real Estate Agents")
        .maybe_single()
        .execute()
        .data
    )
    assert real_estate is not None, "Expected this real demo customer to still exist"
    assert intake.needs_intake(real_estate) is False
