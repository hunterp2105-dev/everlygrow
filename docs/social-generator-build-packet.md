# AI Content Generator — Build Packet
**Status:** Draft v9 — for review before handoff to Claude Code
**Prepared for:** Antigravity IDE + Claude Code
**Source:** AI Master Handbook (Google Sheet) + stakeholder interview + whiteboard architecture sketch

---

## 1. Vision

A premium, branded, fully-managed AI content service that helps customers reach people across the internet, not just social platforms. Customers don't touch a generator at all — they tell us their brand, goals, and requests, and we produce and publish professional, on-brand, consistently-published content on their behalf. The product is built around a **central Hub** (dashboard/ticketing, where the customer works) with **independently addable service modules** plugged into it. **MVP builds two modules: Social, and Video Design & Graphic Creator.** Written Content (blog + email), Reddit/Community, Backlinks/Directory Listings, and Web+SEO are added later, one at a time, without rebuilding the core. The product must feel premium: high-quality, on-brand, and genuinely strategic per industry — not generic AI output.

**Core business proof point for MVP:** prove the pipeline — onboarding → request/brand intake → niche-informed, admin-operated generation → guardrail/QC → customer approval → publish/deliver → performance tracking → smarter regeneration — works end-to-end for one real or test customer, across the Social and Video Design & Graphic Creator modules, before adding more modules, more customers, or billing.

---

## 2. Business Model

A single, full-service tier — customers never operate the generator themselves.

| What the customer does | What we do | Positioning |
|---|---|---|
| Onboards (brand, goals, niche), submits requests/questions/media via the Hub dashboard, approves content before it goes out | Operates the generator on their behalf across every module they have, applies their brand and niche strategy, runs it through guardrails, prepares content for approval, publishes/delivers approved content, monitors performance | Premium, full-service, "we handle it entirely" — priced accordingly |

No self-serve tier, no tier-switching. The customer's Hub dashboard is a request/approval/calendar interface, never a generator.

---

## 3. User Roles & Views

1. **Customer view:** Onboarding → Hub dashboard (requests/questions/media upload, scoped to their active modules) → calendar → approval queue → published/analytics. No generator access, ever.
2. **Admin/Owner view (you):** All customers, their profiles and active modules, full generator access across every module, ticket handling, guardrail overrides, analytics/optimizer, caps/limits, cross-customer calendar, Blotato pool status, credit/cost usage, content-draft delivery, niche playbook library.

---

## 4. Core Architecture & Tech Stack

- **App shell / frontend:** Streamlit
- **Auth & database:** Supabase (or Firebase Auth as fallback)
- **Social module — generation + posting engine:** Blotato API/MCP — AI text, image, and video generation for social platform content (short-form, tied to a posting schedule), ElevenLabs voiceover, cross-posting, analytics collection. Our app is a **branded orchestration layer** on top of it, operated exclusively by admin. This is the same full pipeline discussed throughout — nothing about Social changes here. See §5 for account scaling.
- **Video Design & Graphic Creator module — standalone deliverables:** produces flyers, ad creative, and standalone promotional/marketing videos — **not tied to a posting schedule, and functionally separate from Social's own video generator.** Social's video generation exists to feed scheduled platform posts (short clips for TikTok/Reels-style content); this module exists to produce finished creative assets a customer can use however they need (print, their own ads, their website, a standalone video). Both may call similar underlying Blotato generation capabilities, but they're organized as two distinct modules with separate request types, caps, and delivery methods — never conflate them in the build.
- **Chat-based editing layer:** Claude API — interprets admin's natural-language edit requests and translates them into new generation calls, for any module. Capped at a set number of regenerations per generation (§7).
- **Video generation stance (both modules):** Quality over speed. **Real timing (§16 step 50, corrected from an earlier fixed "~10 minutes" assumption): actual render time varies significantly run to run rather than sitting at a reliable fixed value.** Direct, self-consistent timing across this build's own real video generations (n=4, a small sample — treat as directional) ranged from under 1 minute to just over 6 minutes; no run observed reached anywhere near 10 minutes, though slower runs under different load or queue conditions can't be ruled out from this sample alone. Full data in `docs/phase13-validation-notes.md`'s timing-validation entry. Handled asynchronously: a "ready" notification when done (§9), plus an intermediate "still processing, taking longer than usual" notification for jobs running past `GENERATION_SLOW_WARNING_MINUTES` (6 minutes) without yet failing — distinct from the 30-minute hard-failure timeout, so admin isn't left guessing whether a long-running job is stuck or just slow.
- **Analytics/self-learning tracker:** Pulls Blotato's analytics API per social post, tags by style/template/niche, surfaces top performers. **Gap: TikTok analytics sync via Blotato's API is unreliable, with sync rates varying meaningfully between accounts (38%-70% in our testing) even when both are confirmed Business accounts — root cause unconfirmed.** (Also no analytics API for YouTube, Pinterest, LinkedIn.) Manual entry (§5a) remains the dependable fallback regardless of account type or configuration. Reporting has a lag (~2 hours to 1 day) on top of the sync-rate issue. Video Design & Graphic Creator deliverables don't have performance analytics (they're finished assets, not published/tracked posts).
- **Per-platform optimizer:** Watches social platform performance, auto-suggests strategy changes for admin approval. Applies to Social only.
- **Voice selection:** Admin picks from Blotato's stock voice library. No custom cloning in MVP.
- **Data isolation & security:** Every customer's data isolated; only admin has cross-customer visibility; secrets server-side only.

