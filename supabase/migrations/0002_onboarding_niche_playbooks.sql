-- Phase 2: Onboarding & Niche Playbooks
-- Scope: niche_playbooks (free-text niche input with a general-purpose
-- fallback, per the updated §4b), blotato_account_pools + social_accounts
-- (needed for warm-up tracking and the admin account-connection workflow),
-- customers.niche_playbook_id link.

-- ---------------------------------------------------------------------------
-- Niche playbooks. `niche` is free text (matches customers.niche); there is
-- no fixed enum of niches — onboarding accepts any business's stated niche
-- and falls back to the single is_default row when nothing matches.
-- ---------------------------------------------------------------------------
create table if not exists niche_playbooks (
  id uuid primary key default gen_random_uuid(),
  niche text not null,
  is_default boolean not null default false,
  content_pillars jsonb not null default '[]'::jsonb,
  best_practices text,
  posting_cadence_guidance text,
  example_angles jsonb not null default '[]'::jsonb,
  refined_from_data boolean not null default false,
  version integer not null default 1,
  last_updated timestamptz not null default now()
);

-- Only one default (general-purpose) playbook may exist.
create unique index if not exists niche_playbooks_single_default
  on niche_playbooks ((is_default))
  where is_default;

-- Case-insensitive uniqueness among named (non-default) niches, so onboarding
-- match lookup ("does this niche already have a playbook?") is unambiguous.
create unique index if not exists niche_playbooks_niche_lower_unique
  on niche_playbooks (lower(niche))
  where not is_default;

alter table customers
  add column if not exists niche_playbook_id uuid references niche_playbooks (id);

-- ---------------------------------------------------------------------------
-- Blotato account pools (§5 scaling strategy) and social accounts (§13).
-- Needed now because onboarding assigns each new customer's social accounts
-- to a pool, and the admin connection/warm-up workflow tracks them.
-- ---------------------------------------------------------------------------
create table if not exists blotato_account_pools (
  id uuid primary key default gen_random_uuid(),
  plan_tier text not null check (plan_tier in ('creator', 'agency')),
  connected_account_count integer not null default 0,
  cap integer not null,
  tiktok_posts_used_today integer not null default 0,
  tiktok_daily_cap integer,
  monthly_cost numeric,
  created_at timestamptz not null default now()
);

create table if not exists social_accounts (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  platform text not null check (platform in ('tiktok', 'instagram', 'x')),
  blotato_account_id text,
  blotato_pool_id uuid references blotato_account_pools (id),
  source text not null check (source in ('existing', 'new')),
  warm_up_status text not null default 'pending_connection'
    check (warm_up_status in ('pending_connection', 'not_required', 'warming', 'complete')),
  warm_up_start_date date,
  connected_by_admin_at timestamptz,
  created_at timestamptz not null default now(),
  unique (customer_id, platform)
);

-- ---------------------------------------------------------------------------
-- Seed: one Agency-tier pool (per §5, Creator/Agency from the start — Agency
-- chosen here for the higher connection cap headroom during MVP testing).
-- ---------------------------------------------------------------------------
insert into blotato_account_pools (plan_tier, cap, tiktok_daily_cap)
select 'agency', 100, null
where not exists (select 1 from blotato_account_pools);

-- ---------------------------------------------------------------------------
-- Seed: general-purpose default playbook + five starting niches.
-- Draft content — a starting point for admin refinement via the future
-- Playbook Library screen (Phase 10), not finished IP.
-- ---------------------------------------------------------------------------
insert into niche_playbooks (niche, is_default, content_pillars, best_practices, posting_cadence_guidance, example_angles)
select
  'General',
  true,
  $j$["Behind-the-scenes / how we work", "Customer results & testimonials", "Educational tips relevant to the business", "Community & local presence", "Offers & calls to action"]$j$::jsonb,
  $t$Post consistently rather than frequently; lead with a hook in the first 2 seconds of video or first line of caption; always include a clear call to action; mix short-form video with static/carousel posts.$t$,
  $t$3-4 posts per week across primary platforms, at least 1 video per week.$t$,
  $j$["A day in the life at the business", "Before/after or results showcase", "Quick tip related to your service", "Customer shoutout or review highlight"]$j$::jsonb
where not exists (select 1 from niche_playbooks where is_default);

insert into niche_playbooks (niche, content_pillars, best_practices, posting_cadence_guidance, example_angles)
select
  'Real Estate Agents',
  $j$["Listing showcases & walkthroughs", "Local market updates & neighborhood spotlights", "Buyer/seller education", "Client testimonials & closings", "Agent personality & trust-building"]$j$::jsonb,
  $t$Video walkthroughs consistently outperform photos; lead listings with the single best feature; pair market-data posts with a personal take, not just numbers; celebrate closings publicly (with client permission) to build social proof.$t$,
  $t$4-5 posts per week; new listings posted within 24 hours of going live.$t$,
  $j$["Listing walkthrough with a hook (\"You won't believe this kitchen\")", "5 things to know before buying in this neighborhood", "What your budget gets you in this city right now", "Client testimonial after closing"]$j$::jsonb
