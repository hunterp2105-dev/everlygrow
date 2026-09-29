-- Phase 9: Notifications & Cost Tracking (§16 steps 28-29).
--
-- credit_usage_log and notifications.read_status already exist from
-- Phase 1 — nothing wrote to either until now. Adding email-delivery
-- tracking to notifications, mirroring the job-tracking pattern already
-- used three times in this codebase (generation status, guardrail_status,
-- publish_status): same shape, new state machine.
alter table notifications
  add column if not exists email_status text not null default 'not_applicable'
    check (email_status in ('not_applicable', 'pending', 'sent', 'failed')),
  add column if not exists email_sent_at timestamptz;
