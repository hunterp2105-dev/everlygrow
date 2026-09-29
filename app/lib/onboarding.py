"""Admin-facing customer onboarding: playbook resolution, pool assignment,
and provisioning (customer record, module registry rows, project shells,
social account placeholders, customer login invite).

Each onboarding attempt is tracked as an `onboarding_intakes` row so a
partial failure can be *resumed* rather than re-submitted from scratch:
every step below checks whether its target already exists before creating
it, so re-running provisioning against the same intake only does the work
that's still missing. Still not a database transaction — there's no
multi-statement transaction support over the Supabase REST API — but it's
now safe to retry as many times as needed.
"""

from datetime import datetime, timezone

from app.lib.caps import DEFAULT_CAPS, DEFAULT_WARM_UP_PERIOD_DAYS

PLATFORMS = ["tiktok", "instagram", "x"]

ALREADY_REGISTERED_MARKERS = ("already been registered", "already registered", "already exists")


def list_playbook_niches(client) -> list[str]:
    response = (
        client.table("niche_playbooks")
        .select("niche")
        .eq("is_default", False)
        .order("niche")
        .execute()
    )
    return [row["niche"] for row in (response.data or [])]


def resolve_playbook(client, niche_text: str) -> dict:
    """Exact case-insensitive match against known niches; falls back to the
    single general-purpose default so no business is ever left without a
    starting strategy, per the updated §4b."""
    normalized = (niche_text or "").strip()
    if normalized:
        match = (
            client.table("niche_playbooks")
            .select("*")
            .eq("is_default", False)
            .ilike("niche", normalized)
            .maybe_single()
            .execute()
        )
        if match and match.data:
            return {"playbook": match.data, "matched": True}

    default = (
        client.table("niche_playbooks")
        .select("*")
        .eq("is_default", True)
        .maybe_single()
        .execute()
    )
    return {"playbook": default.data if default else None, "matched": False}


def list_active_modules(client) -> list[dict]:
    response = (
        client.table("modules")
        .select("id, key, name, status")
        .eq("status", "active")
        .order("name")
        .execute()
    )
    return response.data or []


def pick_pool(client) -> dict | None:
    response = client.table("blotato_account_pools").select("*").execute()
    for pool in response.data or []:
        if pool["connected_account_count"] < pool["cap"]:
            return pool
    return None


def list_incomplete_intakes(client) -> list[dict]:
    response = (
        client.table("onboarding_intakes")
        .select("*")
        .neq("status", "complete")
        .order("created_at")
        .execute()
    )
    return response.data or []


def _find_auth_user_by_email(admin_client, email: str):
    for user in admin_client.auth.admin.list_users():
        if user.email == email:
            return user
    return None


def _ensure_invited_user(admin_client, email: str) -> tuple[str | None, str | None]:
    """Returns (auth_user_id, error). Treats 'already registered' as success
    (idempotent) rather than a failure, so retry doesn't re-invite."""
    try:
        invite = admin_client.auth.admin.invite_user_by_email(email)
        return invite.user.id, None
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if any(marker in message.lower() for marker in ALREADY_REGISTERED_MARKERS):
            existing = _find_auth_user_by_email(admin_client, email)
            if existing:
                return existing.id, None
        return None, message


