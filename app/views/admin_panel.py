from datetime import date, datetime, timedelta, timezone

import streamlit as st

from app.lib import (
    analytics,
    approval,
    auth,
    blotato_client,
    credits,
    design,
    generation,
    growth_rules,
    guardrails,
    notifications,
    onboarding,
    optimizer,
    playbook_refinement,
    supabase_client,
    tickets,
)
from app.lib import calendar as calendar_module
from app.lib.caps import DEFAULT_WARM_UP_PERIOD_DAYS
from app.lib.theme import card_close, card_open, empty_state, metric_tile, module_map_svg, progress_line, stamp

# §16 admin usability pass (2026-09-03): flat 16-item nav replaced with
# grouped sections (Operations / Customers / Monitoring / Support / System)
# after direct user feedback that the old list had no sense of what's
# primary vs secondary. "Resume Onboarding" was folded into "Onboard
# Customer" (as a "Needs attention" section, badge-counted below) rather
# than kept as a separate permanent item, since a first-time admin had no
# way to know when to check one screen vs. the other.
NAV_GROUPS = {
    "Operations": ["Generate (Social)", "Design Requests", "Escalations", "Calendar"],
    "Customers": ["Customer Overview", "Customers", "Onboard Customer", "Account Connections", "Playbooks"],
    "Monitoring": ["Analytics", "Content Suggestions", "Notifications", "Credit & Cost Tracker", "Account Pool Capacity"],
    "Support": ["Tickets"],
    # Module Map is a static architecture diagram, not an operational
    # screen — no admin workflow ever requires opening it, so it's kept
    # in its own de-emphasized group rather than mixed into Customers.
    "System": ["Module Map"],
}
_ITEM_TO_GROUP = {item: group for group, items in NAV_GROUPS.items() for item in items}

HOLIDAY_OPTIONS = ["Major U.S. holidays", "Industry awareness days", "None"]
VOICE_OPTIONS = list(blotato_client.VOICES.keys())
GUARDRAIL_OPTIONS = ["strict", "standard", "relaxed"]


def _all_customers() -> list[dict]:
    client = supabase_client.get_supabase_client()
    response = (
        client.table("customers")
        .select("id, name, niche, niche_playbook_id, niche_playbooks(niche, is_default)")
        .execute()
    )
    return response.data or []


def _all_modules() -> list[dict]:
    client = supabase_client.get_supabase_client()
    response = client.table("modules").select("key, name, status").order("status").execute()
    return response.data or []


def _customer_active_modules(client, customer_id: str) -> list[str]:
    response = (
        client.table("customer_modules")
        .select("enabled, modules(name)")
        .eq("customer_id", customer_id)
        .eq("enabled", True)
        .execute()
    )
    return [row["modules"]["name"] for row in (response.data or []) if row.get("modules")]


def _render_active_customer_switcher() -> None:
    """§16 Active Customer follow-up (2026-09-06): pinned at the top of
    the sidebar, above the section/screen nav — every screen that used to
    have its own "pick a customer" dropdown now reads this instead (see
    _active_customer()), so switching customers doesn't mean re-picking
    them on every single screen. Must run before the nav radios AND
    before whichever screen gets dispatched this same run, since it's a
    plain top-to-bottom script rerun — see render()."""
    customers = _all_customers()
    name_by_id = {c["id"]: c["name"] for c in customers}

    current = st.session_state.get("active_customer_id")
    if current is not None and current not in name_by_id:
        # Stale reference (e.g. the customer was removed) — reset rather
        # than point at a customer that no longer exists, and rather than
        # letting st.selectbox raise on an option list that no longer
        # contains the persisted value.
        st.session_state["active_customer_id"] = None

    st.markdown("**Active Customer**")
    st.selectbox(
        "Active Customer",
        [None] + list(name_by_id.keys()),
        key="active_customer_id",
        format_func=lambda cid: name_by_id.get(cid, "— No customer selected —"),
        label_visibility="collapsed",
    )
    st.session_state["active_customer_name"] = name_by_id.get(st.session_state["active_customer_id"])
    st.divider()


def _active_customer() -> tuple[str, str] | None:
    """(customer_id, customer_name) for the sidebar's Active Customer, or
    None if nothing is selected. A pure session-state read — no query —
    since _render_active_customer_switcher() already resolved and stored
    the name earlier in this same render() pass."""
    customer_id = st.session_state.get("active_customer_id")
    if not customer_id:
        return None
    return customer_id, st.session_state.get("active_customer_name") or "Unknown customer"


def _require_active_customer_in(customers: list[dict], module_label: str) -> tuple[str, str] | None:
    """For the single-customer work screens (Generate, Design Requests,
    Analytics): the Active Customer must be set AND must actually be in
    `customers` (this screen's module-filtered list) — never silently
    fall back to a different customer just because the active one isn't
    eligible here. Renders its own explanatory empty-state and returns
    None when either condition fails; caller still owns card_close()."""
    active = _active_customer()
    if active is None:
        empty_state("Pick an Active Customer in the sidebar to get started.")
        return None
    customer_id, customer_name = active
    if not any(c["id"] == customer_id for c in customers):
        empty_state(
            f"{customer_name} doesn't have {module_label} enabled — pick a different Active Customer "
            "in the sidebar, or enable it for them in Customers."
        )
        return None
    return customer_id, customer_name


def _scoped_customer_filter(key_prefix: str) -> str | None:
    """For the cross-customer inbox screens (Tickets, Escalations,
    Account Connections, Credit & Cost Tracker, Notifications): these
    stay cross-customer by design (a shared queue to triage, not a
    per-customer detail view) — the Active Customer only sets the
    DEFAULT filter, never a hard scope, via an explicit "show all"
    checkbox to back out. Returns the customer_id to filter by, or None
    to show everyone (no Active Customer set, or "show all" checked)."""
    active = _active_customer()
    if active is None:
        return None
    customer_id, customer_name = active
    show_all = st.checkbox(
        "Show all customers",
        value=False,
        key=f"{key_prefix}_show_all",
        help=f"Unchecked: filtered to your Active Customer ({customer_name}).",
    )
    return None if show_all else customer_id


def _render_customers() -> None:
    client = supabase_client.get_supabase_client()
    customers = _all_customers()
    card_open("Customers", elevated=True)
    if not customers:
        empty_state("No customers yet — use Onboard Customer to add your first one.")
        card_close()
        return

    for customer in customers:
        playbook = customer.get("niche_playbooks")
        if playbook:
            tag = "General default" if playbook.get("is_default") else playbook.get("niche")
        else:
            tag = "No playbook resolved"
        active_modules = _customer_active_modules(client, customer["id"])

        with st.container():
            st.markdown(
                f"**{customer['name']}** &nbsp;·&nbsp; {customer.get('niche') or 'No niche set'} "
                f"&nbsp;·&nbsp; playbook: {tag}"
            )
            st.caption("Active modules: " + (", ".join(active_modules) if active_modules else "none"))

            with st.expander("Per-customer config"):
                full = client.table("customers").select("*").eq("id", customer["id"]).maybe_single().execute().data or {}
                sensitivity = (full.get("guardrail_config") or {}).get("sensitivity", "standard")
                with st.form(f"config_{customer['id']}"):
                    new_sensitivity = st.selectbox(
                        "Guardrail sensitivity", GUARDRAIL_OPTIONS,
                        index=GUARDRAIL_OPTIONS.index(sensitivity) if sensitivity in GUARDRAIL_OPTIONS else 1,
                        key=f"sens_{customer['id']}",
                    )
                    new_budget = st.number_input(
                        "Credit budget (this billing period, estimated units — leave 0 for no budget)",
                        min_value=0.0, value=float(full.get("credit_budget") or 0), key=f"budget_{customer['id']}",
                    )
                    new_character_description = st.text_area(
                        "Default video character description",
                        value=full.get("default_character_description") or "",
                        placeholder=blotato_client.DEFAULT_SELFIE_CHARACTER_DESCRIPTION,
                        help=(
                            "Used automatically for this customer's video generations on the "
                            "'AI Selfie Talking Video with Consistent Character' template, so their "
                            "videos show the same on-screen presenter every time (overridable per "
                            "generation on the Generate screen). Leave blank to use the generic default."
                        ),
                        key=f"character_{customer['id']}",
                    )
                    if st.form_submit_button("Save"):
                        client.table("customers").update(
                            {
                                "guardrail_config": {**(full.get("guardrail_config") or {}), "sensitivity": new_sensitivity},
                                "credit_budget": new_budget or None,
                                "default_character_description": new_character_description or None,
                            }
                        ).eq("id", customer["id"]).execute()
                        st.success("Saved.")
                        st.rerun()

            _render_intake_summary(client, customer["id"])

    card_close()


