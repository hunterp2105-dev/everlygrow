import re
from datetime import date, timedelta

import streamlit as st

from app.lib import approval, auth, content_ideas, intake, notifications, supabase_client, tickets
from app.lib import calendar as calendar_module
from app.lib.theme import card_close, card_open, empty_state, metric_tile, progress_line, stamp

_PLATFORM_LABELS = {"tiktok": "TikTok", "instagram": "Instagram", "x": "X (Twitter)"}
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# "Requests" and "Tickets" were two separate nav items pointing at the same
# underlying feature (§11.2 calls it "requests"; §16 step 30 calls the admin
# side a "ticket inbox" — same tickets/ticket_messages tables either way).
# Consolidated to one real screen under "Requests" rather than building the
# same thing twice under two labels.
NAV_ITEMS = ["Requests", "Calendar", "Media Library", "Approval Queue", "Notifications"]

_EVENT_STAMP_KIND = {"post": "approved", "deliverable": "approved", "holiday": "planned"}


def _active_modules(customer_id: str) -> list[dict]:
    client = supabase_client.get_supabase_client()
    response = (
        client.table("customer_modules")
        .select("enabled, modules(key, name, status)")
        .eq("customer_id", customer_id)
        .eq("enabled", True)
        .execute()
    )
    return [row["modules"] for row in (response.data or []) if row.get("modules")]


def _render_home(customer_id: str) -> None:
    """§16 visual-polish pass (2026-09-29): the customer's landing view —
    given the elevated treatment (see theme.card_open's docstring) since
    it's the first thing a customer sees on this screen. Each module gets
    its own bordered tile instead of bare markdown + a badge floating in
    a column, so the row reads as distinct cards, not a loose list."""
    modules = _active_modules(customer_id)

    card_open("Active modules", elevated=True)
    if modules:
        cols = st.columns(len(modules))
        for col, module in zip(cols, modules):
            with col:
                st.markdown(
                    f'<div class="sg-subcard" style="text-align:center; margin-bottom:0;">'
                    f'<div style="font-family:var(--font-display); font-weight:600; margin-bottom:8px;">{module["name"]}</div>'
                    f'{stamp("Active", "approved")}'
                    f"</div>",
                    unsafe_allow_html=True,
                )
    else:
        empty_state(
            "No modules are active on your account yet — your admin will get "
            "this set up during onboarding."
        )
    card_close()


def _render_content_idea_suggestions(privileged_client, customer_id: str) -> None:
    """§16 admin follow-up (2026-09-29): the customer-side mirror of
    admin's playbook suggestions — real, tailored ideas so a request
    starts from something concrete instead of a blank box. Uses the
    privileged client throughout (see content_ideas.py's module
    docstring — same privilege pattern as approval.py/intake.py); silent
    on failure (a caption, not a crash) so a Claude hiccup never blocks
    the actual request form below it."""
    try:
        ideas = content_ideas.get_or_refresh_ideas(privileged_client, customer_id)
    except Exception as exc:  # noqa: BLE001
        st.caption(f"Couldn't load content ideas right now: {exc}")
        return
    if not ideas:
        return

    st.markdown("#### Suggested ideas for your business")
    st.caption("Click an idea to start a request with it pre-filled — edit anything before sending.")
    for idea in ideas:
        category_label = content_ideas.CATEGORY_LABELS.get(idea["category"], idea["category"])
        if st.button(f"[{category_label}] {idea['title']}", key=f"idea_{idea['id']}", use_container_width=True):
            st.session_state["prefill_ticket_subject"] = idea["title"]
            st.session_state["prefill_ticket_message"] = idea["detail"]
            content_ideas.mark_used(privileged_client, idea["id"])
            st.rerun()
    st.divider()


def _render_requests(customer_id: str) -> None:
    client = supabase_client.get_supabase_client()
    privileged_client = supabase_client.get_supabase_admin_client()
    card_open("Requests", elevated=True)

    _render_content_idea_suggestions(privileged_client, customer_id)

    with st.form("new_ticket_form"):
        subject = st.text_input("Subject", value=st.session_state.pop("prefill_ticket_subject", ""))
        message = st.text_area("Message", value=st.session_state.pop("prefill_ticket_message", ""))
        if st.form_submit_button("Send"):
            if not subject or not message:
                st.error("Enter a subject and message first.")
            else:
                tickets.create_ticket(client, customer_id, subject, message, sender_id=auth.current_user().id)
                st.success("Sent to your admin.")
                st.rerun()

    st.markdown("#### Your requests")
    your_tickets = tickets.list_tickets(client, customer_id=customer_id)
    if not your_tickets:
        empty_state("Nothing here yet — send your first request above to get started.")

    for ticket in your_tickets:
        with st.container():
            st.markdown(f"**{ticket['subject']}**  {stamp(ticket['status'], 'approved' if ticket['status'] == 'resolved' else 'planned')}", unsafe_allow_html=True)
            for msg in tickets.get_thread(client, ticket["id"]):
                who = "You" if msg["sender_role"] == "customer" else "Admin"
                st.caption(f"{who} · {msg['created_at']}")
                st.markdown(msg["body"])

            if ticket["status"] != "resolved":
                reply_body = st.text_area("Reply", key=f"reply_{ticket['id']}")
                if st.button("Send reply", key=f"send_reply_{ticket['id']}"):
                    if reply_body:
                        tickets.reply(client, ticket["id"], "customer", auth.current_user().id, reply_body, customer_id)
                        st.rerun()

    card_close()


