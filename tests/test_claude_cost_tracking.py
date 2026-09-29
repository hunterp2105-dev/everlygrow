"""§16 admin follow-up (2026-09-29): real token-based Claude API cost
logging. Found live that NO Claude call anywhere in this codebase was
ever cost-logged (including guardrails' constant Sonnet calls), so the
Credit & Cost Tracker was undercounting real spend. Tests the pure cost
math (real Sonnet 5 pricing) and the real DB write into the same
credit_usage_log ledger Blotato spend already uses.
"""

from types import SimpleNamespace

from app.lib import credits


def _usage(input_tokens=0, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )


def test_claude_usage_cost_usd_matches_real_sonnet_5_pricing():
    # 1,000,000 input tokens + 1,000,000 output tokens at $2/$10 per MTok
    usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert credits.claude_usage_cost_usd(usage) == 12.00


def test_claude_usage_cost_usd_handles_small_real_call_sizes():
    # A typical guardrail call: ~800 input tokens, ~150 output tokens
    usage = _usage(input_tokens=800, output_tokens=150)
    expected = (800 * 2.00 + 150 * 10.00) / 1_000_000
    assert credits.claude_usage_cost_usd(usage) == expected


def test_claude_usage_cost_usd_includes_cache_tokens_when_present():
    usage = _usage(input_tokens=100, output_tokens=50, cache_creation_input_tokens=1000, cache_read_input_tokens=2000)
    expected = (100 * 2.00 + 50 * 10.00 + 1000 * 2.50 + 2000 * 0.20) / 1_000_000
    assert credits.claude_usage_cost_usd(usage) == expected


def test_log_claude_usage_converts_to_the_same_credit_unit_as_blotato(admin_client, temp_customer):
    usage = _usage(input_tokens=1_000_000, output_tokens=1_000_000)  # $12.00 real cost

    entry = credits.log_claude_usage(admin_client, temp_customer["id"], usage, cost_source="guardrail_evaluation")

    expected_credits = 12.00 / credits.CREDIT_USD_RATE  # same $0.006/credit rate as Blotato
    assert entry["credit_cost"] == expected_credits
    assert entry["generation_id"] is None
    assert entry["cost_source"] == "guardrail_evaluation"
    assert entry["cost_is_measured"] is True


def test_log_claude_usage_is_included_in_usage_this_period(admin_client, temp_customer):
    usage = _usage(input_tokens=500_000, output_tokens=100_000)
    credits.log_claude_usage(admin_client, temp_customer["id"], usage, cost_source="claude_content_ideas")

    total = credits.usage_this_period(admin_client, temp_customer["id"])
    expected = (500_000 * 2.00 + 100_000 * 10.00) / 1_000_000 / credits.CREDIT_USD_RATE
    assert total == expected