---

## 4a. Hub & Modules Architecture (the core structural decision)

Matches the whiteboard sketch: a fixed **Hub** at the center, with **independent modules** plugged in, so new modules can be added over time without touching what already exists.

**The Hub (built once):** customer accounts, onboarding, brand profile, niche, dashboard, ticketing/requests, calendar, notifications, approval queue (works the same regardless of which module content came from), admin panel, credit/cost tracking, shared guardrail engine.

**MVP Modules (built now):**
- **Social** — the full pipeline as discussed throughout: onboarding-driven, admin-operated, guardrail-checked, customer-approved social content generation (text/image/video/voiceover) and posting, via Blotato. Unchanged from earlier discussion.
- **Video Design & Graphic Creator** — flyers, ad creative, and standalone promotional/marketing videos, delivered as finished files. A genuinely separate module from Social, with its own request type — this is not the same thing as Social's video generator, even though both may use similar Blotato capabilities underneath.

**Future modules (architected for via the registry, not built now):** Written Content (blog + email), Reddit/Community, Backlinks/Directory Listings, Web+SEO.

**Engineering principle for Claude Code:** each module has its own generation logic and data tables, registered with the Hub through a shared, simple interface (a `modules` registry). Adding a new module later means writing new module code and registering it — **not modifying the Hub or any existing module's code.**

- Data model needs a `modules` table and a `customer_modules` table (§13).
- Admin panel gets a visual **Module Map**: Hub at center, each module as a block — Social and Video Design & Graphic Creator active/highlighted, everything else (Written Content, Reddit/Community, Backlinks, Web+SEO) shown as grayed-out "coming soon" blocks (§12, §18).

---

## 4b. Niche Playbook System

To actually "master the social side" for each industry, the product maintains a **playbook per niche**: content pillars, best-practice posting cadence/format guidance, and example content angles, feeding into what the Social module generates — on top of the customer's individual brand profile.

- **Where it comes from initially:** admin-curated research into each target vertical.
- **Compounding loop:** playbook shapes generation → tracker/optimizer measure real performance → admin refines the playbook from results → **every future customer in that niche benefits from what was learned on earlier ones.** Treat this as real IP, not a template.
- **Admin maintenance:** a Playbook Library screen (view/edit per niche, add new niches, flag whether a playbook is still on initial research vs. refined from real data).
- **MVP scope:** start with playbooks for a handful of niches matching your initial go-to-market verticals.

---

## 5. Blotato Account Strategy & Scaling

Blotato does not offer whitelabeling — customers never log into Blotato directly. **We connect and manage every customer's social accounts under our own Blotato account(s).**

**How account connection actually works:** no API-only way to connect a new account — only through Blotato's Settings ("Login with [Platform]"). Practically: **admin personally connects each account**, using the customer's platform login (obtained securely and temporarily during onboarding).

