-- Phase 8: Calendar (§16 steps 26-27).
--
-- generations never got a dedicated "when did this actually go live"
-- timestamp — only approved_at (when the customer clicked approve, which
-- happens moments before the real publish call, not the same instant).
-- The calendar needs an accurate post date, so adding one now rather than
-- approximating with approved_at.
alter table generations add column if not exists published_at timestamptz;
--
-- Deliberately NOT writing posts/deliverables into the Phase 1
-- `calendar_events` shell table — that would mean dual-writing and keeping
-- two records in sync for no benefit, when generations/design_deliverables
-- already have their own dates and are the source of truth. The calendar
-- view (app/lib/calendar.py) computes posts/deliverables on the fly from
-- those tables. `calendar_events` stays as-is, unused for now — dropping
-- it isn't worth a migration for a table that's harmless sitting empty.
--
-- What's genuinely new: a holidays/awareness-day REFERENCE table (§13).
-- Holidays recur annually, so storing a fixed date would go stale — this
-- stores month/day and computes each year's actual occurrence at query
-- time (see calendar.py).
create table if not exists holidays (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  month integer not null check (month between 1 and 12),
  day integer not null check (day between 1 and 31),
  is_general boolean not null default true,
  niche_tags jsonb not null default '[]'::jsonb,
  content_idea_prompt text,
  created_at timestamptz not null default now()
);

alter table holidays enable row level security;

create policy "holidays readable by authenticated" on holidays
  for select using (auth.role() = 'authenticated');
create policy "admin writes holidays" on holidays
  for insert with check (auth_is_admin());
create policy "admin updates holidays" on holidays
  for update using (auth_is_admin());
create policy "admin deletes holidays" on holidays
  for delete using (auth_is_admin());

-- Seed: major U.S. holidays (general) + a handful of niche-tagged
-- awareness days matching the five niches seeded in migration 0002.
insert into holidays (name, month, day, is_general, niche_tags, content_idea_prompt)
select * from (values
  ('New Year''s Day', 1, 1, true, '[]'::jsonb, 'A fresh-start message for the new year — goals, routines, or a "here''s what we''re bringing to this year" post.'),
  ('Valentine''s Day', 2, 14, true, '[]'::jsonb, 'A warm, community-facing post — appreciation for customers/clients, not necessarily romance-themed unless the niche fits.'),
  ('Independence Day', 7, 4, true, '[]'::jsonb, 'A community/local-pride post tied to the holiday, staying brand-appropriate.'),
  ('Thanksgiving', 11, 27, true, '[]'::jsonb, 'A gratitude post — thank customers, staff, or the community.'),
  ('Christmas', 12, 25, true, '[]'::jsonb, 'A warm seasonal greeting, timed with any holiday hours/closures.'),
  ('National Real Estate Investors Day', 3, 10, false, '["Real Estate Agents"]'::jsonb, 'A market-update or "why now is a good time to buy/sell" angle.'),
  ('National Homeownership Month kickoff', 6, 1, false, '["Real Estate Agents"]'::jsonb, 'A homeownership-education post — first-time buyer tips or local market snapshot.'),
  ('National HVAC Tech Day', 8, 3, false, '["Home Services (HVAC/Plumbing/Electrical)"]'::jsonb, 'A behind-the-scenes or appreciation post for the technicians who do the work.'),
  ('National Preparedness Month kickoff', 9, 1, false, '["Home Services (HVAC/Plumbing/Electrical)"]'::jsonb, 'A seasonal-readiness reminder — heating/cooling checkup before the season changes.'),
  ('National Restaurant Employee Day', 5, 5, false, '["Restaurants & Cafes"]'::jsonb, 'A staff-appreciation or behind-the-scenes kitchen post.'),
  ('National Food Day', 10, 24, false, '["Restaurants & Cafes"]'::jsonb, 'A signature-dish spotlight or a "what food means to us" post.'),
  ('National Fitness Day', 5, 1, false, '["Fitness (Personal Trainers/Studios)"]'::jsonb, 'A challenge/trial-offer post or a client-transformation spotlight.'),
  ('New Year fitness resolution season', 1, 2, false, '["Fitness (Personal Trainers/Studios)"]'::jsonb, 'A "new year, new habits" post — approachable, not intimidating.'),
  ('National Wellness Month kickoff', 8, 1, false, '["Health & Wellness (Med Spa/Chiropractic/Dental)"]'::jsonb, 'A patient-education post on a treatment or wellness habit, compliant/non-absolute claims per guardrails.'),
  ('National Dental Hygiene Month kickoff', 10, 1, false, '["Health & Wellness (Med Spa/Chiropractic/Dental)"]'::jsonb, 'A "what to expect at your visit" or oral-health-tip post.')
) as seed(name, month, day, is_general, niche_tags, content_idea_prompt)
where not exists (select 1 from holidays where holidays.name = seed.name);
