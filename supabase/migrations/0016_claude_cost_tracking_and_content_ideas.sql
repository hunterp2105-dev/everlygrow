-- Claude API cost tracking + customer content-idea suggestions
-- (§16 admin follow-up, 2026-09-29)
--
-- PART 1 — Claude cost tracking. Found live: NO Claude/Anthropic API call
-- anywhere in this codebase was ever cost-logged, including guardrail
-- evaluations running constantly on every generation — meaning the
-- existing Credit & Cost Tracker has been undercounting real spend by
-- omitting all Claude usage. cost_source distinguishes entries without
-- needing a new table — credit_usage_log already sums correctly across
-- sources for the existing "credits this period" total (see
-- credits.usage_this_period), so no admin UI change is needed for this
-- to just show up there.
alter table credit_usage_log
  add column if not exists cost_source text;

update credit_usage_log set cost_source = 'blotato_generation' where cost_source is null;

-- PART 2 — Customer content-idea suggestions (the customer-side mirror of
-- admin's playbook-suggestions feature). Generated in a batch by a real
-- Claude call and cached here — see app/lib/content_ideas.py's module
-- docstring for the refresh discipline (this app has no background
-- scheduler; refresh is checked lazily at Request-tab view time).
create table if not exists customer_content_ideas (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  title text not null,
  detail text not null,
  category text not null
    check (category in ('transformation', 'behind_the_scenes', 'trust_building', 'search_optimized', 'seasonal')),
  status text not null default 'active'
    check (status in ('active', 'used', 'dismissed')),
  batch_generated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

alter table customer_content_ideas enable row level security;

-- Same privilege pattern as approval.py/intake.py: customer's own session
-- can only read its own ideas; all writes (generating a batch, marking
-- one used) go through the service-role client from customer_hub.py.
create policy "admin full access to customer_content_ideas" on customer_content_ideas
  for all using (auth_is_admin());
create policy "customer reads own customer_content_ideas" on customer_content_ideas
  for select using (customer_id = auth_customer_id());