def _render_approval_queue(customer_id: str) -> None:
    # Reads use the customer's own session (already RLS-scoped to their own
    # rows). Approve/request-changes write fields a customer session can't
    # under RLS (publish tracking, escalations, notifications are
    # admin-only) — those go through the service-role client instead, with
    # approval.py verifying `customer_id` against the generation's actual
    # owner before touching anything. See app/lib/approval.py's docstring.
    client = supabase_client.get_supabase_client()
    privileged_client = supabase_client.get_supabase_admin_client()
    card_open("Approval Queue", elevated=True)

    pending = approval.list_pending_approvals(client, customer_id)
    if not pending:
        empty_state("Nothing waiting on your review right now.")
        card_close()
        return

    for row in pending:
        module_key = (row.get("modules") or {}).get("key")
        kind = "post" if module_key == "social" else "design deliverable"
        with st.container():
            st.markdown(f"**{row.get('template_description') or 'Content'}** — ready to review as a {kind}")
            if row.get("post_caption"):
                st.caption(f"Caption: {row['post_caption']}")
            if row.get("media_url"):
                st.video(row["media_url"])
            if row.get("image_urls"):
                st.image(row["image_urls"])

            # §16 target-account-picker (2026-09-06): a "post" with no
            # target account set at generation time used to only surface
            # as a stuck admin escalation after approval, with no way for
            # the customer to just pick one here. Only shown when there's
            # actually a choice to make — nothing to pick if none is
            # connected yet (approve still proceeds; admin's escalation
            # path catches that case), and no picker needed at all if
            # admin already set one on the Generate screen.
            target_account_id = None
            if module_key == "social" and not row.get("target_social_account_id"):
                accounts = approval.list_connectable_accounts(client, customer_id)
                if accounts:
                    account_by_label = {
                        f"{a['platform'].upper()} ({a['blotato_account_id']})": a["id"] for a in accounts
                    }
                    account_label = st.selectbox(
                        "Post to",
                        list(account_by_label.keys()),
                        key=f"target_account_{row['id']}",
                    )
                    target_account_id = account_by_label[account_label]
                else:
                    st.caption(
                        "No connected account yet — approving will notify your admin to connect "
                        "one before this can go out."
                    )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Approve", key=f"approve_{row['id']}", use_container_width=True):
                    user = auth.current_user()
                    approval.approve_generation(
                        privileged_client, row, approved_by_user_id=user.id, customer_id=customer_id,
                        target_social_account_id=target_account_id,
                    )
                    st.success("Approved.")
                    st.rerun()
            with col2:
                feedback = st.text_input("Request changes (optional note)", key=f"feedback_{row['id']}")
                if st.button("Request changes", key=f"changes_{row['id']}", use_container_width=True):
                    approval.request_changes(privileged_client, row["id"], feedback, customer_id)
                    st.success("Sent to your admin.")
                    st.rerun()

    card_close()


def _render_calendar(customer_id: str) -> None:
    client = supabase_client.get_supabase_client()
    card_open("Calendar", elevated=True)

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("From", value=date.today().replace(day=1))
    with col2:
        end = st.date_input("To", value=date.today() + timedelta(days=30))

    events = calendar_module.customer_calendar(client, customer_id, start, end)
    if not events:
        empty_state("Nothing on your calendar in this range.")

    for event in events:
        with st.container():
            st.markdown(
                f"{event['date'].isoformat()} — **{event['title']}**  "
                f"{stamp(event['type'], _EVENT_STAMP_KIND[event['type']])}",
                unsafe_allow_html=True,
            )
            if event["type"] == "post" and event.get("post_url"):
                st.caption(f"[{event['post_url']}]({event['post_url']})")
            if event["type"] == "holiday" and event.get("content_idea_prompt"):
                st.caption(f"Idea: {event['content_idea_prompt']}")

    card_close()


def _render_notifications(customer_id: str) -> None:
    client = supabase_client.get_supabase_client()
    card_open("Notifications", elevated=True)

    unread_only = st.checkbox("Unread only", value=True)
    items = notifications.list_notifications(client, recipient_type="customer", customer_id=customer_id, unread_only=unread_only)
    if not items:
        empty_state("Nothing here.")

    for n in items:
        with st.container():
            read_label = "" if n["read_status"] else " — unread"
            st.markdown(f"{stamp(n['type'], 'planned')}{read_label}", unsafe_allow_html=True)
            st.markdown(n["message"])
            st.caption(n["created_at"])
            if not n["read_status"] and st.button("Mark read", key=f"cust_read_{n['id']}"):
                notifications.mark_read(client, n["id"])
                st.rerun()

    card_close()


