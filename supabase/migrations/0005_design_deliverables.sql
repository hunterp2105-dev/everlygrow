-- Phase 4: Video Design & Graphic Creator module.
-- Reuses Phase 3's generic generation engine (generations table,
-- generation.py's start/poll/notify) unchanged — this table only adds the
-- module-specific wrapper: which generation produced a flyer/ad/video
-- deliverable, and its delivery status. Functionally separate from Social's
-- own video generator (different module_id on the shared generations row,
-- different request path/UI), even though both call the same Blotato API.

create table if not exists design_deliverables (
  id uuid primary key default gen_random_uuid(),
  generation_id uuid not null references generations (id) on delete cascade,
  customer_id uuid not null references customers (id) on delete cascade,
  type text not null check (type in ('flyer', 'ad', 'video')),
  occasion text,
  status text not null default 'draft' check (status in ('draft', 'approved', 'delivered')),
  delivered_at timestamptz,
  file_url text,
  created_at timestamptz not null default now()
);

alter table design_deliverables enable row level security;

create policy "admin full access to design_deliverables" on design_deliverables
  for all using (auth_is_admin());
create policy "customer reads own design_deliverables" on design_deliverables
  for select using (customer_id = auth_customer_id());
