-- Client Intake Questionnaire (§16 admin follow-up, 2026-09-10)
-- A customer's first login now shows a required one-time questionnaire
-- instead of their normal Hub (see app/lib/intake.py, customer_hub.py) —
-- the real business answers (niche, tone, platforms, goals) now come
-- straight from the customer once, instead of admin typing a guess into
-- Onboard Customer on their behalf. intake_completed_at gates it;
-- intake_responses keeps the verbatim Q&A so admin can just read exactly
-- what was submitted (see admin_panel._render_customers).
--
-- Existing customers are grandfathered in as already-complete by the
-- backfill below — the gate only applies to customers created after this
-- migration runs, per explicit instruction: don't retroactively lock out
-- real accounts that never saw this questionnaire.

alter table customers
  add column if not exists intake_completed_at timestamptz,
  add column if not exists intake_responses jsonb,
  add column if not exists logo_url text;

update customers set intake_completed_at = now() where intake_completed_at is null;

-- Logo uploads (Q4a). Public read (a logo image isn't sensitive, and this
-- keeps served URLs simple) — writes only ever go through the app's
-- service-role client (see intake.py's module docstring: same
-- privilege pattern as approval.py, customer's own session never writes
-- here directly), so no storage.objects RLS policy is needed for customer
-- writes the way social_accounts needed one for reads.
insert into storage.buckets (id, name, public)
values ('customer-logos', 'customer-logos', true)
on conflict (id) do nothing;
