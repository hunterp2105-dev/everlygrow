"""§16 step 45 — the actual proof of the architecture's core promise: a
brand-new module can be added by inserting data, with ZERO changes to any
existing module's code. This test makes no code changes of its own either
— it only inserts/enables/deletes rows in the real `modules` and
`customer_modules` tables and confirms every existing, unmodified read path
picks the new module up automatically:

  1. onboarding.list_active_modules()      (Onboard Customer screen)
  2. admin_panel._all_modules()            (Module Map)
  3. theme.module_map_svg()                (Module Map's rendered diagram)
  4. customer_hub._active_modules()        (customer Home, once enabled)

If any of these required editing app/lib or app/views to recognize the new
module by name, the "add a module without rebuilding what's already here"
promise (§4a) would be false. They don't — every one of them queries
`modules`/`customer_modules` generically by status/enabled, never by key.
"""

import uuid

from app.lib import onboarding
from app.lib.theme import module_map_svg
from app.views import admin_panel, customer_hub


def test_new_module_appears_in_every_generic_listing_with_zero_code_changes(
    admin_client, temp_customer, rest_call, signed_in_admin_client
):
    dummy_key = f"dummy_test_module_{uuid.uuid4().hex[:8]}"
    module_row = admin_client.table("modules").insert(
        {"key": dummy_key, "name": "Dummy Test Module", "status": "active", "description": "Phase 12 registry proof — safe to delete."}
    ).execute().data[0]

    try:
        # 1. Onboarding's active-module list (app/lib/onboarding.py) — no
        # module-specific code, queries modules where status='active'.
        active_keys = {m["key"] for m in onboarding.list_active_modules(admin_client)}
        assert dummy_key in active_keys, "New active module did not appear in onboarding.list_active_modules()"

        # 2. Admin Module Map's data source (app/views/admin_panel.py
        # ._all_modules) — same story, no per-module branching.
        all_modules = admin_panel._all_modules()
        mapped = {m["key"]: m for m in all_modules}
        assert dummy_key in mapped, "New module did not appear in admin_panel._all_modules()"
        assert mapped[dummy_key]["status"] == "active"

        # 3. The Module Map's actual rendered visual (app/lib/theme.py) —
        # confirm it renders the new node without raising, and that it's
        # rendered as active (not silently dropped or misclassified).
        svg = module_map_svg("HUB", all_modules)
        assert "Dummy Test" in svg or "Dummy" in svg
        # One active trace/node per active module — this dummy module being
        # active should have pushed the active count up by exactly one
        # relative to the baseline before it existed.
        baseline_active = sum(1 for m in all_modules if m["status"] == "active" and m["key"] != dummy_key)
        assert svg.count("sg-node--active") == baseline_active + 1

        # 4. Enable it for a real (throwaway) customer and confirm the
        # customer Hub's own active-modules query (app/views/customer_hub.py)
        # — again, generic, keyed only by customer_modules.enabled — picks
        # it up with no code change either.
        module_id = module_row["id"]
        admin_client.table("customer_modules").insert(
            {"customer_id": temp_customer["id"], "module_id": module_id, "enabled": True}
        ).execute()
        customer_active = {m["key"] for m in customer_hub._active_modules(temp_customer["id"])}
        assert dummy_key in customer_active, "New module, once enabled, did not appear in customer_hub._active_modules()"

    finally:
        # Cleanup: customer_modules row cascades on customer delete (handled
        # by the temp_customer fixture) or on module delete (FK cascade) —
        # delete the module explicitly to be sure nothing lingers.
        rest_call("DELETE", f"modules?key=eq.{dummy_key}")


def test_new_planned_module_renders_dashed_and_dim_with_zero_code_changes(admin_client, rest_call, signed_in_admin_client):
    """Same proof, for a 'planned' (not yet active) module — confirms the
    Module Map's active/planned branching is genuinely data-driven, not
    hardcoded to the six modules that exist today."""
    dummy_key = f"dummy_planned_module_{uuid.uuid4().hex[:8]}"
    admin_client.table("modules").insert(
        {"key": dummy_key, "name": "Dummy Planned Module", "status": "planned", "description": "Phase 12 registry proof — safe to delete."}
    ).execute()
    try:
        all_modules = admin_panel._all_modules()
        assert any(m["key"] == dummy_key and m["status"] == "planned" for m in all_modules)
        svg = module_map_svg("HUB", all_modules)
        assert "sg-node--planned" in svg
        baseline_active = sum(1 for m in all_modules if m["status"] == "active")
        assert svg.count("sg-node--active") == baseline_active
    finally:
        rest_call("DELETE", f"modules?key=eq.{dummy_key}")
