-- Phase 7: Analytics, Tracker, Optimizer & Playbook Refinement (§16 steps 21-25).
--
-- Two columns added to `generations` first: confirmed live that
-- GET /v2/posts/:postSubmissionId returns {postSubmissionId, status,
-- publicUrl} — a bare `status` field and `publicUrl`, NOT the
-- {state:{type,postUrl}} shape approval.poll_publish had guessed before
-- ever calling this for real. We were also never storing the live post's
-- public URL anywhere. And Blotato's analytics endpoints (GET
-- /posts/:id/analytics, GET /analytics) key posts by a different, numeric
-- id — NOT the postSubmissionId UUID we already store — so pulling
-- analytics later requires resolving and storing that numeric id once a
-- post is confirmed published.
alter table generations
  add column if not exists post_url text,
  add column if not exists blotato_numeric_post_id text;
--
-- One `analytics_snapshots` table for BOTH Blotato-API-pulled metrics
-- (Instagram/X) and manually-entered ones (TikTok — no analytics API per
-- §5a) rather than two separate tables as §13 sketches, because §5a's own
-- requirement is that manual entries feed "the same tracker/optimizer
-- logic" — a `source` column does that directly; two tables would mean
-- either duplicating every downstream query or unioning them anyway.
create table if not exists analytics_snapshots (
  id uuid primary key default gen_random_uuid(),
  generation_id uuid not null references generations (id) on delete cascade,
  customer_id uuid not null references customers (id) on delete cascade,
  platform text not null check (platform in ('tiktok', 'instagram', 'x')),
  source text not null check (source in ('api', 'manual')),
  views integer,
  likes integer,
  comments integer,
  shares integer,
  reach integer,
  watch_time integer,
  entered_by uuid references auth.users (id),
  collected_at timestamptz not null default now()
);

create table if not exists optimizer_suggestions (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  platform text not null check (platform in ('tiktok', 'instagram', 'x')),
  trigger_metric text not null,
  proposed_change text not null,
  status text not null default 'pending' check (status in ('pending', 'approved', 'dismissed')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

alter table analytics_snapshots enable row level security;
alter table optimizer_suggestions enable row level security;

create policy "admin full access to analytics_snapshots" on analytics_snapshots
  for all using (auth_is_admin());
create policy "customer reads own analytics_snapshots" on analytics_snapshots
  for select using (customer_id = auth_customer_id());

create policy "admin full access to optimizer_suggestions" on optimizer_suggestions
  for all using (auth_is_admin());
create policy "customer reads own optimizer_suggestions" on optimizer_suggestions
  for select using (customer_id = auth_customer_id());
