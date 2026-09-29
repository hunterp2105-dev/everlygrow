-- §16 step 50 (timing validation) follow-up: real video-generation timing
-- turned out to range from under 1 minute to over 6 minutes (see
-- docs/phase13-validation-notes.md's timing-validation entry) — nowhere
-- near the packet's previously-stated fixed "~10 minutes", and with no
-- signal between "still normal" and the existing 30-minute hard-failure
-- timeout (generation.GENERATION_STALE_TIMEOUT_MINUTES) to tell admin a
-- job is just running long versus actually stuck. This column lets
-- generation.poll_generation fire that intermediate notification exactly
-- once per generation, rather than re-notifying on every subsequent poll
-- while a job is still (correctly) processing.
alter table generations
  add column if not exists slow_notification_sent_at timestamptz;
