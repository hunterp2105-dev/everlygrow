-- §16 video-naturalness follow-up (2026-08-27): the "AI Selfie Talking
-- Video with Consistent Character" template synthesizes its presenter
-- from a text description rather than requiring real footage (see the
-- retracted b-roll default in app/lib/blotato_client.py). A customer's
-- video "spokesperson" should stay consistent across THEIR posts (hence
-- the template's own name) while naturally differing between customers —
-- so the character description lives per-customer, set once by admin,
-- reused automatically, and still overridable per-generation on the
-- Generate (Social) screen.
alter table customers
  add column if not exists default_character_description text;
