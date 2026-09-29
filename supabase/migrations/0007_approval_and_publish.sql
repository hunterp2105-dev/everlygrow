-- Phase 6: Approval & Posting (§16 steps 19-20).
-- Approval state lives on the shared `generations` row, same as guardrail
-- state (Phase 5) — one queue, one set of columns, covering Social and
-- Video Design & Graphic Creator alike. What "approved" *does* differs by
-- module (publish vs. mark-delivered), handled in app/lib/approval.py, not
-- by separate schema per module.

alter table generations
  add column if not exists approval_status text not null default 'pending_review'
    check (approval_status in ('pending_review', 'approved', 'changes_requested')),
  add column if not exists approved_at timestamptz,
  add column if not exists approved_by uuid references auth.users (id),
  add column if not exists customer_feedback text,
  -- Social-only: which connected account this would post to, and the
  -- caption/text to accompany it. Set by admin at generation request time
  -- (see admin_panel._render_generate_social) so everything needed to
  -- publish already exists by the time a customer approves.
  add column if not exists target_social_account_id uuid references social_accounts (id),
  add column if not exists post_caption text,
  -- Publish job tracking (mirrors the generation/guardrail job-tracking
  -- pattern already used twice in this codebase — same shape, new state
  -- machine): Blotato's POST /posts returns a postSubmissionId to poll.
  add column if not exists blotato_post_id text,
  add column if not exists publish_status text not null default 'not_published'
    check (publish_status in ('not_published', 'publishing', 'published', 'failed')),
  add column if not exists publish_retry_count integer not null default 0;
