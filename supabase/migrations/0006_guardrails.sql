-- Phase 5: Guardrails, QC & Failure Handling (§6, §9).
-- Guardrail results live directly on `generations` (§13 already lists
-- "guardrail results" as a generations field) so the same generic
-- generation/poller from Phases 3-4 carries guardrail state uniformly
-- across both modules — no per-module guardrail tables.

alter table generations
  add column if not exists guardrail_status text not null default 'pending'
    check (guardrail_status in ('pending', 'passed', 'flagged', 'failed')),
  add column if not exists guardrail_results jsonb,
  add column if not exists guardrail_checked_at timestamptz;

-- Escalation queue (§9): both guardrail and publish failures land here once
-- retries are exhausted, rather than failing silently. `reason` is generic
-- so the same table covers publish failures once Phase 6 makes publishing
-- real (it's still stubbed as of Phase 3-4).
create table if not exists escalations (
  id uuid primary key default gen_random_uuid(),
  generation_id uuid not null references generations (id) on delete cascade,
  customer_id uuid not null references customers (id) on delete cascade,
  reason text not null check (reason in ('guardrail', 'publish')),
  category text,
  details jsonb not null default '{}'::jsonb,
  status text not null default 'open' check (status in ('open', 'resolved')),
  resolution_note text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

alter table escalations enable row level security;

create policy "admin full access to escalations" on escalations
  for all using (auth_is_admin());