where not exists (select 1 from niche_playbooks where lower(niche) = lower('Real Estate Agents'));

insert into niche_playbooks (niche, content_pillars, best_practices, posting_cadence_guidance, example_angles)
select
  'Home Services (HVAC/Plumbing/Electrical)',
  $j$["Emergency/urgent-need visibility", "Educational maintenance tips", "Job showcases (before/after)", "Trust signals (licensed, insured, reviews)", "Seasonal readiness reminders"]$j$::jsonb,
  $t$Lead with the problem the viewer is having, not the company; before/after visuals build trust fast; seasonal timing matters heavily (AC content pre-summer, heating pre-winter); always surface licensing/certifications somewhere in the profile or content, not just once.$t$,
  $t$2-3 posts per week, with seasonal spikes timed 4-6 weeks ahead of peak demand.$t$,
  $j$["Before/after job photos", "Warning signs your system needs service", "Quick maintenance tip homeowners can do themselves", "Why licensed & insured matters"]$j$::jsonb
where not exists (select 1 from niche_playbooks where lower(niche) = lower('Home Services (HVAC/Plumbing/Electrical)'));

insert into niche_playbooks (niche, content_pillars, best_practices, posting_cadence_guidance, example_angles)
select
  'Restaurants & Cafes',
  $j$["Menu & new item highlights", "Behind-the-scenes kitchen/prep", "Atmosphere & customer experience", "Local events & specials", "Staff personality"]$j$::jsonb,
  $t$Food video (close-up, motion, sizzle) consistently outperforms static photos; post close to meal times when audiences are hungry and deciding; showcase limited-time items with urgency; feature real customers/staff over stock-feeling content.$t$,
  $t$4-6 posts per week; food-focused content daily is common for high performers.$t$,
  $j$["New menu item close-up video", "Behind-the-scenes prep of a signature dish", "Weekend special or event announcement", "Regular customer or staff spotlight"]$j$::jsonb
where not exists (select 1 from niche_playbooks where lower(niche) = lower('Restaurants & Cafes'));

insert into niche_playbooks (niche, content_pillars, best_practices, posting_cadence_guidance, example_angles)
select
  'Fitness (Personal Trainers/Studios)',
  $j$["Client transformations & results", "Workout tips & form demos", "Class/session energy & atmosphere", "Motivation & mindset content", "Offers (trial classes, challenges)"]$j$::jsonb,
  $t$Short workout-demo clips with clear form cues perform best; transformation content needs real client permission and honest framing; energy/atmosphere content builds desire to join, not just skill-building content; a recurring challenge or trial offer gives content a natural call to action.$t$,
  $t$4-5 posts per week, mixing demo, motivation, and results content.$t$,
  $j$["Quick form-check or common mistake fix", "Client transformation story", "Inside a class - energy and community", "This week's challenge or trial offer"]$j$::jsonb
where not exists (select 1 from niche_playbooks where lower(niche) = lower('Fitness (Personal Trainers/Studios)'));

insert into niche_playbooks (niche, content_pillars, best_practices, posting_cadence_guidance, example_angles)
select
  'Health & Wellness (Med Spa/Chiropractic/Dental)',
  $j$["Treatment education (what it is, what to expect)", "Real results (with appropriate consent/compliance)", "Practitioner credibility & credentials", "Patient experience & comfort", "Promotions & new patient offers"]$j$::jsonb,
  $t$This niche requires the highest guardrail sensitivity for claims accuracy — avoid definitive medical/outcome claims, use compliant language ("may help with", not "cures"); credentials and licensing should be visible; comfort/anxiety-reduction messaging matters more here than in most niches; results content must have documented patient consent.$t$,
  $t$3-4 posts per week; educational content should outweigh promotional content roughly 2:1.$t$,
  $j$["What to expect during your first visit", "Common myth about a treatment, debunked", "Meet the practitioner", "Patient experience walkthrough (with consent)"]$j$::jsonb
where not exists (select 1 from niche_playbooks where lower(niche) = lower('Health & Wellness (Med Spa/Chiropractic/Dental)'));

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table niche_playbooks enable row level security;
alter table blotato_account_pools enable row level security;
alter table social_accounts enable row level security;

create policy "niche_playbooks readable by authenticated" on niche_playbooks
  for select using (auth.role() = 'authenticated');
create policy "admin writes niche_playbooks" on niche_playbooks
  for insert with check (auth_is_admin());
create policy "admin updates niche_playbooks" on niche_playbooks
  for update using (auth_is_admin());
create policy "admin deletes niche_playbooks" on niche_playbooks
  for delete using (auth_is_admin());

create policy "admin full access to blotato_account_pools" on blotato_account_pools
  for all using (auth_is_admin());

create policy "admin full access to social_accounts" on social_accounts
  for all using (auth_is_admin());
create policy "customer reads own social_accounts" on social_accounts
  for select using (customer_id = auth_customer_id());