**Known constraints:**
- Connected accounts capped per plan: 20 (Starter), 40 (Creator), 100 (Agency). Facebook Pages/LinkedIn Company Pages don't count toward this.
- TikTok posting capped at 3 unique accounts/24hr **on Starter only** — doesn't apply on Creator/Agency. **Plan on Creator or Agency from the start.**
- Separate per-channel daily video cap (10/day Starter, 25/day Creator) — well above the default 3-posts/day limit.
- ~13 customers on Creator, ~33 on Agency, at 3 platforms each, before hitting the connection cap.

**Scaling strategy — account pooling:** run a pool of Blotato accounts (each Creator/Agency); route new customers to a fresh pool account as caps approach; track this cost deliberately (§10).

### 5a. Manual TikTok Metrics Entry
Simple admin form to periodically log TikTok metrics (views/likes/comments/shares) pulled manually from TikTok's own dashboard, feeding the same tracker/optimizer logic, clearly labeled as manual.

**Why this matters more than a minor API gap:** TikTok analytics sync via Blotato's API is unreliable, with sync rates varying meaningfully between accounts (38%-70% in our testing) even when both are confirmed Business accounts — root cause unconfirmed. Manual entry remains the dependable fallback regardless of account type or configuration. This was investigated directly: the obvious explanation (personal vs. Business account permission tier) was checked and ruled out — both test accounts are confirmed Business accounts in TikTok's own settings, yet sync rates still differ substantially with no identified pattern (not date/age, not content type). Treat manual entry as the primary path for TikTok, not a rare-case fallback.

---

## 6. Guardrails & Quality Control

Every generation (text, image, video — Social or Video Design & Graphic Creator) passes through a guardrail layer before the customer approval queue:

1. **Brand/tone consistency**
2. **Basic content safety** — no NSFW/offensive content
3. **Factual/claims accuracy** — especially health/finance/legal niches
4. **Competitor/legal-sensitive topic filtering**
5. **Voice selection (voiceover only)** — stock voices only, no cloning in MVP
6. **Quality bar** — premium, not generic AI slop; automated checks (1-5) are reliable, "does this look premium" isn't reliably automatable yet — **the mandatory customer approval step does most of the real work here.**

Configurable per customer/niche. The niche playbook (§4b) shapes *what* the Social module generates (strategy); guardrails check *whether it's safe/on-brand/quality* (compliance) once generated, across both modules — different jobs, working together.

**Every generation requires customer approval before it posts/is delivered.** Failures (guardrail or publish) auto-retry then escalate to admin rather than failing silently (§9).

---

## 7. Limits & Caps (configurable per customer — MVP defaults)

| Limit | Default | Notes |
|---|---|---|
| Social platforms per customer | 3 | TikTok, Instagram, X for MVP. More = upsell. |
| Social posts per day | 3 | Upsell for more. |
| Media uploads (images) | 20 | |
| Media uploads (videos) | 5 | |
| Design deliverables per week (flyers/ads) | 3 | Video Design & Graphic Creator module. |
| Standalone videos per week | 1 | Video Design & Graphic Creator module — separate cap since these are more resource-intensive than a flyer/ad. |
| Chat-edit regenerations per generation | 5 | Admin's internal budget control. |
| Approval required | Always | No exceptions in MVP. |

Caps live on the customer's profile, per-module — per-customer config, not hardcoded.

---

## 8. Calendar Tracker & Platform Optimizer

### 8.1 Calendar Tracker
Visual calendar (Admin + Customer) showing what was posted/delivered, when, on which module — Social posts and Video Design & Graphic Creator deliverables both appear, with configurable holiday/awareness-day callouts and content-idea suggestions tied to them.

### 8.2 Per-Platform Optimizer
Watches social platform performance, auto-suggests strategy changes when one underperforms, surfaced to admin — advisory only. Uses manually-entered data for TikTok (§5a). Doesn't apply to Video Design & Graphic Creator (no ongoing performance data for standalone deliverables).

---

## 9. Notifications & Failure Handling

**Triggers:** generation ready for admin review, generation running unusually long (§4, §16 step 50 — an intermediate "still processing" heads-up between normal timing and the failure timeout, not a failure itself), guardrail flag, content ready for customer approval, ticket response, publish success/failure, optimizer suggestion, warm-up complete, credit/cost threshold, Blotato pool cap approaching.

**Channels:** in-app notification center + email for time-sensitive items, stored in Supabase, markable read/unread.

**Failure/retry logic:** per §6 — both guardrail and publish failures route to a visible admin escalation queue.

---

