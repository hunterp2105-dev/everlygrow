# EverlyGrow — Phase 12 (Testing)

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in your Supabase project's URL, anon key, service role key (Project Settings → API), your Blotato API key (Settings → API in the Blotato app), and your Anthropic API key (powers the guardrail pipeline).
3. Apply the migrations, in order, to your Supabase project (SQL Editor, or the Supabase CLI):
   - `supabase/migrations/0001_hub_foundation.sql`
   - `supabase/migrations/0002_onboarding_niche_playbooks.sql`
   - `supabase/migrations/0003_warmup_config_and_retry.sql`
   - `supabase/migrations/0004_generations.sql`
   - `supabase/migrations/0005_design_deliverables.sql`
   - `supabase/migrations/0006_guardrails.sql`
   - `supabase/migrations/0007_approval_and_publish.sql`
   - `supabase/migrations/0008_approved_by_on_delete_set_null.sql`
   - `supabase/migrations/0009_analytics_optimizer.sql`
   - `supabase/migrations/0010_calendar_holidays.sql`
   - `supabase/migrations/0011_notifications_and_credits.sql`
4. Create the first admin account:
   - In Supabase Auth, create a user (email + password).
   - In the `profiles` table, insert a row: `id` = that user's auth UID, `role` = `admin`, `customer_id` = `null`.
5. Run the app: `streamlit run app/main.py`

The service role key, Blotato key, and Anthropic key are server-side only. The service role key is also used (deliberately, with an explicit ownership check) from the customer-facing approval flow — see `app/lib/approval.py`'s module docstring before touching that pattern.

## What's here

**Phase 1 — Hub Foundation:** Streamlit app shell, Supabase-authenticated login, role-gated routing; Hub data model + module registry; design system per §18.

**Phase 2 — Onboarding & Niche Playbooks:** free-text niche matching with a general-purpose fallback; Blotato account pools/social accounts with warm-up tracking; idempotent, resumable onboarding (`onboarding_intakes` + Resume Onboarding screen); real accept-invite/set-password flow for customer logins.

**Phase 3 — Social Module (generation):** `generations` table + `app/lib/generation.py` — one generic start/poll/notify path for every Blotato template type; `app/lib/blotato_client.py` REST wrapper; admin **Generate (Social)** screen.

**Phase 4 — Video Design & Graphic Creator:** `design_deliverables` wraps the same generation engine — flyer/ad and standalone-video requests, §7 weekly caps (soft, flag-not-block), admin **Design Requests** screen. Genuinely separate module from Social (own request path, own table), sharing the underlying engine deliberately.

**Phase 5 — Guardrails, QC & Failure Handling:** `app/lib/guardrails.py` — 4 of the 6 §6 categories go to a real Claude call (brand/tone, content safety, factual/claims, competitor/legal-sensitive); voice-selection compliance is a deterministic code check; quality bar is explicitly deferred per §6's own guidance, not automated. Wired into `generation.poll_generation`'s ready-transition — same call site for both modules. Retry-then-escalate on flag/fail, with a shared `app/lib/retry_policy.py` distinguishing permanent (4xx) from transient (429/5xx) failures — used by both guardrail-engine failures and publish failures. Admin **Escalation Queue** screen.

**Phase 6 — Approval & Posting:** approval state lives on the same `generations` row as guardrail state. Customer-facing **Approval Queue** (`customer_hub.py`) — approve dispatches to a real Blotato publish (social) or marks delivered (design). **Publishing is real, not stubbed** — first live post went out 2026-07-27 after an explicit human review-and-approve step outside the normal flow (`https://www.tiktok.com/@stackdifferrent/video/7667329117125217550`). Caps enforced (posts/day, soft). One deliberate RLS bypass: `generations` only grants customers `SELECT`, so the approval write goes through the service-role client with an explicit ownership check (`approval._verify_ownership`) rather than through the customer's own RLS session — documented in `approval.py`'s module docstring, isolated to just these two functions.

