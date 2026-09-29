"""Client Intake Questionnaire (§16 admin follow-up, 2026-09-10): a
customer's first login shows this instead of their normal Hub (see
customer_hub.py) — the real business answers (niche, tone, platforms,
goals) now come straight from the customer once, instead of admin typing
a guess into Onboard Customer on their behalf.

Answers are stored two ways: verbatim in customers.intake_responses (so
admin can just read exactly what was submitted — see
admin_panel._render_customers), AND written through to the same
structured columns/tables the rest of the app already reads (niche,
niche_playbook_id, brand_profile, plan_caps, social_accounts) so nothing
about generation/caps/playbook-resolution needs to change to use this
data — it lands in the same places Onboard Customer already writes to.

PRIVILEGE NOTE: same pattern as approval.py — a customer's own RLS
session can only SELECT customers/social_accounts (see migration 0001),
so submit_intake() must always be called with the service-role client,
using the caller's own verified customer_id from their profile (which
they can't spoof) — never a customer_id taken from user input.
"""

from datetime import datetime, timezone

from app.lib import onboarding
from app.lib.caps import DEFAULT_WARM_UP_PERIOD_DAYS

LOGO_UPLOAD = "Yes, I'll upload it"
LOGO_DESIGN = "No — I'd like one designed (premium add-on)"
LOGO_SKIP = "No, and I'll skip this for now"
LOGO_OPTIONS = [LOGO_UPLOAD, LOGO_DESIGN, LOGO_SKIP]

TONE_OPTIONS = ["Casual and friendly", "Professional and polished", "Bold and energetic", "Not sure — you decide"]
FREQUENCY_OPTIONS = ["A few times a week", "Daily", "Not sure — recommend something"]

ACCOUNT_EXISTING = "I have an account"
ACCOUNT_NEW = "Please create a new one for me"
ACCOUNT_SOURCE_OPTIONS = [ACCOUNT_EXISTING, ACCOUNT_NEW]

PLATFORM_OPTIONS = onboarding.PLATFORMS  # ["tiktok", "instagram", "x"] — same list, one source of truth
MAX_PLATFORMS = 3

LOGO_BUCKET = "customer-logos"


def needs_intake(customer: dict) -> bool:
    return customer.get("intake_completed_at") is None


def _upload_logo(client, customer_id: str, uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    path = f"{customer_id}/{uploaded_file.name}"
    client.storage.from_(LOGO_BUCKET).upload(
        path,
        uploaded_file.getvalue(),
        {"content-type": uploaded_file.type or "application/octet-stream", "upsert": "true"},
    )
    return client.storage.from_(LOGO_BUCKET).get_public_url(path)


def submit_intake(client, customer_id: str, responses: dict, uploaded_logo=None) -> None:
    """`client` must be the service-role client (see module docstring).

    `responses` keys: business_name, industry, goal, logo_choice
    (one of LOGO_OPTIONS), brand_colors_fonts, platforms (list[str]),
    platform_sources (dict[str, str], platform -> one of
    ACCOUNT_SOURCE_OPTIONS), tone (one of TONE_OPTIONS), frequency (one
    of FREQUENCY_OPTIONS), contact_email, notes.
    """
    logo_url = _upload_logo(client, customer_id, uploaded_logo) if responses.get("logo_choice") == LOGO_UPLOAD else None

    current = client.table("customers").select("brand_profile, plan_caps, email").eq("id", customer_id).maybe_single().execute()
    current_data = current.data if current else {}

    # Re-resolve the niche playbook from the customer's own answer — admin's
    # guess at Onboard Customer time may not match what the customer
    # actually says here, and content suggestions/guardrails read this.
    playbook_resolution = onboarding.resolve_playbook(client, responses["industry"])
    playbook = playbook_resolution["playbook"]

    update = {
        "niche": responses["industry"],
        "niche_playbook_id": playbook["id"] if playbook else None,
        "email": responses.get("contact_email") or current_data.get("email"),
        "brand_profile": {
            **(current_data.get("brand_profile") or {}),
            "tone_voice": responses["tone"],
            "goals": responses.get("goal") or "",
            "brand_colors_fonts": responses.get("brand_colors_fonts") or "",
        },
        "plan_caps": {**(current_data.get("plan_caps") or {}), "posting_frequency": responses["frequency"]},
        "intake_completed_at": datetime.now(timezone.utc).isoformat(),
        "intake_responses": responses,
    }
    if responses.get("business_name"):
        update["name"] = responses["business_name"]
    if logo_url:
        update["logo_url"] = logo_url

    client.table("customers").update(update).eq("id", customer_id).execute()
    _queue_platform_accounts(client, customer_id, responses.get("platform_sources") or {})


def _queue_platform_accounts(client, customer_id: str, platform_sources: dict) -> None:
    """Mirrors onboarding.provision_customer's platform-queueing step
    exactly (same pool assignment, same pending_connection status) —
    admin still connects each one for real via Account Connections,
    same as any other queued account."""
    if not platform_sources:
        return
    existing = client.table("social_accounts").select("platform").eq("customer_id", customer_id).execute().data or []
    existing_platforms = {row["platform"] for row in existing}
    pool = onboarding.pick_pool(client)
    for platform, source in platform_sources.items():
        if platform in existing_platforms:
            continue
        client.table("social_accounts").insert(
            {
                "customer_id": customer_id,
                "platform": platform,
                "source": "existing" if source == ACCOUNT_EXISTING else "new",
                "blotato_pool_id": pool["id"] if pool else None,
                "warm_up_status": "pending_connection",
                "warm_up_period_days": DEFAULT_WARM_UP_PERIOD_DAYS,
            }
        ).execute()
