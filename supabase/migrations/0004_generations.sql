-- Phase 3: Social module generation tracking (§13 `generations` table).
-- One row per Blotato "creation" job, regardless of whether the underlying
-- template produces an image, slideshow, video, or video-with-voiceover —
-- Blotato's own API unifies all of these into the same async
-- queueing -> ... -> done job shape, so this table (and the poller that
-- updates it) is deliberately generic, not one table/poller per content type.

create table if not exists generations (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  module_id uuid not null references modules (id) on delete cascade,
  channel text,
  template_id text not null,
  template_description text,
  prompt text,
  inputs jsonb not null default '{}'::jsonb,
  voice_name text,
  blotato_creation_id text,
  blotato_status text,
  status text not null default 'processing' check (status in ('processing', 'ready', 'failed')),
  media_url text,
  image_urls jsonb,
  retry_count integer not null default 0,
  edit_count integer not null default 0,
  estimated_credit_cost numeric,
  niche_playbook_version_used integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table generations enable row level security;

create policy "admin full access to generations" on generations
  for all using (auth_is_admin());
create policy "customer reads own generations" on generations
  for select using (customer_id = auth_customer_id());
