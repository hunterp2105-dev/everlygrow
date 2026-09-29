"""Phase 12 test suite fixtures (§16 steps 36-45).

Runs against the REAL Supabase project and, where explicitly noted per
test, the REAL Blotato and Anthropic APIs — not mocks — matching how every
prior phase in this build was verified. The one deliberate exception:
Blotato's real publish endpoint (blotato_client.create_post / POST /v2/posts)
is never called live by this suite. That's a standing rule for this
project (established at the Phase 6 gate) because it posts to a customer's
real connected account — an automated test suite re-running that on every
run would violate it every time. Publish-path tests mock only that one
HTTP call and exercise everything else (retry counting, escalation,
notifications, Supabase writes) for real.

Every fixture that creates a Supabase row cleans it up on teardown, the
same discipline used throughout this project's manual live-testing.
"""

import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
_ADMIN_HEADERS = {
    "apikey": SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
}

DEV_CUSTOMER_ID = "91134b44-adfa-45ac-9a1a-3ae57f9cb7fe"
"""The persistent 'Dev Test - Social Generation (Phase 3)' customer with a
real connected TikTok account (blotato_account_id 51990) — reused here
rather than creating a throwaway customer for tests that need a real,
already-connected social account."""

DEV_SOCIAL_ACCOUNT_ID = "d9314dab-9376-4b8b-9353-31868f282114"


def rest(method: str, path: str, **kwargs) -> requests.Response:
    """Raw REST call against Supabase using the service-role key — used for
    setup/teardown and assertions the app's own supabase-py client would
    otherwise wrap, so failures here are unambiguous (not obscured by
    postgrest-py's own exception types)."""
    response = requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=_ADMIN_HEADERS, **kwargs)
    response.raise_for_status()
    return response


@pytest.fixture
def rest_call():
    """Exposes the module-level rest() helper as a fixture so test files
    don't need a package-relative import of tests.conftest."""
    return rest


@pytest.fixture(scope="session")
def admin_client():
    from app.lib import supabase_client

    return supabase_client.get_supabase_admin_client()


@pytest.fixture
def temp_customer(admin_client):
    """A throwaway customer for tests that need isolated, disposable state
    (caps, notifications, cross-module, data isolation) rather than sharing
    the persistent Dev Test customer. Deleted on teardown; cascades clean
    up any generations/social_accounts/etc. created against it."""
    name = f"Phase12 Test Customer {uuid.uuid4().hex[:8]}"
    row = admin_client.table("customers").insert({"name": name, "niche": "General"}).execute().data[0]
    yield row
    admin_client.table("customers").delete().eq("id", row["id"]).execute()


@pytest.fixture
def temp_customer_pair(admin_client):
    """Two throwaway customers, for data-isolation tests that need to prove
    customer A's session genuinely cannot see customer B's rows."""
    rows = []
    for i in range(2):
        name = f"Phase12 Isolation Customer {i} {uuid.uuid4().hex[:8]}"
        rows.append(admin_client.table("customers").insert({"name": name, "niche": "General"}).execute().data[0])
    yield rows
    for row in rows:
        admin_client.table("customers").delete().eq("id", row["id"]).execute()


@pytest.fixture
def module_ids(admin_client):
    rows = admin_client.table("modules").select("id, key, name, status").execute().data
    return {row["key"]: row for row in rows}


def make_auth_user(email: str, password: str = "Test-Password-123!") -> str:
    users = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_ADMIN_HEADERS, params={"per_page": 200}).json()["users"]
    for u in users:
        if u["email"] == email:
            requests.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{u['id']}", headers=_ADMIN_HEADERS)
    resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=_ADMIN_HEADERS,
        json={"email": email, "password": password, "email_confirm": True},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def delete_auth_user(email: str) -> None:
    users = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users", headers=_ADMIN_HEADERS, params={"per_page": 200}).json()["users"]
    for u in users:
        if u["email"] == email:
            requests.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{u['id']}", headers=_ADMIN_HEADERS)


_TEST_PASSWORD = "Test-Password-123!"


@pytest.fixture
def signed_in_admin_client(admin_client):
    """A real signed-in ADMIN session, via the app's own auth.sign_in() +
    get_supabase_client() — the same RLS-scoped client any view-layer
    function (admin_panel.py, customer_hub.py) actually runs against. Those
    modules' session-scoped client requires an authenticated session; a
    bare anon client (what you get with no sign-in at all) satisfies none
    of the 'readable by authenticated'/'admin_is_admin()' policies and
    silently returns empty results, not an error — worth knowing, since
    that's exactly the trap the first draft of this suite fell into."""
    email = f"phase12-test-admin-{uuid.uuid4().hex[:8]}@example.com"
    user_id = make_auth_user(email, _TEST_PASSWORD)
    admin_client.table("profiles").insert({"id": user_id, "role": "admin", "customer_id": None}).execute()

    from app.lib import auth

    error = auth.sign_in(email, _TEST_PASSWORD)
    assert error is None, f"test admin sign-in failed: {error}"
    yield auth._client()
    delete_auth_user(email)


@pytest.fixture
def signed_in_customer_client_factory(admin_client):
    """Factory for a real signed-in CUSTOMER session against a given
    customer_id, using a fresh, independent supabase Client per call (NOT
    the app's session_state-cached one) — needed so two customer sessions
    can coexist in the same test process without one overwriting the
    other's cached client, which is exactly the cross-session-bleed bug
    Phase 1 found and fixed in the real app."""
    from supabase import create_client

    created_emails = []

    def _make(customer_id: str):
        email = f"phase12-test-customer-{uuid.uuid4().hex[:8]}@example.com"
        user_id = make_auth_user(email, _TEST_PASSWORD)
        created_emails.append(email)
        admin_client.table("profiles").insert({"id": user_id, "role": "customer", "customer_id": customer_id}).execute()
        client = create_client(SUPABASE_URL, os.environ["SUPABASE_ANON_KEY"])
        result = client.auth.sign_in_with_password({"email": email, "password": _TEST_PASSWORD})
        client.postgrest.auth(result.session.access_token)
        return client

    yield _make
    for email in created_emails:
        delete_auth_user(email)


_GUARDRAIL_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "guardrail-accuracy-notes.md")


@pytest.fixture(scope="session")
def guardrail_log():
    """Appends one entry per real guardrail call made during this test
    session to docs/guardrail-accuracy-notes.md — the running log this
    project has kept since Phase 5, feeding Phase 13's accuracy review.
    Every case from an automated run is worth recording, not just ones
    that look wrong at a glance, so future review has the full picture."""
    entries = []

    def _log(name: str, niche: str, prompt: str, result: dict) -> None:
        entries.append((name, niche, prompt, result))

    yield _log

    if not entries:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n### {today} — Phase 12 automated guardrail test suite run\n"]
    for name, niche, prompt, result in entries:
        flagged = {cat: v for cat, v in result["categories"].items() if v["verdict"] != "pass"}
        lines.append(f"**Case `{name}`** ({niche}) — overall: `{result['overall']}`")
        lines.append(f"Prompt: \"{prompt}\"")
        if flagged:
            for cat, v in flagged.items():
                lines.append(f"- `{cat}` ({v['verdict']}): {v['note']}")
        else:
            lines.append("- All categories passed.")
        lines.append("")

    with open(_GUARDRAIL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