_INTAKE_LABELS = {
    "business_name": "Business name",
    "industry": "Industry / type of business",
    "goal": "What they want social media to do",
    "logo_choice": "Logo",
    "brand_colors_fonts": "Brand colors/fonts",
    "platforms": "Platforms to manage",
    "platform_sources": "Existing vs. new accounts",
    "tone": "Tone",
    "frequency": "Posting frequency",
    "contact_email": "Contact email",
    "notes": "Anything else",
}
_INTAKE_PLATFORM_LABELS = {"tiktok": "TikTok", "instagram": "Instagram", "x": "X (Twitter)"}


def _format_intake_value(key: str, value) -> str:
    if key == "platforms" and isinstance(value, list):
        return ", ".join(_INTAKE_PLATFORM_LABELS.get(p, p) for p in value)
    if key == "platform_sources" and isinstance(value, dict):
        return "; ".join(f"{_INTAKE_PLATFORM_LABELS.get(p, p)}: {v}" for p, v in value.items())
    return str(value) if value not in (None, "") else "—"


def _render_intake_summary(client, customer_id: str) -> None:
    """§16 Client Intake Questionnaire (2026-09-10): what a customer
    submitted on their first login (see app/lib/intake.py,
    customer_hub._render_intake_form) — shown verbatim, per-question,
    right where admin already looks for everything else about this
    customer, rather than requiring a trip to a separate screen."""
    with st.expander("Intake Questionnaire"):
        row = (
            client.table("customers")
            .select("intake_completed_at, intake_responses, logo_url")
            .eq("id", customer_id)
            .maybe_single()
            .execute()
        )
        data = row.data if row else {}
        if not data.get("intake_completed_at"):
            st.markdown(stamp("Not submitted yet", "planned"), unsafe_allow_html=True)
            return

        st.markdown(f"{stamp('Submitted', 'approved')}  ·  {data['intake_completed_at']}", unsafe_allow_html=True)
        responses = data.get("intake_responses") or {}
        for key, label in _INTAKE_LABELS.items():
            if key in responses:
                st.markdown(f"**{label}:** {_format_intake_value(key, responses[key])}")
        if data.get("logo_url"):
            st.markdown(f"**Logo:** [view uploaded file]({data['logo_url']})")


def _render_module_map() -> None:
    card_open("Module Map", elevated=True)
    st.caption(
        "The whiteboard-sketch structure (§4a): a fixed Hub at the center, with independent "
        "modules plugged in — new ones added later without rebuilding what's already here."
    )
    modules = _all_modules()
    st.markdown(module_map_svg("HUB", modules), unsafe_allow_html=True)
    card_close()


def _incomplete_intake_count(client) -> int:
    return len(onboarding.list_incomplete_intakes(client))


def _render_needs_attention_section(client) -> None:
    """Folded in from the old standalone "Resume Onboarding" nav item —
    a first-time admin had no way to know when to check that screen vs.
    this one, so incomplete attempts now surface right where a new one
    would be started, badge-counted in the nav (see render())."""
    intakes = onboarding.list_incomplete_intakes(client)
    if not intakes:
        return

    try:
        admin_client = supabase_client.get_supabase_admin_client()
    except RuntimeError as exc:
        st.error(str(exc))
        admin_client = None

    with st.expander(f"⚠️ Needs attention — {len(intakes)} incomplete onboarding attempt(s)", expanded=True):
        for intake in intakes:
            with st.container():
                st.markdown(f"**{intake['payload'].get('business_name', 'Unknown business')}** — {intake['email']}")
                st.caption(f"Status: {intake['status']}")
                if intake["last_steps_completed"]:
                    st.markdown("Completed so far:")
                    for step in intake["last_steps_completed"]:
                        st.markdown(f"- {step}")
                if intake["last_errors"]:
                    st.markdown("Last errors:")
                    for error in intake["last_errors"]:
                        st.markdown(f"- {error}")
                if admin_client and st.button("Retry", key=f"retry_{intake['id']}"):
                    result = onboarding.retry_intake(client, admin_client, intake)
                    for step in result["steps_completed"]:
                        st.success(step)
                    for error in result["errors"]:
                        st.error(error)
                    st.rerun()
    st.divider()


def _render_onboard_customer() -> None:
    client = supabase_client.get_supabase_client()

    card_open("Onboard Customer", elevated=True)

    _render_needs_attention_section(client)

    active_modules = onboarding.list_active_modules(client)

    with st.form("onboard_customer_form"):
        with st.expander("Business & contact info", expanded=True):
            email = st.text_input("Customer email (their login invite goes here)")
            business_name = st.text_input("Business name")
            niche = st.text_input("Niche", placeholder="e.g. Real Estate Agents, or anything else")
            suggested_niches = onboarding.list_playbook_niches(client)
            if suggested_niches:
                st.caption("Niches with an existing playbook (any other text is fine — it'll use the general default):")
                st.markdown(" · ".join(f"`{n}`" for n in suggested_niches))
            goals = st.text_area("Goals")
            tone_voice = st.text_input("Tone / voice", placeholder="e.g. warm and approachable")
            posting_frequency = st.text_input("Desired posting frequency", placeholder="e.g. 3x/week")
            guardrail_sensitivity = st.selectbox("Guardrail sensitivity", GUARDRAIL_OPTIONS, index=1)
            holiday_preferences = st.multiselect("Holiday preferences", HOLIDAY_OPTIONS)
            default_voice_preference = st.selectbox("Default voiceover voice", VOICE_OPTIONS)

        with st.expander("Modules", expanded=True):
            selected_module_keys = []
            for module in active_modules:
                if st.checkbox(module["name"], key=f"module_{module['key']}"):
                    selected_module_keys.append(module["key"])
            if not active_modules:
                st.caption("No active modules in the registry.")

        with st.expander("Social platform connections", expanded=False):
            st.caption("Only used if Social is selected above.")
            platform_sources = {}
            for platform in onboarding.PLATFORMS:
                choice = st.radio(
                    platform.upper(),
                    ["Not connecting", "Existing account", "New account"],
                    key=f"platform_{platform}",
                    horizontal=True,
                )
                if choice != "Not connecting":
                    platform_sources[platform] = "existing" if choice == "Existing account" else "new"

            warm_up_period_days = st.number_input(
                "Warm-up period (days) for new accounts",
                min_value=1,
                value=DEFAULT_WARM_UP_PERIOD_DAYS,
                help="Applies to any platform queued as a New account above. Adjustable per account later in Account Connections.",
            )

        submitted = st.form_submit_button("Onboard customer")

    if not submitted:
        card_close()
        return

    if not email or not business_name:
        st.error("Email and business name are required.")
        card_close()
        return

    try:
        admin_client = supabase_client.get_supabase_admin_client()
    except RuntimeError as exc:
        st.error(str(exc))
        card_close()
        return

    payload = {
        "email": email,
        "business_name": business_name,
        "niche": niche,
        "goals": goals,
        "tone_voice": tone_voice,
        "posting_frequency": posting_frequency,
        "guardrail_sensitivity": guardrail_sensitivity,
        "holiday_preferences": holiday_preferences,
        "default_voice_preference": default_voice_preference,
        "selected_module_keys": selected_module_keys,
        "platform_sources": platform_sources if "social" in selected_module_keys else {},
        "warm_up_period_days": warm_up_period_days,
    }
    result = onboarding.provision_customer(client, admin_client, payload)

    for step in result["steps_completed"]:
        st.success(step)
    for error in result["errors"]:
        st.error(error)

    card_close()


def _social_customers(client) -> list[dict]:
    response = (
        client.table("customer_modules")
        .select("customer_id, enabled, modules!inner(key), customers(id, name)")
        .eq("modules.key", "social")
        .eq("enabled", True)
        .execute()
    )
    return [row["customers"] for row in (response.data or []) if row.get("customers")]


def _customer_niche_playbook(client, customer_id: str) -> dict | None:
    """Reads the playbook this customer is actually linked to
    (customers.niche_playbook_id, set at onboarding — see
    onboarding.resolve_playbook) rather than re-matching by niche text,
    falling back to the General default playbook the same way onboarding
    does when a customer has none. Returns None only if the library has
    no rows at all (e.g. a fresh install before any playbook exists)."""
    customer = client.table("customers").select("niche_playbook_id").eq("id", customer_id).maybe_single().execute()
    playbook_id = (customer.data or {}).get("niche_playbook_id") if customer else None
    if playbook_id:
        playbook = client.table("niche_playbooks").select("*").eq("id", playbook_id).maybe_single().execute()
        if playbook and playbook.data:
            return playbook.data
    default = client.table("niche_playbooks").select("*").eq("is_default", True).maybe_single().execute()
    return default.data if default else None


