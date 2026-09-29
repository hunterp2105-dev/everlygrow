"""§16 growth-rules Group A6 (2026-09-11): X's 2026 algorithm favors
text-first posts, and video there is optional, not mandatory the way it
is on TikTok/Instagram (see docs/social-growth-playbook.md Part 4,
app/lib/growth_rules.py). generation.start_text_only_generation is the
one path in the generation engine with no Blotato media job at all — this
tests it runs through the exact same ready-transition handling
(guardrails, credit logging at a real 0 cost, notifications) as any other
generation reaching 'ready', without ever touching Blotato.
"""

from unittest.mock import patch

from app.lib import generation, growth_rules


def _social_module_id(admin_client) -> str:
    return admin_client.table("modules").select("id").eq("key", "social").maybe_single().execute().data["id"]


def test_start_text_only_generation_never_calls_blotato(admin_client, temp_customer):
    with patch("app.lib.blotato_client.create_from_template") as mock_create:
        result = generation.start_text_only_generation(
            admin_client, customer_id=temp_customer["id"], module_id=_social_module_id(admin_client),
            post_caption="A hot take about pricing your listing right.",
        )
    mock_create.assert_not_called()
    assert result["template_id"] == growth_rules.TEXT_ONLY_TEMPLATE_ID
    assert result["status"] == "ready"
    assert result["media_url"] is None
    assert result["post_caption"] == "A hot take about pricing your listing right."


def test_start_text_only_generation_logs_zero_real_cost(admin_client, temp_customer):
    result = generation.start_text_only_generation(
        admin_client, customer_id=temp_customer["id"], module_id=_social_module_id(admin_client),
        post_caption="A quick industry take.",
    )
    usage = admin_client.table("credit_usage_log").select("credit_cost, cost_is_measured").eq("generation_id", result["id"]).execute().data
    assert len(usage) == 1
    assert usage[0]["credit_cost"] == 0
    assert usage[0]["cost_is_measured"] is True, "0 is a real measurement here, not the unmeasured fallback guess"


def test_start_text_only_generation_runs_guardrails_and_fires_ready_notification(admin_client, temp_customer):
    result = generation.start_text_only_generation(
        admin_client, customer_id=temp_customer["id"], module_id=_social_module_id(admin_client),
        post_caption="A quick industry take about home inspections.",
    )
    assert result["guardrail_status"] in ("passed", "flagged", "failed")

    notif = admin_client.table("notifications").select("type").eq("customer_id", temp_customer["id"]).in_("type", ["generation_ready", "generation_failed"]).execute().data
    assert len(notif) >= 1


def test_start_text_only_generation_sets_target_account_when_given(admin_client, temp_customer):
    account = admin_client.table("social_accounts").insert(
        {"customer_id": temp_customer["id"], "platform": "x", "source": "existing", "blotato_account_id": "fake-x-id"}
    ).execute().data[0]

    result = generation.start_text_only_generation(
        admin_client, customer_id=temp_customer["id"], module_id=_social_module_id(admin_client),
        post_caption="A quick take.", target_social_account_id=account["id"],
    )
    assert result["target_social_account_id"] == account["id"]
