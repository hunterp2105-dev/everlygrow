-- Phase 2 follow-up: configurable per-account warm-up period (21-day
-- default, not the previous hardcoded 14), customers.email (needed so a
-- retry/resume action can always find who to re-invite without depending
-- on a profiles/auth join that may not exist yet), and onboarding_intakes
-- (tracks in-progress onboarding so a partial failure can be resumed
-- instead of re-run from scratch).

alter table social_accounts
  add column if not exists warm_up_period_days integer not null default 21;

alter table customers
  add column if not exists email text;

create table if not exists onboarding_intakes (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  payload jsonb not null,
  customer_id uuid references customers (id) on delete set null,
  status text not null default 'in_progress' check (status in ('in_progress', 'complete', 'failed')),
  last_steps_completed jsonb not null default '[]'::jsonb,
  last_errors jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table onboarding_intakes enable row level security;
create policy "admin full access to onboarding_intakes" on onboarding_intakes
  for all using (auth_is_admin());