def _render_playbook_suggestions(client, customer_id: str, key_prefix: str, max_angles: int = 5) -> None:
    """§16 usability follow-up (2026-09-03): the niche playbook's content
    pillars and example angles (§4b) used to live only on the separate
    Playbooks screen — nothing surfaced them where a prompt is actually
    being written. Clicking an angle sets the same "prefill_prompt"
    session-state key Calendar's "use this idea" buttons already use, so
    the Prompt field below picks it up on rerun without any new plumbing.
    Renders nothing if the library is empty or this niche's playbook has
    no example angles yet, rather than showing an empty section."""
    playbook = _customer_niche_playbook(client, customer_id)
    if not playbook:
        return
    angles = (playbook.get("example_angles") or [])[:max_angles]
    if not angles:
        return

    niche_label = "your business (general default)" if playbook.get("is_default") else playbook.get("niche", "your business")
    with st.container():
        st.markdown(f"**Suggested ideas for {niche_label}**")
        pillars = playbook.get("content_pillars") or []
        if pillars:
            st.caption("Content pillars: " + " · ".join(pillars))
        st.caption(
            "Growth-research mix guidance: ~30% of content answering real search questions in this "
            "niche (durable TikTok/Instagram search traffic), the rest weighted toward "
            "behind-the-scenes, UGC/testimonials, and educational content."
        )
        for i, angle in enumerate(angles):
            if st.button(angle, key=f"{key_prefix}_angle_{customer_id}_{i}", use_container_width=True):
                st.session_state["prefill_prompt"] = angle
                st.rerun()
    st.divider()


