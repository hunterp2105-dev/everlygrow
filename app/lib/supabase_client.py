import os

import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def _new_anon_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set (see .env.example)."
        )
    return create_client(url, key)


def get_supabase_client() -> Client:
    """One client per Streamlit session (st.session_state), NOT a shared
    st.cache_resource singleton. This client's requests carry whichever
    user's session token auth.sign_in() has attached to it (see
    app.lib.auth) — a process-wide singleton would leak one user's session
    into every other concurrent user's requests."""
    if "sg_supabase_client" not in st.session_state:
        st.session_state["sg_supabase_client"] = _new_anon_client()
    return st.session_state["sg_supabase_client"]


@st.cache_resource
def get_supabase_admin_client() -> Client:
    """Service-role client — bypasses RLS entirely, so every call site is a
    trust boundary. Used for admin-only code paths (customer onboarding
    invites), AND (as of Phase 6) from customer_hub.py's approval actions,
    since generations' RLS only grants customers SELECT and the
    publish-dispatch writes (publish tracking, escalations, notifications)
    are admin-only. That customer-facing use is safe ONLY because
    app/lib/approval.py verifies the caller's own (session-derived,
    unspoofable) customer_id against the generation's actual owner before
    writing anything — never call this from customer-facing code without
    an equivalent explicit ownership check of your own."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see .env.example) "
            "to onboard new customers."
        )
    return create_client(url, key)
