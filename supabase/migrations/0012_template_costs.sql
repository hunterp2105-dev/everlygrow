-- Phase 13 cost-validation follow-up: real per-template Blotato credit
-- costs vary by TEMPLATE, not by the old image/video category guess
-- (measured live via GET /v2/credits balance-diffing — see
-- docs/phase13-validation-notes.md). Replaces app/lib/credits.py's old
-- binary image=1/video=5 placeholder (ESTIMATED_COST_PER_TYPE) with a
-- table that's learned in production rather than pre-populated by hand:
-- the first time any given template is actually used, generation.py
-- snapshots the real Blotato credit balance before the job starts and
-- diffs it against the balance once the job finishes, writing the result
-- here. Every template after that reads its real measured cost instead
-- of a guess.
create table if not exists template_costs (
  template_id text primary key,
  credit_cost numeric not null,
  measured_at timestamptz not null default now()
);

alter table template_costs enable row level security;
create policy "admin full access to template_costs" on template_costs
  for all using (auth_is_admin());

-- Seed the three real measurements already taken by hand (2026-08-12,
-- see docs/phase13-validation-notes.md) so they aren't thrown away.
insert into template_costs (template_id, credit_cost) values
  ('9f4e66cd-b784-4c02-b2ce-e6d0765fd4c0', 0),                                  -- Single Centered Text Quote
  ('013904bf-6b3b-43f4-bb1f-f1964a38c29b', 50),                                 -- TV Wall Infographic
  ('/base/v2/ai-story-video/5903fe43-514d-40ee-a060-0d6628c5f8fd/v1', 35)       -- AI Story Video with AI Voice (voice omitted)
on conflict (template_id) do nothing;

-- Holds the Blotato credit balance snapshotted right before a generation
-- starts, ONLY when that generation's template has no row in
-- template_costs yet — cleared back to null once the cost is learned.
-- Needed because the "before" balance and the "after" balance are read at
-- two different points in time (start_generation vs. poll_generation's
-- ready-transition), so the snapshot has to survive somewhere in between.
alter table generations
  add column if not exists credit_balance_before_start integer;

-- Lets admin (and future review) distinguish a real measured cost from
-- the fallback placeholder at a glance, per-row, rather than needing to
-- cross-reference template_costs by hand.
alter table credit_usage_log
  add column if not exists cost_is_measured boolean not null default false;
