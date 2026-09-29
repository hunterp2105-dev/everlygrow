-- Phase 1: Hub Foundation schema
-- Scope: customers, profiles (auth link + role), module registry (modules,
-- customer_modules), projects, tickets, calendar_events, notifications,
-- credit_usage_log. Module-specific tables (generations, posts, design
-- deliverables, etc.) are deferred to later phases per the build packet.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Customers
-- ---------------------------------------------------------------------------
create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  brand_profile jsonb not null default '{}'::jsonb,
  niche text,
  guardrail_config jsonb not null default '{}'::jsonb,
  plan_caps jsonb not null default '{}'::jsonb,
  holiday_preferences jsonb not null default '{}'::jsonb,
  credit_budget numeric,
  approval_preference text not null default 'manual',
  default_voice_preference text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Profiles: links a Supabase auth user to a role and (for customers) a
-- customer record. One admin account for MVP; role is a plain column so
-- multi-admin support later needs no schema change.
-- ---------------------------------------------------------------------------
create table if not exists profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  role text not null check (role in ('admin', 'customer')),
  customer_id uuid references customers (id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint customer_role_requires_customer_id
    check (role <> 'customer' or customer_id is not null)
);

-- ---------------------------------------------------------------------------
-- Module registry: the mechanism that lets new modules be added later
-- without modifying the Hub or existing modules.
-- ---------------------------------------------------------------------------
create table if not exists modules (
  id uuid primary key default gen_random_uuid(),
  key text not null unique,
  name text not null,
  status text not null check (status in ('active', 'planned')),
  description text,
  created_at timestamptz not null default now()
);

create table if not exists customer_modules (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  module_id uuid not null references modules (id) on delete cascade,
  enabled boolean not null default true,
  caps jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (customer_id, module_id)
);

-- ---------------------------------------------------------------------------
-- Projects/folders: per-customer, auto-organized, span modules
-- ---------------------------------------------------------------------------
create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  module_id uuid references modules (id) on delete set null,
  name text not null,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Tickets / requests
-- ---------------------------------------------------------------------------
create table if not exists tickets (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  subject text not null,
  status text not null default 'open' check (status in ('open', 'pending', 'resolved')),
  created_at timestamptz not null default now()
);

create table if not exists ticket_messages (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets (id) on delete cascade,
  sender_role text not null check (sender_role in ('admin', 'customer')),
  sender_id uuid references auth.users (id) on delete set null,
  body text not null,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Calendar events (Hub-level shell; module-specific linking arrives with
-- the Social and Video Design & Graphic Creator modules)
-- ---------------------------------------------------------------------------
create table if not exists calendar_events (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  module_id uuid references modules (id) on delete set null,
  event_date date not null,
  type text not null,
  title text not null,
  description text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Notifications
-- ---------------------------------------------------------------------------
create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  recipient_type text not null check (recipient_type in ('admin', 'customer')),
  customer_id uuid references customers (id) on delete cascade,
  type text not null,
  message text not null,
  read_status boolean not null default false,
  created_at timestamptz not null default now(),
  constraint customer_recipient_requires_customer_id
    check (recipient_type <> 'customer' or customer_id is not null)
);

-- ---------------------------------------------------------------------------
-- Credit usage log
-- ---------------------------------------------------------------------------
create table if not exists credit_usage_log (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers (id) on delete cascade,
  generation_id uuid,
  credit_cost numeric not null,
  billing_period text not null,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Seed module registry: Social + Video Design & Graphic Creator are active;
-- future modules exist as rows so the Module Map and onboarding screen can
-- render them as "coming soon" without any module-specific code.
-- ---------------------------------------------------------------------------
insert into modules (key, name, status, description) values
  ('social', 'Social', 'active', 'Onboarding-driven, admin-operated, guardrail-checked social content generation and posting via Blotato.'),
  ('video_design_graphic_creator', 'Video Design & Graphic Creator', 'active', 'Flyers, ad creative, and standalone promotional videos delivered as finished files.'),
  ('written_content', 'Written Content', 'planned', 'Blog + email content generation.'),
  ('reddit_community', 'Reddit / Community', 'planned', 'Reddit and community engagement content.'),
  ('backlinks', 'Backlinks / Directory Listings', 'planned', 'Backlink building and directory listing management.'),
  ('web_seo', 'Web + SEO', 'planned', 'Website content and SEO optimization.')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- Row Level Security: every customer's data isolated; only admin has
-- cross-customer visibility.
-- ---------------------------------------------------------------------------
alter table customers enable row level security;
alter table profiles enable row level security;
alter table customer_modules enable row level security;
alter table projects enable row level security;
alter table tickets enable row level security;
alter table ticket_messages enable row level security;
alter table calendar_events enable row level security;
alter table notifications enable row level security;
alter table credit_usage_log enable row level security;
-- modules is reference data, readable by any authenticated user
alter table modules enable row level security;

create or replace function auth_is_admin()
returns boolean
language sql
security definer
stable
as $$
  select exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  );
$$;

create or replace function auth_customer_id()
returns uuid
language sql
security definer
stable
as $$
  select customer_id from profiles where id = auth.uid();
$$;

create policy "modules readable by authenticated" on modules
  for select using (auth.role() = 'authenticated');

create policy "admin full access to customers" on customers
  for all using (auth_is_admin());
create policy "customer reads own record" on customers
  for select using (id = auth_customer_id());

create policy "admin full access to profiles" on profiles
  for all using (auth_is_admin());
create policy "user reads own profile" on profiles
  for select using (id = auth.uid());

create policy "admin full access to customer_modules" on customer_modules
  for all using (auth_is_admin());
create policy "customer reads own customer_modules" on customer_modules
  for select using (customer_id = auth_customer_id());

create policy "admin full access to projects" on projects
  for all using (auth_is_admin());
create policy "customer reads own projects" on projects
  for select using (customer_id = auth_customer_id());

create policy "admin full access to tickets" on tickets
  for all using (auth_is_admin());
create policy "customer full access to own tickets" on tickets
  for all using (customer_id = auth_customer_id());

create policy "admin full access to ticket_messages" on ticket_messages
  for all using (auth_is_admin());
create policy "customer full access to own ticket_messages" on ticket_messages
  for all using (
    ticket_id in (select id from tickets where customer_id = auth_customer_id())
  );

create policy "admin full access to calendar_events" on calendar_events
  for all using (auth_is_admin());
create policy "customer reads own calendar_events" on calendar_events
  for select using (customer_id = auth_customer_id());

create policy "admin full access to notifications" on notifications
  for all using (auth_is_admin());
create policy "customer reads own notifications" on notifications
  for select using (customer_id = auth_customer_id());
create policy "customer updates own notification read_status" on notifications
  for update using (customer_id = auth_customer_id());

create policy "admin full access to credit_usage_log" on credit_usage_log
  for all using (auth_is_admin());
create policy "customer reads own credit_usage_log" on credit_usage_log
  for select using (customer_id = auth_customer_id());