## 10. Credit & Cost Tracking (Admin)

Per-customer credit/cost usage against a configurable budget (flag, don't hard-block). Per-pool-account spend view. Simple dashboard for MVP.

---

## 11. Storyboard — User Flows

### 11.1 Onboarding
1. Customer receives onboarding link → account created.
2. Onboarding form: business name, brand/logo, brand kit, niche (auto-applies a starting niche playbook, §4b), goals, tone/voice, posting frequency, guardrail sensitivity, holiday preferences, default voice preference.
3. **Selects active modules:** Social (with per-platform existing-vs-new-account branch and warm-up handling) and/or Video Design & Graphic Creator. Future modules (Written Content, Reddit/Community, Backlinks, Web+SEO) shown as "coming soon" in the same screen.
4. System provisions Hub dashboard + Blotato sub-profile (within assigned pool) scoped to selected modules.
5. First-time tutorial: requests, uploads, approvals, calendar.

### 11.2 Ongoing Service Flow
1. Customer submits requests/media/questions via the Hub — or admin proactively generates based on onboarding profile, niche playbook, calendar-suggested ideas, or optimizer suggestions.
2. Admin operates the relevant module: Social (post generation, informed by brand + niche playbook, exactly as previously discussed) or Video Design & Graphic Creator (flyer, ad, or standalone video from a customer request or occasion).
3. Guardrail layer checks the draft — customer approval queue, or flagged for regeneration.
4. Admin can chat-edit before it reaches the customer, up to the per-generation cap.
5. Customer reviews and approves (or requests a change).
6. Approved: social content publishes via Blotato; Video Design & Graphic Creator output is delivered to the customer as a finished file. Calendar updates for both.
7. For Social: analytics populate (with lag); tracker logs performance; optimizer surfaces suggestions; niche playbook refines over time from real results across all customers in that niche.

### 11.3 Admin/Owner Flow
Customer list + profiles + active modules, full generator access across every module, ticket inbox, guardrail/failure escalation queue, cross-customer analytics/calendar, optimizer suggestion queue, Blotato pool status, credit/cost tracker, manual TikTok metrics entry, niche playbook library (§4b), and the Module Map (§4a).

---

## 12. Wireframes (described)

**Screen: Onboarding Form** — Business Info → Brand Assets → Goals & Niche (auto-suggests playbook) → Social Platforms (existing/new branch) → Module selection (Social / Video Design & Graphic Creator active; others shown as upcoming) → Guardrail preview → Holiday preferences → Voice preference.

**Screen: Customer Hub Dashboard** — Notification bell; nav scoped to active modules (Requests | Calendar | Media Library | Approval Queue | Tickets | Analytics — Analytics only meaningful for Social); no generator.

**Screen: Admin Panel** — Customer list (active modules shown); per-customer profile + full generator access; ticket inbox; guardrail/failure escalation queue; cross-customer calendar/analytics; optimizer suggestion queue; Blotato pool status; credit/cost tracker; manual TikTok metrics entry.

**Screen: Module Map (admin-facing)** — Visual echo of the whiteboard sketch: Hub centrally, each module as a block. Social and Video Design & Graphic Creator highlighted/active; Written Content, Reddit/Community, Backlinks, Web+SEO shown grayed-out as "coming soon" — a literal, at-a-glance picture of the product's growth path.

**Screen: Niche Playbook Library (admin-facing)** — List of niches with playbooks; content pillars, best-practice guidance, example angles, and a flag for research-only vs. refined-from-data; simple add/edit interface.

---

## 13. Data Model (high level)

- **Customers** (id, name, brand profile, niche, guardrail config, plan caps, holiday preferences, credit budget, approval preference, default voice preference)
- **Modules** (id, name [social/video_design_graphic_creator/written_content/reddit_community/backlinks/web_seo], status [active/planned], description)
- **Customer modules** (id, customer_id, module_id, enabled, module-specific caps)
- **Niche playbooks** (id, niche, content_pillars, best_practices, posting_cadence_guidance, example_angles, refined_from_data [bool], last_updated)
- **Projects/Folders** (per customer, auto-organized, across modules)
- **Generations** (id, customer_id, module_id, channel, type, status, guardrail results, retry_count, edit_count, style/template tags, estimated_credit_cost, selected_voice, niche_playbook_version_used)
- **Media uploads** (id, customer_id, type, url, cap tracking)
- **Tickets/Requests** (id, customer_id, message thread, status)
- **Posts** (id, generation_id, platform, scheduled/published time, status, failure_reason, analytics snapshot) — Social module
- **Design deliverables** (id, generation_id, type [flyer/ad/video], status [draft/approved/delivered], delivered_at, file_url) — Video Design & Graphic Creator module
- **Analytics snapshots** (post_id, views, likes, comments, shares, reach, watch_time, collected_at)
- **Calendar events** (id, customer_id, post_id/design_deliverable_id/holiday_id, date, type, suggested_content_idea)
- **Holiday/awareness-day reference table** (id, name, date/recurrence, niche_tags, is_general)
- **Optimizer suggestions** (id, customer_id, platform, trigger_metric, proposed_change, status)
- **Social accounts** (id, customer_id, platform, blotato_account_id, blotato_pool_id, source, warm_up_status, warm_up_start_date, connected_by_admin_at)
- **Manual metrics log** (id, customer_id, post_id, platform, metrics, entered_by, entered_at)
- **Blotato account pools** (id, plan_tier, connected_account_count, cap, tiktok_posts_used_today, tiktok_daily_cap, monthly_cost)
- **Notifications** (id, customer_id/admin flag, type, message, read_status, created_at)
- **Credit usage log** (id, customer_id, generation_id, credit_cost, billing_period)

---

## 14. MVP Scope vs. Later Phases

**In MVP:**
- Hub architecture (§4a) with a proper module registry, even though only 2 modules are built now
- **Social module:** onboarding, account connection/warm-up, generation (text/image/video/voiceover), guardrails, approval, posting, analytics (with TikTok manual-entry workaround), optimizer — the full pipeline as discussed throughout, unchanged
- **Video Design & Graphic Creator module:** flyer + ad creation and standalone promotional video, delivered as finished files, same guardrail/approval pipeline, functionally separate from Social's video generator
- **Niche playbook system (§4b):** starting niches, admin-maintained, feeding Social generation, with the refinement loop wired to the tracker/optimizer
- Chat-based editing (admin-facing), capped per generation
- Media library with caps
- Full guardrail pipeline, with retry + escalation
- Mandatory customer approval
- Notification system, credit/cost tracker, Blotato pool structure
- Data isolation, per-customer caps
- Testing + validation phases (§17) before onboarding a real paying customer

**Deferred to later phases (architected for via the module registry, not built now):**
- **Written Content module** (blog + email)
- **Reddit/Community module**
- **Backlinks/Directory Listings module**
- **Web+SEO module**
- Payment/billing (Stripe)
- Full multi-tenant scaling beyond the first Blotato pool account
- Additional social platforms beyond the initial 3
- Analytics/optimizer coverage for non-social modules
- Fully custom video editor (only if needed)
- Advanced ML-driven self-learning/optimizer
- Real-time credit billing sync
- Automated "quality bar" detection beyond customer approval
- A self-serve tier
- A dedicated solution for the future "too many customers" scaling bottleneck (§15)

---

## 15. Open Questions

- Final product name/branding
- Pricing for the full-service tier, and for module/platform upsells
- Exact guardrail thresholds per niche
- Whether customers can opt to let admin auto-approve on their behalf
- Source for holiday/awareness-day reference data
- Exact credit-cost figures per generation type
- At what customer count a second Blotato pool account makes sense
- Order of future modules after MVP — Written Content, Reddit/Community, Backlinks/Directories, Web+SEO are all on the roadmap; which comes first once the Social + Video Design & Graphic Creator MVP is proven

**Future consideration (flagged, not designed now):** once the Hub + modules are running well, admin will personally be operating the generator for every customer across every module — at some point, **"too many customers" becomes the actual bottleneck**, since this is fully-managed with no self-serve option. Nothing to build for this now — it needs its own dedicated design pass once it's a real, current problem.

---

## 16. Build Plan for Claude Code (Antigravity)

**Phase 1 — Hub Foundation**
1. Scaffold Streamlit app with Supabase auth (customer + admin roles)
2. Data model / Supabase schema for the Hub (customers, projects, tickets, calendar, notifications, credit usage log) and the **module registry** (modules, customer_modules) as first-class citizens from day one
3. Basic routing for 2 views: Customer Hub, Admin

**Phase 2 — Onboarding & Niche Playbooks**
4. Build onboarding form (brand assets, niche → auto-applies starting playbook, module selection, per-platform account branch, guardrail defaults, holiday preferences, voice preference)
5. Build the niche playbook data structure and seed a handful of starting niches (§4b)
6. Auto-provision customer folder/project structure + Blotato sub-profile within assigned pool on submit
7. Build warm-up tracking for new social accounts
8. Build admin-facing account-connection workflow (manual, via Blotato Settings)

**Phase 3 — Social Module**
9. Integrate Blotato API/MCP for text/image/video/voiceover generation, informed by both brand profile and niche playbook — full pipeline as previously discussed
10. Build voice-selection UI
11. Build async video job handling (background status, notification, pre-scheduled kickoff)
12. Build chat-based edit layer (admin-facing), enforcing the per-generation edit cap
13. Build media library with upload caps

**Phase 4 — Video Design & Graphic Creator Module**
14. Build flyer/ad creation flow: request intake (occasion/purpose, format), generation via Blotato image gen, guardrail pass, delivery as a finished file
15. Build standalone video design flow: request intake, generation via Blotato video gen (separate request path from Social's video generator, even if using similar underlying capability), guardrail pass, delivery as a finished file
16. Register both as one module with two deliverable types (flyer/ad, video), its own caps (§7)

**Phase 5 — Guardrails, QC & Failure Handling**
17. Build guardrail pipeline (all 6 categories from §6), configurable per customer, applied uniformly across both modules
18. Build retry logic and escalation queue for guardrail and publish failures

**Phase 6 — Approval & Posting**
19. Build customer approval/preview queue, covering both modules
20. Wire approved social content to Blotato's publish endpoint with caps enforced and failure handling

**Phase 7 — Analytics, Tracker, Optimizer & Playbook Refinement**
21. Pull Blotato analytics API (Instagram, X), store snapshots
22. Build manual TikTok metrics entry
23. Build self-learning logic: tag by style/template/niche, surface best performers
24. Build per-platform optimizer: suggestion generation, approve/dismiss queue
25. Build the niche playbook refinement workflow: surface performance data back to admin per niche (§4b)

**Phase 8 — Calendar**
26. Build calendar view (customer read-only + admin cross-customer), covering both modules
27. Build/seed holiday + niche awareness-day reference table, wire into calendar with content-idea shortcuts

**Phase 9 — Notifications & Cost Tracking**
28. Build in-app + email notification system for all triggers (§9)
29. Build admin credit/cost tracker and Blotato pool status panel

**Phase 10 — Admin Tools**
30. Build admin panel: customer list with active modules, per-customer config, ticket inbox, escalation queues, cross-customer views
31. Build the **Module Map** screen (§4a, §12) — visual Hub + blocks, active vs. future modules
32. Build the **Niche Playbook Library** screen (§4b, §12)

**Phase 11 — Polish**
33. Implement the design system (§18): theme override, tokens, spacing, approval-stamp element, custom-styled data views
34. Apply design system consistently across both views
35. Onboarding tutorial

**Phase 12 — Testing**
36. Integration tests for every third-party call
37. Guardrail test suite (known-bad examples per niche, confirm correct flagging without over-flagging)
38. Failure-path tests (guardrail retry/escalation, publish retry/failure, video timeout)
39. Cap/limit tests across both modules
40. Warm-up period test
41. Cross-module test: generate content across Social + Video Design & Graphic Creator in one pass, confirm the Hub (calendar, approval queue) reflects both correctly
42. Notification test
43. Data isolation test
44. Blotato pool test
45. Module registry test: confirm a new module can be added (even a dummy/test module) without modifying existing module code — the actual test of the architecture's core promise

**Phase 13 — Validation**
46. Run the full pipeline with one real/test customer over a sustained period, across both MVP modules
47. Manual quality review against the "premium, not AI slop" bar
48. Guardrail accuracy review (false positives/negatives)
49. Cost validation against the credit tracker
50. Timing validation
51. Niche playbook validation: does the generated content actually feel strategically informed for that industry?
52. Business model validation: does the full-service price point feel justified?
53. Go/no-go checklist before onboarding a real paying customer

**Deferred (Phase 14+, not in this build):** Written Content module (blog + email), Reddit/Community module, Backlinks/Directory Listings module, Web+SEO module, Stripe billing, additional social platforms, second Blotato pool account, multi-tenant scale testing, ML-driven optimizer, live credit billing sync, automated quality-bar detection, native TikTok API analytics (if Blotato adds it), custom voice cloning via API (if Blotato adds it), a future self-serve tier, and a dedicated solution for the "too many customers" scaling bottleneck (§15).

---

## 17. Testing & Validation Strategy

Two separate phases (12 and 13 in §16), answering different questions: **Testing** asks whether the system works correctly (mechanical, checkable without human judgment) — including whether the module registry actually delivers on its core promise of addability without rework. **Validation** asks whether it produces outcomes worth paying for — including whether the niche playbooks make content feel genuinely strategic. Phase 13's go/no-go checklist exists so launch is a deliberate decision, not just "the tests are green."

---

## 18. Design & Brand Standards (v2)

The product needs to look and feel like a premium, established company — not a default Streamlit app, and not generic AI-tool boilerplate. **v2 supersedes the original warm/editorial direction below with a modern/technical one** — dark-mode-first, graphite base, one accent color reserved strictly for active states.

### 18.1 Design direction (v2 — supersedes 18.1 below)

**Color:** `bg` `#0E1013` (near-black graphite base), `surface` `#15181C` (card/panel fill), `line` `#262A30` (hairline borders/dividers — thin, not thick card outlines), `ink` `#E6E8EB` (primary text), `ink-muted` `#8A9099` (secondary text), `accent` `#3E8EFF` (electric blue — **reserved for active/in-progress states only, never resting states**), `pass` `#3FB97A` (flat, resting — guardrail-passed/approved), `fail` `#E5484D` (flat, resting — flagged/failed).

**Type:** Display — Space Grotesk. Body — Inter. Data/utility — **JetBrains Mono** (replaces IBM Plex Mono).

**Layout:** Flat and precise over decorative. Thin hairline borders instead of thick card outlines. Generous whitespace retained from v1. Single consistent icon set.

**The most important constraint:** glow and the accent color mark active/in-progress states only (a job actually running, a publish actually in flight) — never a resting state, however important that resting state is. A passed guardrail, a resolved ticket, a completed post are all resting states and get flat semantic color, not glow. When in doubt between "modern-professional" and "cringe," choose the flatter, less decorated option.

**Signature elements:**
- The **approval stamp** motif becomes a **status badge** — a sleek CI-pipeline-passing badge, not a wax seal. Flat, small, monospace-flavored, resting by default; only the badge for a genuinely in-progress state (processing, publishing) gets the accent glow.
- The **Module Map** (§4a, §12) becomes a **node/circuit-diagram visual** — the Hub-and-blocks structure reimagined as a hub node with trace lines fanning out to module nodes. This is the one screen where a technical flourish fits naturally; active modules' nodes and traces carry the accent, planned modules render as dim, dashed, unlit nodes.

### 18.1 (v1, superseded) Original warm/editorial direction

**Color:** `paper` `#F7F5F1` (warm background), `ink` `#14213D` (primary text/dark surfaces), `approved` `#2F6F4E` (guardrail-passed/approved content), `needs-review` `#B23A48` (calm flag color), `line` `#C9C2B4` (borders/dividers).

**Type:** Display — Space Grotesk. Body — Inter. Data/utility — IBM Plex Mono.

**Layout:** Generous whitespace, card-based modules, single consistent icon set.

**Signature elements:**
- The **approval stamp** motif for guardrail-passed content (§6).
- The **Module Map** (§4a, §12) as a recurring visual metaphor — the Hub-and-blocks structure from the original whiteboard sketch, reused as a design touchstone so the "building block, add anytime" philosophy is visible in the product itself.

### 18.2 Streamlit-specific implementation notes
Override Streamlit's default theme entirely; never leave raw `st.dataframe`/`st.table` defaults in customer-facing views; enforce one consistent spacing system (8px base unit); the async video wait deserves a considered loading state; empty states should read as an invitation to act.

### 18.3 Copy and interaction standards
Name things by what the customer controls, not internals ("Review needed," not "Guardrail flagged"). Active voice, consistent verbs across a flow. Plain, specific failure messages. Restrained, purposeful motion. Responsive down to mobile; visible keyboard focus states.
