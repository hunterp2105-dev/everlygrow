-- Fix: generations.approved_by (added in migration 0007) had no ON DELETE
-- behavior, so deleting an auth user who ever approved a generation would
-- be permanently blocked by this FK (found while cleaning up test data —
-- a real concern for eventual customer account deletion, not just tests).
-- Approver identity is metadata; losing it on account deletion is fine.

alter table generations drop constraint if exists generations_approved_by_fkey;
alter table generations
  add constraint generations_approved_by_fkey
  foreign key (approved_by) references auth.users (id) on delete set null;