def _render_intake_form(customer_id: str) -> None:
    """§16 Client Intake Questionnaire (2026-09-10): a customer's first
    login shows this instead of the normal Hub — see needs_intake() in
    render() below. No sidebar nav while this is showing; it's a hard
    gate, not a dismissible banner, and there's nothing to navigate to
    yet anyway until this is submitted."""
    privileged_client = supabase_client.get_supabase_admin_client()

    st.markdown("## Welcome — a few quick questions")
    st.caption(
        "A few quick questions so we can set up your social media management. "
        "Takes about 5 minutes. You'll only need to do this once — we'll follow "
        "up separately for anything else."
    )

    with st.form("intake_form"):
        st.markdown("#### About your business")
        business_name = st.text_input("Business name")
        industry = st.text_input(
            "What industry/type of business are you?",
            help="e.g. real estate, HVAC/home services, restaurant, fitness studio, salon — "
            "just describe it in your own words.",
        )
        goal = st.text_area(
            "What do you want social media to do for your business?",
            help="e.g. bring in more calls, build local awareness, fill appointment slots — "
            "whatever your actual goal is.",
        )

        st.markdown("#### Branding")
        logo_choice = st.radio("Do you have a logo?", intake.LOGO_OPTIONS)
        uploaded_logo = None
        if logo_choice == intake.LOGO_UPLOAD:
            uploaded_logo = st.file_uploader("Upload your logo", type=["png", "jpg", "jpeg", "svg", "pdf"])
        brand_colors_fonts = st.text_area(
            "Do you have brand colors or fonts you'd like used?",
            help="Totally optional — if you're not sure, we'll pick something that fits your industry.",
        )

        st.markdown("#### Platforms")
        platforms = st.multiselect(
            "Which platforms do you want us to manage?",
            intake.PLATFORM_OPTIONS,
            format_func=lambda p: _PLATFORM_LABELS[p],
            max_selections=intake.MAX_PLATFORMS,
            help=f"Choose up to {intake.MAX_PLATFORMS} for your plan.",
        )
        platform_sources = {}
        for platform in platforms:
            platform_sources[platform] = st.radio(
                f"{_PLATFORM_LABELS[platform]} — do you already have an account?",
                intake.ACCOUNT_SOURCE_OPTIONS,
                key=f"intake_platform_{platform}",
                horizontal=True,
            )

        st.markdown("#### Style & cadence")
        tone = st.radio("What tone fits your business best?", intake.TONE_OPTIONS)
        frequency = st.radio("How often would you like to post?", intake.FREQUENCY_OPTIONS)

        st.markdown("#### Contact")
        contact_email = st.text_input(
            "Best email to reach you at", help="We'll send updates here once everything's set up."
        )
        notes = st.text_area("Anything else we should know?")

        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    if not business_name or not industry or not goal or not platforms or not contact_email:
        st.error("Please fill in all required fields (marked above) before submitting.")
        return
    if not _EMAIL_PATTERN.match(contact_email):
        st.error("Enter a valid email address.")
        return

    responses = {
        "business_name": business_name,
        "industry": industry,
        "goal": goal,
        "logo_choice": logo_choice,
        "brand_colors_fonts": brand_colors_fonts,
        "platforms": platforms,
        "platform_sources": platform_sources,
        "tone": tone,
        "frequency": frequency,
        "contact_email": contact_email,
        "notes": notes,
    }
    intake.submit_intake(privileged_client, customer_id, responses, uploaded_logo=uploaded_logo)
    st.success("Thanks! Your admin will follow up shortly.")
    st.rerun()


def render(customer_id: str | None) -> None:
    st.markdown("## Your Hub")

    if not customer_id:
        empty_state("Your account isn't linked to a customer profile yet.")
        return

    client = supabase_client.get_supabase_client()
    customer = client.table("customers").select("intake_completed_at").eq("id", customer_id).maybe_single().execute()
    if intake.needs_intake(customer.data or {}):
        _render_intake_form(customer_id)
        return

    with st.sidebar:
        unread = notifications.unread_count(supabase_client.get_supabase_client(), recipient_type="customer", customer_id=customer_id)
        if unread:
            st.caption(f"🔔 {unread} unread notification(s)")
        selection = st.radio("Navigate", NAV_ITEMS, label_visibility="collapsed")

    if selection == "Requests":
        _render_requests(customer_id)
    elif selection == "Approval Queue":
        _render_approval_queue(customer_id)
    elif selection == "Calendar":
        _render_calendar(customer_id)
    elif selection == "Notifications":
        _render_notifications(customer_id)
    else:
        _render_home(customer_id)