def _upsert_intake(client, intake: dict) -> dict:
    if intake.get("id"):
        client.table("onboarding_intakes").update(
            {
                "customer_id": intake.get("customer_id"),
                "status": intake["status"],
                "last_steps_completed": intake["steps_completed"],
                "last_errors": intake["errors"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", intake["id"]).execute()
        return intake

    inserted = (
        client.table("onboarding_intakes")
        .insert(
            {
                "email": intake["email"],
                "payload": intake["payload"],
                "status": intake["status"],
                "last_steps_completed": intake["steps_completed"],
                "last_errors": intake["errors"],
            }
        )
        .execute()
    )
    intake["id"] = inserted.data[0]["id"]
    return intake


def provision_customer(client, admin_client, payload: dict, intake: dict | None = None) -> dict:
    """payload keys: email, business_name, niche, goals, tone_voice,
    posting_frequency, guardrail_sensitivity, holiday_preferences (list[str]),
    default_voice_preference, selected_module_keys (list[str]),
    platform_sources (dict[str, str] platform -> 'existing'|'new'),
    warm_up_period_days (int, optional, defaults to DEFAULT_WARM_UP_PERIOD_DAYS).

    `intake`, if passed (from a Resume Onboarding retry), is the existing
    onboarding_intakes row — provisioning resumes using its stored
    customer_id rather than starting over.
    """
    steps_completed: list[str] = []
    errors: list[str] = []
    intake = intake or {"email": payload["email"], "payload": payload, "customer_id": None}
    intake["steps_completed"] = steps_completed
    intake["errors"] = errors
    intake["status"] = "in_progress"
    intake = _upsert_intake(client, intake)

    auth_user_id, invite_error = _ensure_invited_user(admin_client, payload["email"])
    if invite_error:
        errors.append(f"Couldn't create/verify login for {payload['email']}: {invite_error}")
        intake["status"] = "failed"
        _upsert_intake(client, intake)
        return {"steps_completed": steps_completed, "errors": errors, "customer_id": intake.get("customer_id"), "intake_id": intake["id"]}
    steps_completed.append(f"Login ready for {payload['email']}")

    playbook_resolution = resolve_playbook(client, payload["niche"])
    playbook = playbook_resolution["playbook"]
    steps_completed.append(
        f"Resolved niche playbook: {'matched ' + playbook['niche'] if playbook_resolution['matched'] else 'fell back to General default'}"
    )

    customer_id = intake.get("customer_id")
    if not customer_id:
        try:
            customer_insert = (
                client.table("customers")
                .insert(
                    {
                        "name": payload["business_name"],
                        "email": payload["email"],
                        "niche": payload["niche"],
                        "niche_playbook_id": playbook["id"] if playbook else None,
                        "brand_profile": {"tone_voice": payload.get("tone_voice", "")},
                        "guardrail_config": {"sensitivity": payload.get("guardrail_sensitivity", "standard")},
                        "plan_caps": {"posting_frequency": payload.get("posting_frequency", "")},
                        "holiday_preferences": {"categories": payload.get("holiday_preferences", [])},
                        "approval_preference": "manual",
                        "default_voice_preference": payload.get("default_voice_preference"),
                    }
                )
                .execute()
            )
            customer_id = customer_insert.data[0]["id"]
            intake["customer_id"] = customer_id
            _upsert_intake(client, intake)
            steps_completed.append(f"Created customer record for {payload['business_name']}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Couldn't create customer record: {exc}")
            intake["status"] = "failed"
            _upsert_intake(client, intake)
            return {"steps_completed": steps_completed, "errors": errors, "customer_id": None, "intake_id": intake["id"]}
    else:
        steps_completed.append("Customer record already exists — reusing it")

    existing_profile = (
        client.table("profiles").select("id").eq("id", auth_user_id).maybe_single().execute()
    )
    if not (existing_profile and existing_profile.data):
        try:
            client.table("profiles").insert(
                {"id": auth_user_id, "role": "customer", "customer_id": customer_id}
            ).execute()
            steps_completed.append("Linked login to customer record")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Couldn't link login to customer record: {exc}")
    else:
        steps_completed.append("Login already linked to customer record")

    modules_response = client.table("modules").select("id, key, name").execute()
    modules_by_key = {m["key"]: m for m in (modules_response.data or [])}
    existing_customer_modules = (
        client.table("customer_modules").select("module_id").eq("customer_id", customer_id).execute()
    )
    existing_module_ids = {row["module_id"] for row in (existing_customer_modules.data or [])}

    for module_key in payload.get("selected_module_keys", []):
        module = modules_by_key.get(module_key)
        if not module:
            errors.append(f"Module '{module_key}' not found in registry — skipped")
            continue
        if module["id"] in existing_module_ids:
            steps_completed.append(f"{module['name']} already enabled — skipping")
            continue
        try:
            client.table("customer_modules").insert(
                {
                    "customer_id": customer_id,
                    "module_id": module["id"],
                    "enabled": True,
                    "caps": DEFAULT_CAPS.get(module_key, {}),
                }
            ).execute()
            client.table("projects").insert(
                {
                    "customer_id": customer_id,
                    "module_id": module["id"],
                    "name": f"{payload['business_name']} — {module['name']}",
                }
            ).execute()
            steps_completed.append(f"Enabled {module['name']} and created its project folder")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Couldn't set up {module['name']}: {exc}")

    if "social" in payload.get("selected_module_keys", []):
        existing_accounts = (
            client.table("social_accounts").select("platform").eq("customer_id", customer_id).execute()
        )
        existing_platforms = {row["platform"] for row in (existing_accounts.data or [])}
        pool = pick_pool(client)
        if pool is None:
            errors.append(
                "No Blotato pool account has room for new connections — "
                "add a new pool before connecting this customer's accounts."
            )
        warm_up_period_days = payload.get("warm_up_period_days", DEFAULT_WARM_UP_PERIOD_DAYS)
        for platform, source in payload.get("platform_sources", {}).items():
            if platform in existing_platforms:
                steps_completed.append(f"{platform} already queued — skipping")
                continue
            try:
                client.table("social_accounts").insert(
                    {
                        "customer_id": customer_id,
                        "platform": platform,
                        "source": source,
                        "blotato_pool_id": pool["id"] if pool else None,
                        "warm_up_status": "pending_connection",
                        "warm_up_period_days": warm_up_period_days,
                    }
                ).execute()
                existing_platforms.add(platform)
                steps_completed.append(f"Queued {platform} for admin connection ({source} account)")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Couldn't queue {platform}: {exc}")

        # §7 "Social platforms per customer" cap — soft (flag, don't block),
        # matching every other cap in this codebase. Read back the caps
        # actually stored on this customer's customer_modules row (not the
        # DEFAULT_CAPS constant directly) since caps are meant to be
        # per-customer configurable, not hardcoded.
        social_module = modules_by_key.get("social")
        if social_module:
            social_caps_row = (
                client.table("customer_modules")
                .select("caps")
                .eq("customer_id", customer_id)
                .eq("module_id", social_module["id"])
                .maybe_single()
                .execute()
            )
            platforms_cap = ((social_caps_row.data or {}).get("caps") or {}).get("platforms_per_customer") if social_caps_row else None
            if platforms_cap is not None and len(existing_platforms) > platforms_cap:
                steps_completed.append(
                    f"Note: {len(existing_platforms)} platforms connected, over the {platforms_cap}-platform cap "
                    "— allowed anyway (soft cap, admin discretion)."
                )

    intake["status"] = "failed" if errors else "complete"
    _upsert_intake(client, intake)
    return {"steps_completed": steps_completed, "errors": errors, "customer_id": customer_id, "intake_id": intake["id"]}


def retry_intake(client, admin_client, intake_row: dict) -> dict:
    """Resume a previously incomplete onboarding using its stored payload."""
    intake = {
        "id": intake_row["id"],
        "email": intake_row["email"],
        "payload": intake_row["payload"],
        "customer_id": intake_row.get("customer_id"),
    }
    return provision_customer(client, admin_client, intake_row["payload"], intake=intake)