def _render_generate_social() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Generate (Social)", elevated=True)

    customers = _social_customers(client)
    if not customers:
        empty_state("No customers have Social enabled yet.")
        card_close()
        return

    result = _require_active_customer_in(customers, "Social")
    if result is None:
        card_close()
        return
    customer_id, customer_name = result
    st.caption(f"Customer: **{customer_name}**")

    if "sg_blotato_templates" not in st.session_state:
        try:
            st.session_state["sg_blotato_templates"] = blotato_client.list_templates()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't load Blotato templates: {exc}")
            card_close()
            return
    templates = st.session_state["sg_blotato_templates"]
    template_by_label = {f"{t['description']} ({t['id'][-8:]})": t for t in templates}
    template_labels = list(template_by_label.keys())
    # No video template is preferred as of the 2026-08-27 retraction (see
    # blotato_client._PREFERRED_VIDEO_TEMPLATE_KEYWORDS's docstring) —
    # preferred_video_template currently just returns the first video
    # template in list order. Kept as a named call (not inlined) so a
    # real, tested preference can be reinstated in one place later.
    _preferred_video_template = blotato_client.preferred_video_template(templates)
    _default_template_index = 0
    if _preferred_video_template:
        _preferred_label = f"{_preferred_video_template['description']} ({_preferred_video_template['id'][-8:]})"
        if _preferred_label in template_labels:
            _default_template_index = template_labels.index(_preferred_label)

    social_module_id = next(m["id"] for m in _all_modules_with_ids(client) if m["key"] == "social")

    connected_accounts = _customer_connected_accounts(client, customer_id)
    caps = _customer_module_caps(client, customer_id, "social")
    posts_today = _posts_published_today(client, customer_id)
    _render_social_cap_strip(client, customer_id, caps, posts_today)

    _render_playbook_suggestions(client, customer_id, key_prefix="social")

    _PLATFORM_CHOICE_TO_KEY = {"TikTok": "tiktok", "Instagram": "instagram", "X (Twitter)": "x"}

    with st.form("generate_form"):
        # §16 growth-rules Group A6: X's 2026 algorithm favors text-first
        # posts (reportedly ~30% better than video there), and video is
        # optional on X, not mandatory the way it is on TikTok/Instagram —
        # this explicit choice is what makes that actually possible, since
        # otherwise the platform isn't known until a target account is
        # picked (still optional at this stage) or later at approval.
        platform_choice = st.selectbox(
            "Which platform is this for?",
            ["Not sure yet / general", "TikTok", "Instagram", "X (Twitter)"],
            help="Picking X switches to a simpler text-first flow with media optional, per 2026 platform research.",
        )
        intended_platform = _PLATFORM_CHOICE_TO_KEY.get(platform_choice)

        x_text = None
        attach_media = False
        template_label = None
        prompt = None
        character_description = None
        selected_template = None

        if intended_platform == "x":
            x_text = st.text_area(
                "Post text",
                value=st.session_state.pop("prefill_prompt", ""),
                placeholder="A conversation-starting take, question, or data point — this is the post itself.",
                help=growth_rules.PLATFORM_FORMAT_GUIDANCE["x"],
            )
            attach_media = st.checkbox("Also attach a video/image (optional on X)")
            if attach_media:
                template_label = st.selectbox("Template", template_labels, index=_default_template_index)
                selected_template = template_by_label[template_label]
                prompt = st.text_area("Media prompt", placeholder="Describe the video/image to generate")
        else:
            template_label = st.selectbox("Template", template_labels, index=_default_template_index)
            prompt = st.text_area(
                "Prompt", value=st.session_state.pop("prefill_prompt", ""), placeholder="Describe the content you want generated"
            )
            selected_template = template_by_label[template_label]
            if blotato_client.is_video_template(selected_template):
                st.caption(
                    "Video template selected — natural-pacing direction (candid framing, varied shot "
                    "lengths, anti-stock-feel) and growth-research direction (front-loaded hook, a "
                    f"~{growth_rules.DEFAULT_VIDEO_LENGTH_SECONDS}s length target, loop-friendly ending) "
                    "are appended to your prompt automatically."
                )
            if selected_template["id"] == blotato_client.SELFIE_CHARACTER_TEMPLATE_ID:
                customer_default_character = (
                    client.table("customers").select("default_character_description").eq("id", customer_id).maybe_single().execute()
                )
                customer_default_character = (customer_default_character.data or {}).get("default_character_description") if customer_default_character else None
                character_description = st.text_area(
                    "Character description",
                    value=customer_default_character or blotato_client.DEFAULT_SELFIE_CHARACTER_DESCRIPTION,
                    help=(
                        "Describes the synthesized on-screen presenter for this customer. Defaults to "
                        "this customer's saved character (set in Customers → Per-customer config) so "
                        "their videos show a consistent 'spokesperson' — edit here to override just this "
                        "one generation without changing the customer's saved default."
                    ),
                )

        account_by_label = {f"{a['platform'].upper()} ({a['blotato_account_id']})": a for a in connected_accounts}
        if account_by_label:
            account_label = st.selectbox("Target account (for when this gets approved and published)", list(account_by_label.keys()))
        else:
            account_label = None
            st.caption("No connected accounts for this customer yet — connect one in Account Connections before this can be published.")

        # The explicit choice above wins when set; otherwise fall back to
        # whatever platform the picked target account implies. Either way
        # this can still be None (nothing picked yet) — every use below
        # already handles that generic case.
        effective_platform = intended_platform or (account_by_label[account_label]["platform"] if account_label else None)
        hashtag_limit = growth_rules.HASHTAG_LIMITS.get(effective_platform, growth_rules.DEFAULT_HASHTAG_LIMIT)
        if effective_platform and effective_platform != "x":
            st.caption(f"**{effective_platform.upper()} format:** {growth_rules.PLATFORM_FORMAT_GUIDANCE[effective_platform]}")
        if effective_platform:
            st.caption(f"**Best time to post:** {growth_rules.POSTING_TIME_GUIDANCE[effective_platform]}")

        caption = None
        if intended_platform != "x":
            caption = st.text_area(
                "Post caption",
                placeholder="The text that will accompany the post once approved and published",
                help=(
                    "Front-load your main keyword/phrase in the first line (helps search on TikTok/Instagram). "
                    f"Max {hashtag_limit} hashtags for {effective_platform.upper() if effective_platform else 'this platform'} — "
                    "extra ones are trimmed automatically."
                ),
            )

        # Voice selection removed from this form entirely (2026-09-03 usability
        # pass) — it has failed every time it's been tested (see the
        # blotato_client.create_from_template docstring; cause still
        # unconfirmed, ticket filed with Blotato) and a permanently-broken
        # disabled control was pure noise. Reinstate once actually reliable.
        submitted = st.form_submit_button("Generate")

    if not submitted:
        pass
    elif intended_platform == "x":
        if not x_text:
            st.error("Enter your post text first.")
        elif attach_media and not prompt:
            st.error("Enter a media prompt, or uncheck \"also attach a video/image\".")
        else:
            final_text, text_trimmed = growth_rules.enforce_hashtag_limit(x_text, "x")
            if text_trimmed:
                st.info(f"Trimmed to {growth_rules.HASHTAG_LIMITS['x']} hashtags for X.")
            target_id = account_by_label[account_label]["id"] if account_label else None
            try:
                if attach_media:
                    template = selected_template
                    final_prompt = blotato_client.apply_natural_pacing_direction(prompt, template)
                    final_prompt = blotato_client.apply_growth_direction(final_prompt, template)
                    template_inputs = None
                    if template["id"] == blotato_client.SELFIE_CHARACTER_TEMPLATE_ID:
                        template_inputs = blotato_client.build_selfie_character_inputs(final_prompt, character_description)
                    generation.start_generation(
                        client,
                        customer_id=customer_id,
                        module_id=social_module_id,
                        template_id=template["id"],
                        template_description=template["description"],
                        prompt=final_prompt,
                        voice_name=None,
                        target_social_account_id=target_id,
                        post_caption=final_text,
                        inputs=template_inputs,
                    )
                else:
                    generation.start_text_only_generation(
                        client,
                        customer_id=customer_id,
                        module_id=social_module_id,
                        post_caption=final_text,
                        target_social_account_id=target_id,
                    )
                st.success("Generation queued.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Couldn't start generation: {exc}")
    elif not prompt:
        st.error("Enter a prompt first.")
    else:
        template = template_by_label[template_label]
        final_prompt = blotato_client.apply_natural_pacing_direction(prompt, template)
        final_prompt = blotato_client.apply_growth_direction(final_prompt, template)
        final_caption, caption_trimmed = growth_rules.enforce_hashtag_limit(caption, effective_platform)
        if caption_trimmed:
            st.info(
                f"Trimmed to {hashtag_limit} hashtags for "
                f"{effective_platform.upper() if effective_platform else 'this platform'} — extras were removed."
            )
        template_inputs = None
        if template["id"] == blotato_client.SELFIE_CHARACTER_TEMPLATE_ID:
            template_inputs = blotato_client.build_selfie_character_inputs(final_prompt, character_description)
        try:
            generation.start_generation(
                client,
                customer_id=customer_id,
                module_id=social_module_id,
                template_id=template["id"],
                template_description=template["description"],
                prompt=final_prompt,
                voice_name=None,
                target_social_account_id=account_by_label[account_label]["id"] if account_label else None,
                post_caption=final_caption,
                inputs=template_inputs,
            )
            st.success("Generation queued.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't start generation: {exc}")

    st.markdown("#### Generations for this customer")
    rows = (
        client.table("generations")
        .select("*")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    if not rows:
        empty_state("No generations yet for this customer.")

    for row in _visible_rows(rows, f"show_all_generate_{customer_id}"):
        with st.container():
            st.markdown(f"**{row.get('template_description') or row['template_id']}**")
            st.caption(f"Prompt: {row['prompt']}")

            if row["status"] == "processing":
                st.markdown(stamp(f"Processing ({row['blotato_status']})", "active"), unsafe_allow_html=True)
                st.markdown(progress_line(), unsafe_allow_html=True)
                if st.button("Check status", key=f"check_{row['id']}"):
                    generation.poll_generation(client, row)
                    st.rerun()
            elif row["status"] == "ready":
                st.markdown(stamp("Ready for review", "approved"), unsafe_allow_html=True)
                if row.get("media_url"):
                    st.video(row["media_url"])
                if row.get("image_urls"):
                    st.image(row["image_urls"])
                _render_guardrail_badge(row)
                if row["guardrail_status"] == "passed":
                    st.caption(f"Approval status: {row['approval_status']} — awaiting the customer's decision in their Hub.")
                if row.get("publish_status") not in ("not_published", None):
                    publish_kind = {"published": "approved", "publishing": "active", "failed": "review"}.get(row["publish_status"], "planned")
                    st.markdown(stamp(f"Publish: {row['publish_status']}", publish_kind), unsafe_allow_html=True)
                    if row["publish_status"] == "publishing":
                        st.markdown(progress_line(), unsafe_allow_html=True)
                        if st.button("Check publish status", key=f"pub_check_{row['id']}"):
                            approval.poll_publish(client, row)
                            st.rerun()
            else:
                st.markdown(stamp("Failed", "review"), unsafe_allow_html=True)

    _render_show_more_toggle(rows, f"show_all_generate_{customer_id}")

    card_close()


def _visible_rows(rows: list[dict], toggle_key: str, page_size: int = 5) -> list[dict]:
    """§16 usability pass: generation/request history used to render every
    row (with full inline video/image previews) unconditionally — fine for
    a handful of items, unreadable once a customer has dozens. Shows the
    most recent `page_size` unless the paired toggle button (see
    _render_show_more_toggle) has been clicked."""
    if st.session_state.get(toggle_key, False):
        return rows
    return rows[:page_size]


def _render_show_more_toggle(rows: list[dict], toggle_key: str, page_size: int = 5) -> None:
    if len(rows) <= page_size:
        return
    showing_all = st.session_state.get(toggle_key, False)
    label = "Show last 5" if showing_all else f"Show all ({len(rows)})"
    if st.button(label, key=f"toggle_{toggle_key}"):
        st.session_state[toggle_key] = not showing_all
        st.rerun()


def _render_social_cap_strip(client, customer_id: str, caps: dict, posts_today: int) -> None:
    """§16 usability pass: the three cap checks (posts/day, images/month,
    videos/month) used to render as three separate st.caption lines,
    then one combined caption string. §16 visual-polish pass
    (2026-09-29): now real bordered metric tiles (theme.metric_tile) in a
    row, matching how numbers are treated everywhere else in this pass —
    an over-cap tile flips to a flat warning color, never the accent glow
    (that stays reserved for active/in-progress states, not a warning)."""
    tiles = []
    over_cap = False
    if caps.get("posts_per_day") is not None:
        limit = caps["posts_per_day"]
        over = posts_today >= limit
        over_cap = over_cap or over
        tiles.append(metric_tile(f"{posts_today}/{limit}", "Posts today", warn=over))
    for media_type, cap_key, label in (("image", "media_uploads_images", "Images"), ("video", "media_uploads_videos", "Videos")):
        limit = caps.get(cap_key)
        if limit is None:
            continue
        used = _media_uploads_this_month(client, customer_id, media_type)
        over = used >= limit
        over_cap = over_cap or over
        tiles.append(metric_tile(f"{used}/{limit}", f"{label} this month", warn=over))

    if not tiles:
        return
    st.markdown(f'<div style="display:flex; flex-wrap:wrap;">{"".join(tiles)}</div>', unsafe_allow_html=True)
    if over_cap:
        st.caption("⚠ over cap — admin discretion to proceed")


def _render_guardrail_badge(generation_row: dict) -> None:
    status = generation_row.get("guardrail_status", "pending")
    if status == "pending":
        st.markdown(stamp("Guardrails: pending", "planned"), unsafe_allow_html=True)
        return
    kind = {"passed": "approved", "flagged": "review", "failed": "review"}[status]
    st.markdown(stamp(f"Guardrails: {status}", kind), unsafe_allow_html=True)
    if status != "passed" and generation_row.get("guardrail_results"):
        for category, verdict in generation_row["guardrail_results"].items():
            if isinstance(verdict, dict) and verdict.get("verdict") != "pass":
                label = guardrails.CATEGORY_LABELS.get(category, category)
                st.caption(f"⚠️ {label}: {verdict.get('note')}")


def _all_modules_with_ids(client) -> list[dict]:
    return client.table("modules").select("id, key").execute().data or []


DELIVERABLE_TYPE_LABELS = {"Flyer": "flyer", "Ad": "ad", "Standalone Video": "video"}


def _customer_module_caps(client, customer_id: str, module_key: str) -> dict:
    response = (
        client.table("customer_modules")
        .select("caps, modules!inner(key)")
        .eq("customer_id", customer_id)
        .eq("modules.key", module_key)
        .maybe_single()
        .execute()
    )
    return (response.data or {}).get("caps", {}) if response else {}


def _customer_connected_accounts(client, customer_id: str) -> list[dict]:
    response = (
        client.table("social_accounts")
        .select("id, platform, blotato_account_id")
        .eq("customer_id", customer_id)
        .not_.is_("connected_by_admin_at", "null")
        .execute()
    )
    return response.data or []


def _posts_published_today(client, customer_id: str) -> int:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    response = (
        client.table("generations")
        .select("id", count="exact")
        .eq("customer_id", customer_id)
        .eq("publish_status", "published")
        .gte("approved_at", today_start)
        .execute()
    )
    return response.count or 0


def _media_uploads_this_month(client, customer_id: str, media_type: str) -> int:
    """§7's "Media uploads (images/videos)" caps have no stated period in
    the packet (unlike posts_per_day's explicit "per day" and the design
    caps' explicit "per week") — monthly is a judgment call here, chosen
    to match the period credits.py already uses for budget tracking
    (billing_period) rather than inventing a new one. Counts only 'ready'
    generations (an in-progress or failed one hasn't actually produced any
    media yet), classified image-vs-video the same way credits.py does
    (credits.generation_type: has a media_url -> video, else image) so
    the two places that care about this distinction can't drift apart."""
    social_module_id = next((m["id"] for m in _all_modules_with_ids(client) if m["key"] == "social"), None)
    if social_module_id is None:
        return 0
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    rows = (
        client.table("generations")
        .select("media_url")
        .eq("customer_id", customer_id)
        .eq("module_id", social_module_id)
        .eq("status", "ready")
        .gte("created_at", month_start)
        .execute()
        .data
        or []
    )
    return sum(1 for row in rows if credits.generation_type(row) == media_type)


def _render_design_requests() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Design Requests", elevated=True)

    customers = design.list_design_customers(client)
    if not customers:
        empty_state("No customers have Video Design & Graphic Creator enabled yet.")
        card_close()
        return

    result = _require_active_customer_in(customers, "Video Design & Graphic Creator")
    if result is None:
        card_close()
        return
    customer_id, customer_name = result
    st.caption(f"Customer: **{customer_name}**")
    caps = _customer_module_caps(client, customer_id, "video_design_graphic_creator")

    if "sg_blotato_templates" not in st.session_state:
        try:
            st.session_state["sg_blotato_templates"] = blotato_client.list_templates()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't load Blotato templates: {exc}")
            card_close()
            return
    image_templates, video_templates = design.categorize_templates(st.session_state["sg_blotato_templates"])

    design_module_id = next(m["id"] for m in _all_modules_with_ids(client) if m["key"] == "video_design_graphic_creator")

    _render_playbook_suggestions(client, customer_id, key_prefix="design")

    with st.form("design_request_form"):
        type_label = st.radio("Deliverable type", list(DELIVERABLE_TYPE_LABELS.keys()), horizontal=True)
        deliverable_type = DELIVERABLE_TYPE_LABELS[type_label]
        occasion = st.text_input("Occasion / purpose", placeholder="e.g. Spring HVAC tune-up promotion")

        candidate_templates = video_templates if deliverable_type == "video" else image_templates
        template_by_label = {f"{t['description']} ({t['id'][-8:]})": t for t in candidate_templates}
        template_label = st.selectbox("Template", list(template_by_label.keys()))

        prompt = st.text_area(
            "Prompt", value=st.session_state.pop("prefill_prompt", ""), placeholder="Describe the flyer, ad, or video you want generated"
        )

        usage = design.check_cap_usage(client, customer_id, deliverable_type, caps)
        if usage["limit"] is not None:
            st.markdown(
                metric_tile(f"{usage['used']}/{usage['limit']}", "Cap usage this week", warn=not usage["within_cap"]),
                unsafe_allow_html=True,
            )
            if not usage["within_cap"]:
                st.caption("⚠ over cap — admin discretion to proceed")

        submitted = st.form_submit_button("Generate")

    if submitted:
        if not prompt:
            st.error("Enter a prompt first.")
        else:
            template = template_by_label[template_label]
            try:
                design.create_design_request(
                    client,
                    customer_id=customer_id,
                    module_id=design_module_id,
                    deliverable_type=deliverable_type,
                    occasion=occasion,
                    template_id=template["id"],
                    template_description=template["description"],
                    prompt=prompt,
                )
                st.success("Design request queued.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Couldn't start generation: {exc}")

    st.markdown("#### Requests for this customer")
    requests_list = design.list_design_requests(client, customer_id)
    if not requests_list:
        empty_state("No design requests yet for this customer.")

    for row in _visible_rows(requests_list, f"show_all_design_{customer_id}"):
        gen = row.get("generations") or {}
        with st.container():
            st.markdown(f"**{row['type'].upper()}** — {row.get('occasion') or 'No occasion given'}")
            st.caption(f"Template: {gen.get('template_description') or gen.get('template_id')}")

            if gen.get("status") == "processing":
                st.markdown(stamp(f"Processing ({gen.get('blotato_status')})", "active"), unsafe_allow_html=True)
                st.markdown(progress_line(), unsafe_allow_html=True)
                if st.button("Check status", key=f"design_check_{row['id']}"):
                    generation.poll_generation(client, gen)
                    st.rerun()
            elif gen.get("status") == "ready":
                st.markdown(stamp("Ready for review", "approved"), unsafe_allow_html=True)
                if gen.get("media_url"):
                    st.video(gen["media_url"])
                if gen.get("image_urls"):
                    st.image(gen["image_urls"])
                _render_guardrail_badge(gen)
                if gen.get("guardrail_status") == "passed":
                    st.caption(f"Approval status: {gen.get('approval_status')} — awaiting the customer's decision in their Hub.")
                if row["status"] == "delivered":
                    st.markdown(stamp("Delivered", "approved"), unsafe_allow_html=True)
            else:
                st.markdown(stamp("Failed", "review"), unsafe_allow_html=True)

    _render_show_more_toggle(requests_list, f"show_all_design_{customer_id}")

    card_close()


def _render_account_connections() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Account Connections", elevated=True)

    filter_customer_id = _scoped_customer_filter("account_connections")

    response = (
        client.table("social_accounts")
        .select(
            "id, customer_id, platform, source, warm_up_status, warm_up_start_date, warm_up_period_days, "
            "blotato_account_id, connected_by_admin_at, customers(name)"
        )
        .execute()
    )
    accounts = response.data or []
    if filter_customer_id:
        accounts = [a for a in accounts if a.get("customer_id") == filter_customer_id]

    pending = [a for a in accounts if not a.get("connected_by_admin_at")]
    connected = [a for a in accounts if a.get("connected_by_admin_at")]

    st.markdown("#### Waiting on manual connection")
    if not pending:
        empty_state("Nothing waiting — every queued account has been connected.")
    for account in pending:
        customer_name = (account.get("customers") or {}).get("name", "Unknown customer")
        with st.container():
            st.markdown(
                f"**{customer_name}** — {account['platform'].upper()} ({account['source']} account)"
            )
            st.caption(
                "Log into Blotato's Settings with this customer's platform credentials, "
                "connect the account, then paste the Blotato account ID here."
            )
            blotato_id = st.text_input("Blotato account ID", key=f"blotato_id_{account['id']}")
            warm_up_period_days = account["warm_up_period_days"]
            if account["source"] == "new":
                warm_up_period_days = st.number_input(
                    "Warm-up period (days)",
                    min_value=1,
                    value=account["warm_up_period_days"],
                    key=f"warmup_period_{account['id']}",
                )
            if st.button("Mark as connected", key=f"connect_{account['id']}"):
                if not blotato_id:
                    st.error("Enter the Blotato account ID first.")
                else:
                    _mark_connected(client, account, blotato_id, warm_up_period_days)
                    st.rerun()

    st.markdown("#### Warm-up tracking")
    warming = [a for a in connected if a["warm_up_status"] == "warming"]
    if not warming:
        empty_state("No accounts currently in their warm-up window.")
    for account in warming:
        customer_name = (account.get("customers") or {}).get("name", "Unknown customer")
        start = account.get("warm_up_start_date")
        period = account["warm_up_period_days"]
        days_elapsed = (date.today() - date.fromisoformat(start)).days if start else 0
        progress = min(days_elapsed / period, 1.0)
        st.markdown(f"**{customer_name}** — {account['platform'].upper()}")
        st.markdown(metric_tile(f"{days_elapsed}/{period}", "Warm-up day"), unsafe_allow_html=True)
        st.progress(progress)
        new_period = st.number_input(
            "Adjust warm-up period (days)",
            min_value=1,
            value=period,
            key=f"warmup_period_edit_{account['id']}",
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save period", key=f"save_period_{account['id']}"):
                client.table("social_accounts").update({"warm_up_period_days": new_period}).eq("id", account["id"]).execute()
                st.rerun()
        with col2:
            if st.button("Mark warm-up complete", key=f"warmup_{account['id']}"):
                client.table("social_accounts").update({"warm_up_status": "complete"}).eq("id", account["id"]).execute()
                notifications.notify(
                    client, recipient_type="admin", type_="warm_up_complete",
                    message=f"{customer_name} — {account['platform'].upper()} finished its warm-up period.",
                    customer_id=account.get("customer_id"),
                )
                st.rerun()

    card_close()


def _mark_connected(client, account: dict, blotato_id: str, warm_up_period_days: int) -> None:
    is_new = account["source"] == "new"
    update = {
        "connected_by_admin_at": datetime.now(timezone.utc).isoformat(),
        "blotato_account_id": blotato_id,
        "warm_up_status": "warming" if is_new else "not_required",
        "warm_up_period_days": warm_up_period_days,
    }
    if is_new:
        update["warm_up_start_date"] = date.today().isoformat()
    client.table("social_accounts").update(update).eq("id", account["id"]).execute()

    if account.get("blotato_pool_id"):
        pool = client.table("blotato_account_pools").select("*").eq(
            "id", account["blotato_pool_id"]
        ).maybe_single().execute()
        if pool and pool.data:
            updated_pool = (
                client.table("blotato_account_pools")
                .update({"connected_account_count": pool.data["connected_account_count"] + 1})
                .eq("id", account["blotato_pool_id"])
                .execute()
                .data[0]
            )
            credits.check_pool_cap(client, updated_pool)


def _render_ticket_inbox() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Tickets", elevated=True)

    filter_customer_id = _scoped_customer_filter("tickets")
    # Defaults to "open" (was "All") — the actionable tickets should be
    # what greets you, not buried under already-resolved ones.
    status_filter = st.selectbox("Status", ["open", "pending", "resolved", "All"])
    all_tickets = tickets.list_tickets(
        client, customer_id=filter_customer_id, status=None if status_filter == "All" else status_filter
    )
    if not all_tickets:
        empty_state("Nothing here.")

    for ticket in all_tickets:
        customer_name = (ticket.get("customers") or {}).get("name", "Unknown customer")
        kind = "review" if ticket["status"] == "open" else ("planned" if ticket["status"] == "pending" else "approved")
        with st.container():
            st.markdown(f"**{customer_name}** — {ticket['subject']}  {stamp(ticket['status'], kind)}", unsafe_allow_html=True)
            for msg in tickets.get_thread(client, ticket["id"]):
                who = "Customer" if msg["sender_role"] == "customer" else "Admin"
                st.caption(f"{who} · {msg['created_at']}")
                st.markdown(msg["body"])

            if ticket["status"] != "resolved":
                reply_body = st.text_area("Reply", key=f"admin_reply_{ticket['id']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Send reply", key=f"admin_send_{ticket['id']}"):
                        if reply_body:
                            user = auth.current_user()
                            tickets.reply(client, ticket["id"], "admin", user.id, reply_body, ticket["customer_id"])
                            st.rerun()
                with col2:
                    if st.button("Mark resolved", key=f"admin_resolve_{ticket['id']}"):
                        tickets.resolve_ticket(client, ticket["id"])
                        st.rerun()

    card_close()


def _render_escalations() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Escalations", elevated=True)

    filter_customer_id = _scoped_customer_filter("escalations")
    open_escalations = guardrails.list_open_escalations(client)
    if filter_customer_id:
        open_escalations = [e for e in open_escalations if e.get("customer_id") == filter_customer_id]
    if not open_escalations:
        empty_state("Nothing escalated — every guardrail flag either passed on retry or hasn't exhausted retries yet.")
        card_close()
        return

    for esc in open_escalations:
        gen = esc.get("generations") or {}
        customer_name = (esc.get("customers") or {}).get("name", "Unknown customer")
        with st.container():
            st.markdown(f"**{customer_name}** — {gen.get('template_description') or gen.get('template_id')}")
            st.caption(f"Reason: {esc['reason']}" + (f" — {esc['category']}" if esc.get("category") else ""))
            st.caption(f"Escalated: {esc['created_at']}")

            details = esc.get("details") or {}
            for category, verdict in details.items():
                if isinstance(verdict, dict):
                    label = guardrails.CATEGORY_LABELS.get(category, category)
                    st.markdown(f"- **{label}**: {verdict.get('verdict')} — {verdict.get('note')}")
                else:
                    st.markdown(f"- {category}: {verdict}")

            if gen.get("media_url"):
                st.video(gen["media_url"])
            if gen.get("image_urls"):
                st.image(gen["image_urls"])

            # §16 target-account-picker follow-up (2026-09-06): the exact
            # fix for the "approved but no target account" escalation this
            # crash used to produce — sets the account and republishes
            # through the real _publish() path, same as any other publish,
            # instead of leaving this stuck forever with no way to resolve
            # it except a blind "Mark resolved."
            if esc["reason"] == "publish" and not gen.get("target_social_account_id"):
                accounts = approval.list_connectable_accounts(client, esc["customer_id"])
                if accounts:
                    account_by_label = {
                        f"{a['platform'].upper()} ({a['blotato_account_id']})": a["id"] for a in accounts
                    }
                    account_label = st.selectbox(
                        "Post to", list(account_by_label.keys()), key=f"esc_target_account_{esc['id']}"
                    )
                    if st.button("Set target account & retry", key=f"esc_set_target_{esc['id']}"):
                        approval.set_target_account_and_retry_publish(
                            client, gen, account_by_label[account_label], esc["id"]
                        )
                        st.success("Target account set — retrying publish.")
                        st.rerun()
                else:
                    st.caption("This customer still has no connected account — connect one in Account Connections first.")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Retry anyway", key=f"esc_retry_{esc['id']}"):
                    guardrails.retry_escalated_generation(client, gen)
                    st.success("Retrying — check back on Generate (Social) / Design Requests for status.")
                    st.rerun()
            with col2:
                resolution_note = st.text_input("Resolution note", key=f"esc_note_{esc['id']}")
                if st.button("Mark resolved", key=f"esc_resolve_{esc['id']}"):
                    guardrails.resolve_escalation(client, esc["id"], resolution_note)
                    st.rerun()

    card_close()


def _published_generations(client, customer_id: str) -> list[dict]:
    return (
        client.table("generations")
        .select("*")
        .eq("customer_id", customer_id)
        .eq("publish_status", "published")
        .order("approved_at", desc=True)
        .execute()
        .data
        or []
    )


def _render_analytics() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Analytics", elevated=True)

    customers = _social_customers(client)
    if not customers:
        empty_state("No customers have Social enabled yet.")
        card_close()
        return

    result = _require_active_customer_in(customers, "Social")
    if result is None:
        card_close()
        return
    customer_id, customer_name = result
    st.caption(f"Customer: **{customer_name}**")

    st.markdown("#### Published posts")
    published = _published_generations(client, customer_id)
    if not published:
        empty_state("No published posts for this customer yet.")
    for row in published:
        account = (
            client.table("social_accounts").select("platform").eq("id", row.get("target_social_account_id")).maybe_single().execute()
            if row.get("target_social_account_id")
            else None
        )
        platform = (account.data or {}).get("platform") if account else "unknown"
        with st.container():
            st.markdown(f"**{row.get('template_description') or row['template_id']}** — {platform.upper() if platform else ''}")
            if row.get("post_url"):
                st.caption(f"[{row['post_url']}]({row['post_url']})")

            if platform == "tiktok":
                st.caption("No analytics API for TikTok in some cases — log metrics manually below (§5a).")
                with st.form(f"manual_metrics_{row['id']}"):
                    views = st.number_input("Views", min_value=0, step=1, key=f"mv_{row['id']}")
                    likes = st.number_input("Likes", min_value=0, step=1, key=f"ml_{row['id']}")
                    comments = st.number_input("Comments", min_value=0, step=1, key=f"mc_{row['id']}")
                    shares = st.number_input("Shares", min_value=0, step=1, key=f"ms_{row['id']}")
                    if st.form_submit_button("Log metrics"):
                        analytics.log_manual_metrics(
                            client, row, entered_by=auth.current_user().id,
                            views=views, likes=likes, comments=comments, shares=shares,
                        )
                        st.success("Logged.")
                        st.rerun()
            else:
                if st.button("Pull analytics", key=f"pull_{row['id']}"):
                    snapshot = analytics.pull_api_analytics(client, row)
                    if snapshot:
                        st.success(f"Pulled: {snapshot['views']} views, {snapshot['likes']} likes, {snapshot['comments']} comments, {snapshot['shares']} shares.")
                    else:
                        st.info("Not synced yet — Blotato analytics can take up to 24h after publish.")

    st.markdown("#### Top performers (this customer)")
    top = analytics.top_performers(client, limit=5)
    top = [t for t in top if t["generation"]["customer_id"] == customer_id]
    if not top:
        empty_state("No analytics data yet to rank.")
    for row in top:
        gen = row["generation"]
        st.markdown('<div class="sg-subcard">', unsafe_allow_html=True)
        st.markdown(f"**{gen.get('template_description') or gen.get('template_id')}**  ·  _{row['source']}_")
        tiles = "".join(
            [
                metric_tile(str(row.get("likes") or 0), "Likes"),
                metric_tile(str(row.get("comments") or 0), "Comments"),
                metric_tile(str(row.get("shares") or 0), "Shares"),
            ]
        )
        st.markdown(f'<div style="display:flex; flex-wrap:wrap;">{tiles}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    card_close()


def _render_optimizer() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Content Suggestions", elevated=True)

    # The "check" trigger below is single-customer (needs one target to
    # run a real baseline check against) so it uses the Active Customer —
    # but "Pending suggestions" itself has always been a cross-customer
    # queue (every row already shows which customer it's for), so unlike
    # Generate/Design/Analytics it is NOT gated behind an Active Customer
    # selection; it stays visible regardless.
    social_customers = _social_customers(client)
    active = _active_customer()
    if active and any(c["id"] == active[0] for c in social_customers):
        customer_id, customer_name = active
        st.caption(f"Checking underperformance for: **{customer_name}**")
        if st.button("Check for underperformance"):
            new_suggestions = optimizer.generate_suggestions(client, customer_id)
            if new_suggestions:
                st.success(f"{len(new_suggestions)} new suggestion(s).")
            else:
                st.info("Nothing to suggest right now — either performance looks fine, or there isn't enough data yet for a baseline.")
            st.rerun()
    elif active:
        st.caption(f"{active[1]} doesn't have Social enabled — pick a different Active Customer in the sidebar to check for underperformance.")
    elif social_customers:
        st.caption("Pick an Active Customer in the sidebar to check for underperformance for a specific customer.")

    st.markdown("#### Pending suggestions")
    pending = optimizer.list_pending_suggestions(client)
    if not pending:
        empty_state("No pending suggestions.")
    for s in pending:
        customer_name = (s.get("customers") or {}).get("name", "Unknown customer")
        with st.container():
            st.markdown(f"**{customer_name}** — {s['platform'].upper()}")
            st.caption(f"Trigger: {s['trigger_metric']}")
            st.markdown(s["proposed_change"])
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Approve", key=f"opt_approve_{s['id']}"):
                    optimizer.resolve_suggestion(client, s["id"], "approved")
                    st.rerun()
            with col2:
                if st.button("Dismiss", key=f"opt_dismiss_{s['id']}"):
                    optimizer.resolve_suggestion(client, s["id"], "dismissed")
                    st.rerun()

    card_close()


def _render_playbooks() -> None:
    """Playbooks (§4b, §12, §16 step 32): browse/add/edit
    playbook content directly, with the Phase 7 refinement-data section
    (top performers, mark-refined) as an additional part of the same
    screen — not gating it. It used to return early with nothing shown at
    all when a niche had zero performance data yet, which is the common
    case for most niches right now; fixed here."""
    client = supabase_client.get_supabase_client()
    card_open("Playbooks", elevated=True)

    with st.expander("Universal growth principles (2026 research)"):
        st.caption(
            "Applies to every niche — not stored per-playbook since it's the same "
            "regardless of niche (see app/lib/growth_rules.py)."
        )
        st.markdown(f"**Core principle:** {growth_rules.UNIVERSAL_PRINCIPLES}")
        st.markdown(f"**Growth timeline:** {growth_rules.GROWTH_TIMELINE_EXPECTATION}")
        st.markdown("**Format by platform/goal:**")
        for platform, guidance in growth_rules.PLATFORM_FORMAT_GUIDANCE.items():
            st.markdown(f"- **{platform.upper()}:** {guidance}")

    with st.expander("Add a new niche playbook"):
        with st.form("new_playbook_form"):
            new_niche = st.text_input("Niche name")
            new_pillars = st.text_area("Content pillars (one per line)")
            new_practices = st.text_area("Best practices")
            new_cadence = st.text_input("Posting cadence guidance")
            new_angles = st.text_area("Example angles (one per line)")
            if st.form_submit_button("Create"):
                if not new_niche:
                    st.error("Enter a niche name first.")
                else:
                    client.table("niche_playbooks").insert(
                        {
                            "niche": new_niche,
                            "content_pillars": [p.strip() for p in new_pillars.splitlines() if p.strip()],
                            "best_practices": new_practices,
                            "posting_cadence_guidance": new_cadence,
                            "example_angles": [a.strip() for a in new_angles.splitlines() if a.strip()],
                        }
                    ).execute()
                    st.success(f"Created '{new_niche}'.")
                    st.rerun()

    niches = (
        client.table("niche_playbooks")
        .select("id, niche")
        .eq("is_default", False)
        .order("niche")
        .execute()
        .data
        or []
    )
    if not niches:
        empty_state("No niche playbooks yet — add one above.")
        card_close()
        return

    niche_by_name = {n["niche"]: n["id"] for n in niches}
    selected_niche = st.selectbox("Niche", list(niche_by_name.keys()))
    playbook = client.table("niche_playbooks").select("*").eq("id", niche_by_name[selected_niche]).maybe_single().execute().data

    research_flag = "Refined from data" if playbook.get("refined_from_data") else "Initial research only"
    st.markdown(f"{stamp(research_flag, 'approved' if playbook.get('refined_from_data') else 'planned')}  ·  v{playbook.get('version', 1)}", unsafe_allow_html=True)

    with st.form(f"edit_playbook_{playbook['id']}"):
        edited_pillars = st.text_area("Content pillars (one per line)", value="\n".join(playbook.get("content_pillars") or []))
        edited_practices = st.text_area("Best practices", value=playbook.get("best_practices") or "")
        edited_cadence = st.text_input("Posting cadence guidance", value=playbook.get("posting_cadence_guidance") or "")
        edited_angles = st.text_area("Example angles (one per line)", value="\n".join(playbook.get("example_angles") or []))
        if st.form_submit_button("Save changes"):
            client.table("niche_playbooks").update(
                {
                    "content_pillars": [p.strip() for p in edited_pillars.splitlines() if p.strip()],
                    "best_practices": edited_practices,
                    "posting_cadence_guidance": edited_cadence,
                    "example_angles": [a.strip() for a in edited_angles.splitlines() if a.strip()],
                }
            ).eq("id", playbook["id"]).execute()
            st.success("Saved.")
            st.rerun()

    st.markdown("#### Performance data for this niche")
    summary = playbook_refinement.performance_summary_for_niche(client, selected_niche)
    st.caption(f"Sample size: {summary['sample_size']} tracked post(s) with analytics in this niche.")

    if summary["sample_size"] == 0:
        empty_state("No performance data yet for this niche — nothing to refine from until posts have analytics.")
    else:
        st.markdown("**What's working**")
        for template_desc, count in summary["template_frequency"]:
            st.markdown(f"- {template_desc} — appears {count}x in the top performers")

        st.markdown("**Top performing posts**")
        for row in summary["top_performers"]:
            gen = row["generation"]
            st.markdown(
                f"- {gen.get('template_description') or gen.get('template_id')}: "
                f"{row.get('likes') or 0} likes, {row.get('comments') or 0} comments, {row.get('shares') or 0} shares"
            )

        note = st.text_area("What did the data show? (appended to best_practices, nothing overwritten)", key="refine_note")
        if st.button("Mark refined from data"):
            playbook_refinement.mark_refined(client, playbook["id"], note or None)
            st.success("Playbook updated.")
            st.rerun()

    card_close()


_EVENT_STAMP_KIND = {"post": "approved", "deliverable": "approved", "holiday": "planned"}


def _render_calendar() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Calendar", elevated=True)
    st.caption("Cross-customer view of scheduled/published posts, deliverables, and holidays.")

    with st.expander("Best times to post (2026 research)"):
        st.caption(
            "Advisory only — this product publishes immediately on customer approval, there's no "
            "\"schedule for later\" feature, so use this as guidance for when to approve/publish, "
            "not an automatic scheduler."
        )
        for platform, guidance in growth_rules.POSTING_TIME_GUIDANCE.items():
            st.markdown(f"- **{platform.upper()}:** {guidance}")

    customers = _all_customers()
    customer_by_name = {c["name"]: c["id"] for c in customers}

    # Defaults from the sidebar Active Customer (no auto-navigation, just
    # a default) — re-applies whenever the Active Customer actually
    # changes, but a manual override made here persists until it does,
    # same "changed since last run" pattern used for admin_nav_item.
    active = _active_customer()
    active_name = active[1] if active else "All customers"
    if st.session_state.get("calendar_scope_last_active") != active_name:
        st.session_state["calendar_scope"] = active_name
        st.session_state["calendar_scope_last_active"] = active_name

    scope = st.selectbox("Customer", ["All customers"] + list(customer_by_name.keys()), key="calendar_scope")
    scoped_customer_id = None if scope == "All customers" else customer_by_name[scope]

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("From", value=date.today().replace(day=1))
    with col2:
        end = st.date_input("To", value=date.today() + timedelta(days=30))

    events = calendar_module.admin_calendar(client, start, end, customer_id=scoped_customer_id)
    if not events:
        empty_state("Nothing in this range.")

    for event in events:
        with st.container():
            label = f"{event['date'].isoformat()} — **{event['title']}**"
            if event.get("customer_name"):
                label += f" ({event['customer_name']})"
            st.markdown(f"{label}  {stamp(event['type'], _EVENT_STAMP_KIND[event['type']])}", unsafe_allow_html=True)
            if event["type"] == "post" and event.get("post_url"):
                st.caption(f"[{event['post_url']}]({event['post_url']})")
            if event["type"] == "holiday" and event.get("content_idea_prompt"):
                st.caption(event["content_idea_prompt"])
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("Use idea for Social", key=f"idea_social_{event['title']}_{event['date']}"):
                        st.session_state["prefill_prompt"] = event["content_idea_prompt"]
                        # Can't set st.session_state["admin_nav"] directly here — the
                        # "admin_nav"-keyed radio has already been instantiated earlier
                        # in this same run, and Streamlit forbids mutating a widget's
                        # own key post-instantiation. Stash it and apply at the top of
                        # render(), before the radio is created on the next run.
                        st.session_state["pending_nav"] = "Generate (Social)"
                        st.rerun()
                with col_b:
                    if st.button("Use idea for Design", key=f"idea_design_{event['title']}_{event['date']}"):
                        st.session_state["prefill_prompt"] = event["content_idea_prompt"]
                        st.session_state["pending_nav"] = "Design Requests"
                        st.rerun()

    card_close()


def _render_notifications() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Notifications", elevated=True)

    filter_customer_id = _scoped_customer_filter("notifications")
    unread_only = st.checkbox("Unread only", value=True)
    items = notifications.list_notifications(
        client, recipient_type="admin", customer_id=filter_customer_id, unread_only=unread_only
    )
    if not items:
        empty_state("Nothing here.")

    for n in items:
        with st.container():
            kind = "review" if n["type"] in notifications.TIME_SENSITIVE_TYPES else "planned"
            read_label = "" if n["read_status"] else " — unread"
            st.markdown(f"{stamp(n['type'], kind)}{read_label}", unsafe_allow_html=True)
            st.markdown(n["message"])
            st.caption(f"{n['created_at']} · email: {n['email_status']}")
            if not n["read_status"] and st.button("Mark read", key=f"read_{n['id']}"):
                notifications.mark_read(client, n["id"])
                st.rerun()

    card_close()


def _render_credit_tracker() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Credit & Cost Tracker", elevated=True)
    st.caption(
        "Real per-template costs, learned automatically the first time each template is used "
        "(see app/lib/credits.py) — a template not yet used anywhere falls back to a flagged "
        "conservative estimate until it is."
    )

    filter_customer_id = _scoped_customer_filter("credit_tracker")
    customers = _all_customers()
    if filter_customer_id:
        customers = [c for c in customers if c["id"] == filter_customer_id]
    if not customers:
        empty_state("No customers yet.")
        card_close()
        return

    for c in customers:
        used = credits.usage_this_period(client, c["id"])
        customer_row = client.table("customers").select("credit_budget").eq("id", c["id"]).maybe_single().execute()
        budget = (customer_row.data or {}).get("credit_budget") if customer_row else None
        st.markdown('<div class="sg-subcard">', unsafe_allow_html=True)
        st.markdown(f"**{c['name']}**")
        if budget:
            over = used >= budget
            st.markdown(
                metric_tile(f"{used:.0f}/{budget:.0f}", f"Est. credits this period ({used/budget:.0%})", warn=over),
                unsafe_allow_html=True,
            )
            st.progress(min(used / budget, 1.0))
        else:
            st.markdown(metric_tile(f"{used:.0f}", "Est. credits this period (no budget set)"), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    card_close()


def _render_pool_status() -> None:
    client = supabase_client.get_supabase_client()
    card_open("Account Pool Capacity", elevated=True)

    pools = client.table("blotato_account_pools").select("*").execute().data or []
    if not pools:
        empty_state("No pools configured.")
    for pool in pools:
        st.markdown('<div class="sg-subcard">', unsafe_allow_html=True)
        st.markdown(f"**{pool['plan_tier'].title()} pool**")
        near_cap = pool["connected_account_count"] >= pool["cap"] * credits.POOL_CAP_THRESHOLD_FRACTION
        tiles = [metric_tile(f"{pool['connected_account_count']}/{pool['cap']}", "Connections", warn=near_cap)]
        if pool.get("tiktok_daily_cap"):
            tiles.append(metric_tile(f"{pool['tiktok_posts_used_today']}/{pool['tiktok_daily_cap']}", "TikTok posts today"))
        if pool.get("monthly_cost"):
            tiles.append(metric_tile(f"${pool['monthly_cost']}", "Monthly cost"))
        st.markdown(f'<div style="display:flex; flex-wrap:wrap;">{"".join(tiles)}</div>', unsafe_allow_html=True)
        st.progress(min(pool["connected_account_count"] / pool["cap"], 1.0))
        st.markdown("</div>", unsafe_allow_html=True)

    card_close()


def _render_customer_overview() -> None:
    """§16 Active Customer follow-up: one screen answering "what's going
    on with this customer right now" without navigating across five
    different screens to piece it together — pending approvals, open
    tickets, recent generations, cap usage, and what's coming up, all
    read from functions that already exist elsewhere in this file/module."""
    client = supabase_client.get_supabase_client()
    card_open("Customer Overview", elevated=True)

    active = _active_customer()
    if active is None:
        empty_state("Pick an Active Customer in the sidebar to see their overview.")
        card_close()
        return
    customer_id, customer_name = active
    st.markdown(f"### {customer_name}")

    pending_approvals = approval.list_pending_approvals(client, customer_id)
    customer_tickets = tickets.list_tickets(client, customer_id=customer_id)
    open_tickets = [t for t in customer_tickets if t["status"] != "resolved"]
    recent_generations = (
        client.table("generations")
        .select("*")
        .eq("customer_id", customer_id)
        .order("created_at", desc=True)
        .limit(5)
        .execute()
        .data
        or []
    )
    upcoming_events = calendar_module.admin_calendar(
        client, date.today(), date.today() + timedelta(days=14), customer_id=customer_id
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Pending approvals", len(pending_approvals))
    with col2:
        st.metric("Open tickets", len(open_tickets))
    with col3:
        st.metric("Upcoming (14 days)", len(upcoming_events))

    st.markdown("#### Cap usage this period")
    social_caps = _customer_module_caps(client, customer_id, "social")
    posts_today = _posts_published_today(client, customer_id)
    _render_social_cap_strip(client, customer_id, social_caps, posts_today)

    st.markdown("#### Recent generations")
    if not recent_generations:
        empty_state("No generations yet for this customer.")
    for row in recent_generations:
        kind = {"ready": "approved", "processing": "active", "failed": "review"}.get(row["status"], "planned")
        st.markdown(
            f"{stamp(row['status'], kind)} {row.get('template_description') or row['template_id']}",
            unsafe_allow_html=True,
        )

    st.markdown("#### Upcoming (next 14 days)")
    if not upcoming_events:
        empty_state("Nothing scheduled in the next 14 days.")
    for event in upcoming_events:
        st.markdown(f"- {event['date'].isoformat()} — {event['title']}")

    card_close()


def _format_nav_item(label: str, intake_count: int) -> str:
    if label == "Onboard Customer" and intake_count:
        return f"{label} ({intake_count})"
    return label


def render() -> None:
    st.markdown("## Admin")
    client = supabase_client.get_supabase_client()

    if "pending_nav" in st.session_state:
        # A jump requested from elsewhere (e.g. Calendar's "use this idea"
        # buttons) — resolve the target item's group too, and mark the
        # group as already-current so the group-change handling below
        # doesn't reset admin_nav_item back to that group's first item.
        target_item = st.session_state.pop("pending_nav")
        target_group = _ITEM_TO_GROUP[target_item]
        st.session_state["admin_nav_group"] = target_group
        st.session_state["admin_nav_item"] = target_item
        st.session_state["admin_nav_last_group"] = target_group

    intake_count = _incomplete_intake_count(client)

    with st.sidebar:
        _render_active_customer_switcher()

        unread = notifications.unread_count(client, recipient_type="admin")
        if unread:
            st.caption(f"🔔 {unread} unread notification(s)")

        group = st.radio("Section", list(NAV_GROUPS), key="admin_nav_group")

        # Switching groups (an explicit sidebar click, not a pending_nav
        # jump, which already set admin_nav_last_group to match above) —
        # land on that group's first item rather than keeping the
        # previous group's selection, which wouldn't be a valid option here.
        if st.session_state.get("admin_nav_last_group") != group:
            st.session_state["admin_nav_item"] = NAV_GROUPS[group][0]
            st.session_state["admin_nav_last_group"] = group

        selection = st.radio(
            "Screen",
            NAV_GROUPS[group],
            key="admin_nav_item",
            format_func=lambda label: _format_nav_item(label, intake_count),
        )

    if selection == "Customer Overview":
        _render_customer_overview()
    elif selection == "Customers":
        _render_customers()
    elif selection == "Onboard Customer":
        _render_onboard_customer()
    elif selection == "Account Connections":
        _render_account_connections()
    elif selection == "Generate (Social)":
        _render_generate_social()
    elif selection == "Design Requests":
        _render_design_requests()
    elif selection == "Analytics":
        _render_analytics()
    elif selection == "Content Suggestions":
        _render_optimizer()
    elif selection == "Notifications":
        _render_notifications()
    elif selection == "Credit & Cost Tracker":
        _render_credit_tracker()
    elif selection == "Account Pool Capacity":
        _render_pool_status()
    elif selection == "Tickets":
        _render_ticket_inbox()
    elif selection == "Escalations":
        _render_escalations()
    elif selection == "Calendar":
        _render_calendar()
    elif selection == "Module Map":
        _render_module_map()
    elif selection == "Playbooks":
        _render_playbooks()
    else:
        card_open(selection)
        empty_state(f"{selection} isn't built yet — this arrives in a later phase.")
        card_close()
