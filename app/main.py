import os
import sys

# Deployment fix (Streamlit Community Cloud): running `python -m streamlit
# run app/main.py` locally puts the current working directory (the repo
# root) on sys.path, which is why `from app.lib import ...` below has always
# worked in local dev. Streamlit Cloud's runner does not do this the same
# way — it left the repo root off sys.path, so the very same import failed
# there with `ModuleNotFoundError: No module named 'app'` (reproduced
# locally too: this import fails if the working context is app/ itself,
# rather than its parent). Explicitly adding the repo root here makes the
# import resolve the same way regardless of how the script was invoked —
# a packaging fix, not a functional change.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import streamlit.components.v1 as components

from app.lib import auth
from app.lib.theme import inject_theme
from app.views import admin_panel, customer_hub

st.set_page_config(page_title="EverlyGrow", page_icon="✦", layout="wide")
inject_theme()

# This Supabase project's invite/recovery emails use the implicit auth flow —
# confirmed by following a generated link and inspecting its redirect: tokens
# arrive as a URL hash fragment (#access_token=...), not a ?code= query param.
# Hash fragments never reach the server, so Streamlit's Python code can't read
# them directly. This one-time JS shim moves them into query params (which
# st.query_params CAN read) via a single client-side redirect. The
# alternative — customizing Supabase's email template to link with
# ?token_hash=... instead of Supabase's own redirect — would avoid this shim,
# but requires a manual dashboard template edit for every email type; this
# shim works against the existing default templates unmodified.
_HASH_TO_QUERY_SHIM = """
<script>
  const hash = window.top.location.hash;
  if (hash && hash.includes('access_token')) {
    const hashParams = new URLSearchParams(hash.substring(1));
    const search = new URLSearchParams(window.top.location.search);
    for (const [key, value] of hashParams.entries()) {
      search.set(key, value);
    }
    window.top.location.replace(window.top.location.pathname + '?' + search.toString());
  }
</script>
"""


def render_set_password(invite_type: str) -> None:
    st.markdown("## Set your password")
    if invite_type == "invite":
        st.caption("Welcome! Set a password to finish setting up your account.")
    else:
        st.caption("Set a new password for your account.")

    with st.form("set_password_form"):
        password = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Set password")

    if not submitted:
        return

    if len(password) < 8:
        st.error("Password must be at least 8 characters.")
        return
    if password != confirm:
        st.error("Passwords don't match.")
        return

    error = auth.set_password(password)
    if error:
        st.error(f"Couldn't set your password: {error}")
        return

    st.query_params.clear()
    st.success("Password set. Loading your account...")
    st.rerun()


def render_login() -> None:
    st.markdown("## EverlyGrow")
    st.caption("Sign in to your Hub.")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        error = auth.sign_in(email, password)
        if error:
            st.error("Couldn't sign you in — check your email and password and try again.")
        else:
            st.rerun()


def render_app() -> None:
    profile = auth.current_profile()

    if profile is None:
        st.error(
            "Your account isn't set up yet. Ask your admin to finish setting up "
            "your access, then try signing in again."
        )
        if st.button("Sign out"):
            auth.sign_out()
            st.rerun()
        return

    with st.sidebar:
        st.markdown("### EverlyGrow")
        st.caption(f"Signed in as **{auth.current_user().email}**")
        if st.button("Sign out", use_container_width=True):
            auth.sign_out()
            st.rerun()

    if profile["role"] == "admin":
        admin_panel.render()
    else:
        customer_hub.render(profile["customer_id"])


def main() -> None:
    access_token = st.query_params.get("access_token")
    invite_type = st.query_params.get("type")

    if access_token and invite_type in ("invite", "recovery"):
        refresh_token = st.query_params.get("refresh_token", "")
        error = auth.adopt_session(access_token, refresh_token)
        if error:
            st.error("This link is invalid or has expired. Ask your admin to send a new one.")
            return
        render_set_password(invite_type)
        return

    if not auth.is_authenticated():
        components.html(_HASH_TO_QUERY_SHIM, height=0)
        render_login()
    else:
        render_app()


if __name__ == "__main__":
    main()