**Phase 7 — Analytics, Tracker, Optimizer & Playbook Refinement:**
- `analytics_snapshots`: one table for both Blotato-API-pulled metrics and manually-entered ones (§5a's own requirement — manual entries feed "the same tracker/optimizer logic" — a `source` column does that directly).
- `app/lib/analytics.py`: resolves Blotato's numeric post id (a different id than the `postSubmissionId` we store — see Known Issues), pulls real API analytics where available, `top_performers()` tags by style/template/niche.
- Admin **Analytics** screen: pull button for API-covered platforms, manual entry form for TikTok.
- `app/lib/optimizer.py`: rule-based (not ML, per §14) per-platform underperformance detection against a customer's own prior average; needs 3+ snapshots on one platform for a baseline. Admin **Optimizer** screen: approve/dismiss queue, advisory only.
- `app/lib/playbook_refinement.py`: surfaces real performance data per niche back to admin (top performers, template frequency) — admin decides whether/how to refine the playbook; nothing auto-edits `content_pillars`. Admin **Playbooks** screen.

Guardrail accuracy findings (false positives/negatives, especially the subjective categories) are logged on an ongoing basis in `docs/guardrail-accuracy-notes.md`, feeding Phase 13 step 47.

**Phase 8 — Calendar:** `app/lib/calendar.py` merges real posts/deliverables (computed live, not duplicated into `calendar_events`) with a recurring holiday/awareness-day reference table; customer (read-only, own data) and admin (cross-customer) views, with content-idea shortcuts into Generate/Design Requests.

**Phase 9 — Notifications & Cost Tracking:** `app/lib/notifications.py` centralizes every trigger (§9) with in-app list/mark-read and a stubbed email dispatch for time-sensitive types; `app/lib/credits.py` tracks estimated per-generation cost (placeholder units — Blotato doesn't return real cost per job) against an optional per-customer budget, and Blotato pool-cap approaching warnings.

**Phase 10 — Admin Tools:** full customer list with active-modules + per-customer config; real ticket inbox (both directions — customer creates/replies, admin replies, notifications fire each way); Escalation Queue; **Module Map** (Hub + module blocks, generic/data-driven — see Phase 12's registry test); **Niche Playbook Library** (add/edit + performance-data refinement view, non-gating for niches with zero data yet).

**Phase 11 — Polish (design system v2):** dark-mode-first, graphite base, one electric-blue accent reserved strictly for active/in-progress states (never resting ones) — see `docs/social-generator-build-packet.md` §18.1 v2. The approval-stamp motif became a flat CI-badge-style status badge; the Module Map became an actual node/circuit-diagram SVG (`app/lib/theme.py::module_map_svg`).

**Phase 12 — Testing:** real pytest suite in `tests/` (see **Testing** below) covering every item in §16 steps 36-45 against the live Supabase project (and real Blotato/Anthropic calls where safe). Two real findings/fixes came out of writing it:
- **Video/generation timeout gap, now fixed:** nothing previously marked a generation `failed` if Blotato's job simply never reached a terminal status — `poll_generation` would no-op on it forever. Fixed with a 30-minute staleness check (`app/lib/generation.py::GENERATION_STALE_TIMEOUT_MINUTES`, well past the packet's documented ~10-minute video render ceiling) in the one place a generation's live status is already re-checked.
- **Guardrail over-flagging pattern found and logged, not yet fixed:** ordinary marketing copy ("made fresh daily," a routine real estate listing, a compliantly-hedged health claim) gets flagged on `factual_claims_accuracy` across unrelated niches under standard sensitivity — see `docs/guardrail-accuracy-notes.md`'s 2026-08-12 entry. Likely cause: the category's own instruction wording ("any unverifiable or risky claims") reads as "any unverifiable claims" in practice. Left for Phase 13's guardrail calibration (§17), not fixed here — the three affected tests are marked `xfail` (not loosened) so they'll visibly flip once retuned.

## Testing

`tests/` is a real pytest suite exercising the live Supabase project (RLS included, via real signed-in sessions — not just the service-role client) and real Blotato/Anthropic calls wherever that's safe. One standing exception: **Blotato's real publish endpoint (`create_post`) is never called live by this suite** — that's the same Phase 6 rule this whole build has followed (it posts to a customer's real connected account). Publish-path tests mock only that one HTTP call and run everything else — retry counting, escalation, notifications — for real.

```
pip install -r requirements.txt
python -m pytest tests/ -v
```

Full run takes ~5 minutes (the cross-module test does two real Blotato image generations; the guardrail suite makes ~10 real Claude calls) and creates/cleans up its own throwaway customers, auth users, and modules — nothing persists in Supabase after a run except appended entries in `docs/guardrail-accuracy-notes.md`. `tests/test_module_registry.py` is the load-bearing one: it proves a brand-new module can be added (data only) and picked up by onboarding, the Module Map, and the customer Hub with zero changes to any existing module's code — the architecture's central claim (§4a).

## Known issues

- **Blotato voice generation is unreliable — cause not fully confirmed.** Any voice parameter on the "AI Video with AI Voice" template failed every time tried (3 attempts, zero error detail), while the identical request without one succeeded reliably. Plan-tier gating ruled out. A separate test hit `insufficient-credits` with a real error message, meaning credit exhaustion may have confounded the earlier unexplained failures. Support ticket filed with Blotato (`help@blotato.com`) with the full repro and specific creation IDs. Not blocking — generation without voice works reliably. The Voice selector is disabled (not just warned) on both Generate screens until resolved.
- **TikTok analytics sync via Blotato's API is unreliable, root cause unconfirmed.** Measured actual sync rates across every post on two connected accounts: `@stackdifferrent` (our test account) synced 5/13 posts (38%); `@lifeandlegacybooks` synced 35/50 (70%). The obvious explanation — personal vs. Business account permission tier — was checked directly against each account's real TikTok settings and **ruled out**: both are confirmed Business accounts. No other pattern found either (not post age/sync-lag, not content type — video and photo posts on the same account sync at similar rates to each other). This is a genuinely unexplained platform-side inconsistency, not something fixable from our side. Manual entry (§5a) is the dependable path regardless of account type or configuration — treat it as primary for TikTok, not a rare fallback. Included in the Blotato support ticket.
- **`GET /v2/posts` is not a real history** — confirmed live it only ever returns a handful of very-recent items (last ~hour), no matter the limit, with no way to page further back. `GET /v2/published-posts` is the actual way to find an older post by URL, and its `offset` pagination is not a simple date sort (a 13-day-old post surfaced at `offset=25`, not near where date order would predict) — `analytics.resolve_numeric_post_id` does a bounded linear scan (5 pages / 500 posts) rather than assuming any ordering.

## Known simplifications

- **Onboarding is admin-run, not self-serve.**
- **No true autocomplete widget for niche input** — free text plus a reference list.
- **Provisioning is idempotent but not transactional** — resumable via Resume Onboarding, not auto-rolled-back.
- **Pool assignment is single-pool-aware but not multi-pool-smart.**
- **Generation/publish/analytics are admin-triggered and polled manually** (buttons), not a background worker — fine for MVP volume, would need a real job queue at scale.
- **Optimizer is rule-based, not ML** — per §14, ML-driven optimization is explicitly a later phase.
- **Playbook refinement is data-surfacing, not auto-editing** — admin decides what changes, matching §4b's framing of refinement as admin-driven.
- **Not all defined Social caps are actually checked.** `DEFAULT_CAPS["social"]` (`app/lib/caps.py`) defines `platforms_per_customer`, `media_uploads_images`, `media_uploads_videos`, and `chat_edit_regenerations_per_generation` — only `posts_per_day` is read anywhere (the Generate screen). The other three are stored per-customer at onboarding but nothing checks usage against them. Video Design & Graphic Creator's two caps are both fully wired (`design.check_cap_usage`). Caps are soft/advisory by design either way, so nothing is blocked by this gap — flagged here since a stored cap number that's never checked could otherwise look load-bearing when it isn't.
