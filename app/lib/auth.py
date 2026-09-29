import streamlit as st

from app.lib.supabase_client import get_supabase_client


def _client():
    return get_supabase_client()


def sign_in(email: str, password: str) -> str | None:
    """Attempt sign in. Returns an error message on failure, None on success."""
    try:
        result = _client().auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001 - surface any auth failure as a plain message
        return str(exc)
    st.session_state["sg_session"] = result.session
    st.session_state["sg_user"] = result.user
    return None


def adopt_session(access_token: str, refresh_token: str) -> str | None:
    """Adopt a session obtained outside a password sign-in — specifically an
    invite/recovery link's access+refresh token pair. Used by the
    accept-invite flow so a freshly-invited customer's session (and RLS
    scope) is exactly theirs, not admin's and not another customer's."""
    try:
        result = _client().auth.set_session(access_token, refresh_token)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    st.session_state["sg_session"] = result.session
    st.session_state["sg_user"] = result.user
    return None


def set_password(new_password: str) -> str | None:
    """Sets the password for the currently-adopted session's user (self-service
    — requires their own session, not admin privileges).

    supabase-py's Client._listen_to_auth_events resets the shared postgrest
    client's Authorization header to the plain anon key on every auth event
    that ISN'T "SIGNED_IN"/"TOKEN_REFRESHED"/"SIGNED_OUT" — and update_user()
    fires "USER_UPDATED", which isn't in that list. So immediately after a
    successful password change, the client silently drops back to
    unauthenticated for subsequent queries unless we re-apply the session's
    own token ourselves right after. Confirmed live: current_profile() came
    back None post-set_password despite the session/RLS both being fine —
    re-applying auth here fixed it."""
    client = _client()
    try:
        client.auth.update_user({"password": new_password})
    except Exception as exc:  # noqa: BLE001
        return str(exc)

    session = st.session_state.get("sg_session")
    if session:
        client.postgrest.auth(session.access_token)
    return None


def sign_out() -> None:
    try:
        _client().auth.sign_out()
    except Exception:  # noqa: BLE001 - sign-out is best-effort
        pass
    for key in ("sg_session", "sg_user", "sg_profile"):
        st.session_state.pop(key, None)


def current_user():
    return st.session_state.get("sg_user")


def current_profile() -> dict | None:
    """Fetch (and cache in session) the profiles row for the signed-in user."""
    if "sg_profile" in st.session_state:
        return st.session_state["sg_profile"]

    user = current_user()
    if not user:
        return None

    response = (
        _client()
        .table("profiles")
        .select("id, role, customer_id")
        .eq("id", user.id)
        .maybe_single()
        .execute()
    )
    profile = response.data if response else None
    st.session_state["sg_profile"] = profile
    return profile


def is_authenticated() -> bool:
    return current_user() is not None
