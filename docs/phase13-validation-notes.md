# Phase 13 Validation Notes (running log)

Companion to `docs/guardrail-accuracy-notes.md` (guardrail-specific) — this
file tracks findings from §16 steps 46-53 more broadly: cost validation,
timing, sustained-run observations, and anything else Validation surfaces
that doesn't belong in the go/no-go checklist itself.

## `insufficient-credits` was never a recognized terminal status (2026-09-03)

Found live: two real generations (Home Services and Fitness niche-validation videos, using the newly-fixed character template) hit Blotato's real `"insufficient-credits"` status mid-run and then sat as `status: "processing"` in the DB indefinitely — `_BLOTATO_TO_INTERNAL` (`app/lib/generation.py`) had no entry for it, so `_normalize_status` fell through to its default of `"processing"`. Without this fix they would have eventually been marked failed anyway (by the 30-minute staleness timeout), but mislabeled as a generic stuck/orphaned job rather than the real, immediately-actionable reason (account ran out of credits).

**Fixed:** `"insufficient-credits"` added to `_BLOTATO_TO_INTERNAL` as a real terminal failure. `_notify_terminal`'s admin notification now surfaces the actual `blotato_status` reason (e.g. `"Generation failed (insufficient-credits): ..."`) instead of a bare `"Generation failed: ..."` — the reason is what tells admin whether to top up credits or investigate something else. Verified with a real test (`tests/test_generation_timeout.py`) and by re-polling the two real affected rows, which now correctly show `status: failed`, `blotato_status: insufficient-credits`.

## Cost validation (§16 step 49)

**Method:** Blotato's real `GET /v2/credits` endpoint returns a live
`creditsRemaining` balance. Measured real cost per generation by reading
the balance immediately before and after one real, complete generation job
(no publish involved), for three template/type combinations.

**Pricing (real, from `GET /v2/credits`):** $6.00 per 1,000 credits =
**$0.006 per credit.**

**Results (2026-08-12):**

| Template | Type (by our classification) | Real credit cost | Real $ cost |
|---|---|---|---|
| Single Centered Text Quote (`9f4e66cd-...`) | image | 0 | $0.00 |
| TV Wall Infographic (`013904bf-...`) | image | 50 | $0.30 |
| AI Story Video with AI Voice, voice omitted (`/base/v2/ai-story-video/...`) | video | 35 | $0.21 |

**Finding — the current cost model's *shape* is wrong, not just its numbers.**
`app/lib/credits.py`'s `ESTIMATED_COST_PER_TYPE = {"image": 1, "video": 5}`
assumes cost is a function of the binary image/video classification
(`generation_type()`: has a `media_url` → video, else image) with video
costing roughly 5x an image. Real data contradicts the direction of that
assumption on the very sample it was tested against: one image template
(TV Wall Infographic, 50 credits) cost **more** than the video template
tested (35 credits), and the other image template (Single Centered Text
Quote) cost **nothing at all**. Real cost appears to vary **by template**,
not by the image/video category — likely driven by each template's actual
Blotato-side pipeline complexity (e.g. how many AI sub-steps a given
template chains together), not by output media type.

**What this means concretely:** the credit tracker's whole purpose (per
§10) is to warn admin before a customer's real spend gets away from
budget. A binary image=1/video=5 model that's off by this much — in the
wrong direction, on real data — could tell admin a customer is nowhere
near budget while the customer is actually well over it (if they're using
expensive image templates), or the reverse. This is a real problem for
what the credit tracker is FOR, not just an inaccurate placeholder.

**Not fixed here.** Rebuilding `ESTIMATED_COST_PER_TYPE` into a proper
per-template cost table (fetched from Blotato once, cached, keyed by
template id rather than a hardcoded image/video guess) is a real,
scoped code change with product implications — it changes what an
existing customer's stored budget number actually means. That's a decision
for you, not something to silently rewrite while "validating." Options
once you've seen this:
1. Per-template cost table, refreshed periodically via balance-diffing (what this note did manually) or Blotato support confirming their real pricing model.
2. Keep the simple placeholder but recalibrate the ratio using a larger, template-representative sample (more than the 3 data points here).
3. Ask Blotato support directly whether there's a published per-template credit-cost list (their public API docs don't have one — checked directly).

**Real spend from this validation exercise:** 85 credits (~$0.51) — balance went 1002 → 917 across the three test generations above. Not production activity; logged here for transparency since it's real money, however small.

### Restructured (2026-08-18): per-template cost table, learned in production

Rebuilt `app/lib/credits.py` per option 1 above rather than deferring further. `ESTIMATED_COST_PER_TYPE` (the image/video binary guess) is gone. In its place:

- **`template_costs`** table (migration 0012), seeded with the three real measurements above.
- **Learned automatically**, not tested upfront across all 37 templates: `generation.start_generation` (and `guardrails._retry`, since a retry starts a genuinely new job) snapshots the real Blotato balance via `blotato_client.get_credit_balance()` immediately before a job starts, but only if that template has no row in `template_costs` yet. `generation._maybe_learn_template_cost` diffs that snapshot against the balance once the job reaches `ready`, and persists the result — so the second time any template is used, it reads a real number instead of guessing.
- **`FALLBACK_ESTIMATED_COST = 50`** — used only for a template with no measurement yet. Set to the highest of the three real data points (not an average), since underestimating is the actual product risk (a budget warning firing too late). Every use of the fallback is flagged per-row via `credit_usage_log.cost_is_measured = false`, so admin can distinguish a real number from a guess at a glance rather than needing to cross-reference `template_costs` by hand.
- Verified end-to-end with a real generation against a temporarily-unlearned template: balance snapshotted, job ran for real, cost diffed and persisted, and that same generation's own `credit_usage_log` entry used the freshly-learned number (not the fallback) — see `tests/test_template_costs.py`.

Also asked Blotato support directly (option 3) whether a published per-template cost list exists, via an addendum to the existing voice-generation ticket (`docs/blotato-support-addendum-template-costs.md` — drafted, not sent automatically; no email-sending tool available in this environment).

## Sustained-run compilation (§16 step 46)

The Dev Test customer's ~2+ weeks of history (2026-07-27 onward) is real
dev/testing activity across Phases 3-12, not a steady daily service
cadence — logged as supporting context, not a substitute for a real
forward-committed run. The actual sustained-period test is the forward
cadence below: at least one real Social + one real Design generation for
the Dev Test customer every 1-2 days, for 1-2 weeks (target through
roughly 2026-08-26), driven in-session (no autonomous scheduler — a cloud
routine would need a git repo + secret injection this project doesn't
have yet, and the user chose not to set that up for this).

### Cadence log

**2026-08-12 (day 1):**
- Social: generation `54bbe587-9495-49c5-9efb-bbd627cdae6d`, template "Single Centered Text Quote", prompt about staying consistent with small daily habits. Real Blotato job completed (`done`) → `status: ready`, guardrail `passed`. Left at pending customer approval — not published (standing rule).
- Design: generation `3ed3b9d9-8672-47db-8e10-7ec0529a4794`, template "TV Wall Infographic", prompt about 3 quick productivity tips. Real Blotato job completed (`done`) → `status: ready`, guardrail `passed`. Left pending — no publish step exists for Design anyway.
- Both ran through the same real guardrail pipeline (`app/lib/guardrails.py`) as any other generation, no shortcuts.

## Video naturalness finding (2026-08-24)

Admin feedback on real generated content: flyers/photos approved as good quality; videos read as robotic/AI-like, not natural. Ran a real, direct 4-way comparison rather than guessing at one fix — same topic (a small business owner opening their shop in the morning), varying template and prompt phrasing independently:

| # | Template | Prompt | Result |
|---|---|---|---|
| 1 | AI Video with AI Voice (pure talking avatar) | Plain, no direction | Baseline — robotic |
| 2 | AI Video with AI Voice (same template) | + explicit natural-pacing/candid-framing/varied-shot-length/anti-stock-feel direction | Prompt direction alone — **not enough** |
| 3 | AI Avatar with AI Generated B-roll | Same natural-pacing prompt as #2 | **Confirmed by direct comparison: meaningfully more natural** |
| 4 | Video of Images and Text with Minimal Style (the one true non-avatar/montage option available) | Same natural-pacing prompt | Failed to generate — see Known Issue 1 below |

**Finding, confirmed by admin's direct side-by-side judgment:** neither the b-roll template nor the natural-pacing prompt direction alone is sufficient — #2 (same avatar template, better prompt) still didn't read as natural. It's the **combination** — a b-roll-inclusive template *and* the natural-pacing direction together — that actually worked (#3).

**Fixed, applied automatically going forward (2026-08-25):**
- `app/lib/blotato_client.py` now owns `is_video_template()`, `preferred_video_template()` (prefers any b-roll-inclusive template by keyword match, not hardcoded to this one template id, so future b-roll templates qualify automatically), and `apply_natural_pacing_direction()`.
- Generate (Social) screen: the template selectbox now **defaults** to the preferred b-roll-inclusive template (admin can still pick anything else) — confirmed live via AppTest that "AI Avatar with AI Generated B-roll" is the pre-selected option.
- Whenever the selected template is any video template, the natural-pacing direction is **appended automatically** to the prompt before generation — not something admin has to remember to type.
- `app/lib/design.py`'s `categorize_templates` now reuses `blotato_client.is_video_template` instead of its own separate keyword list, so Design and Social can't drift apart on what counts as a video template.
- Verified with real unit tests (`tests/test_video_naturalness_defaults.py`, 7/7 passing) and a live AppTest drive of the real Generate (Social) screen.
- Baked into the **General default niche playbook** (§4b) too, not just code: `best_practices` (now version 2, live in Supabase) has this exact guidance appended, so it's part of the strategic reference admin sees for any niche defaulting to the General playbook — not something that only lives in code comments.

**Real cost of this comparison:** 344 → 104 credits across cases #1-3 (~$1.44); case #4's two attempts (see below) cost 0 additional credits since both failed before rendering started.

### RETRACTION (2026-08-27): the b-roll finding above was built on a broken generation, not a real comparison

Ran a fresh batch of real content for niche-playbook validation (3 niches × Social video + Design image, using the "confirmed" b-roll default from above). The admin reported directly: every generated video looked like the same video — same person, over and over, regardless of niche or prompt.

**Investigated and confirmed real:**
- Checked whether the video *files* were actually duplicates (a caching/reuse bug) — they were not: distinct file sizes, distinct ETags, distinct upload timestamps for every URL. The files are genuinely different.
- Checked Blotato's own template documentation for "AI Avatar with AI Generated B-roll" (`https://help.blotato.com/api/visuals/7c26a1cd-...`): it lists **`avatarVideoUrl` as a required input** — a real video of a person's face, meant to be customer-supplied footage.
- **This app has never supplied that field, on any call, ever** — `blotato_client.create_from_template` only ever sends `templateId` + a flat text `prompt`. There is no feature anywhere in this product for a customer to upload their own talking-head footage.
- Blotato returned `"done"` with a real, playable video every single time despite the missing required field — meaning it silently substitutes something (almost certainly a fixed internal demo/fallback clip) rather than erroring. That fallback clip is what showed up as "the same person" across every generation.

**What this invalidates:** the 2026-08-24 finding's conclusion that the b-roll template + natural-pacing direction "reads meaningfully more natural" is unreliable — the case that supposedly proved it (comparison #3) was this same broken fallback avatar, not a genuine AI-generated character reacting to the prompt. **What still holds:** the narrower result that the natural-pacing prompt direction ALONE, on "AI Video with AI Voice" (a template with no avatar-footage requirement — confirmed via its own docs, which describe it as narrated scene video with no presenter at all), was not sufficient to fix the original "robotic" complaint. That comparison (#1 vs #2) never touched `avatarVideoUrl` and isn't affected by this bug.

**Also newly learned, worth acting on next:** "AI Selfie Talking Video with Consistent Character" (`/base/v2/ai-selfie-video/57f5a565-...`) is the one template actually documented to synthesize a character from a text description (`characterDescription`, union type — text or image reference) with no real footage required, plus a structured `scenes` array (`description` + `narration` per scene) — genuinely different from the flat-prompt convention this app has used for every template so far. Untested. Likely the right next candidate, but needs `blotato_client.create_from_template` (or a template-specific variant) extended to actually send the structured inputs this template requires, not just a bare prompt string.

**Fixed immediately:**
- `blotato_client.preferred_video_template` no longer prefers any specific template — reverted to neutral (first video template in list order) until something is properly tested and confirmed.
- The live General niche playbook (now version 3) has the 2026-08-24 recommendation explicitly retracted, not just silently overwritten, so anyone reading its history understands what happened and why.
- The natural-pacing prompt direction is left in place (still applied automatically) since its own narrower evidence isn't affected by this bug, but the module docstrings no longer claim it's "confirmed" as part of a fix — only that it wasn't sufficient alone.

**Not yet done:** re-running a real comparison with a properly-wired template. That's real follow-up work (extending the calling convention for structured template inputs), not something to bolt on inside this retraction.

### Known Issue 1: a second template now shows the same bare `creation-from-template-failed` signature

"Video of Images and Text with Minimal Style" (`/base/v2/images-with-text/3ed4bb92-dbfe-45e6-9dc8-605b77f70506/v1`) failed **twice** (two independent attempts, both real) with `creation-from-template-failed` and zero error detail — checked the raw `GET /v2/creations/{id}` response directly both times, nothing beyond the bare status. This is the same unexplained bare-failure signature already on file for the voice-generation issue, now confirmed on a **second, unrelated template**. Worth adding to the existing Blotato support thread alongside the voice-generation report and the per-template-cost question — a pattern across multiple templates is a stronger signal than either instance alone. Not retried a third time (per explicit instruction — two real attempts is enough to call it a pattern, not spend more credits chasing a single template today).

## Timing validation (§16 step 50) — 2026-08-25

**Method:** pulled every real video generation logged across this build and looked for wall-clock duration. Found a real measurement problem along the way: the database's own `created_at` (set server-side by Postgres's `now()` default) and `updated_at` (set client-side by this app's Python code) disagreed badly enough on some rows that `updated_at` came out *before* `created_at` — logically impossible, and consistent with a clock-skew between this execution environment and Supabase's server (magnitude varied, roughly 20-100 seconds across the rows checked). **DB timestamp deltas are therefore not trustworthy for measuring real duration** and were not used for this finding.

What was used instead: elapsed time measured within a single Python process using `time.monotonic()` (immune to any client/server clock disagreement, since both the start and end reads come from the same clock). This is exactly what the video-naturalness comparison script (previous entry above) and one earlier real cost-measurement call already did, so their printed elapsed-time output is the real data source here.

**Real video generation timing observed (n=4, all from this build's own testing — not production volume):**

| Template | Real elapsed time |
|---|---|
| AI Story Video with AI Voice, voice omitted (cost-measurement run) | ~55-65s |
| AI Video with AI Voice, plain prompt (comparison #1) | ~150-165s (~2.5-2.75 min) |
| AI Video with AI Voice, natural-pacing prompt (comparison #2) | ~180-197s (~3.0-3.3 min) |
| AI Avatar with AI Generated B-roll, natural-pacing prompt (comparison #3) | ~351-367s (~5.85-6.1 min) |

**Range: under 1 minute to just over 6 minutes — roughly a 6x spread, and every single run finished well short of the packet's previously-stated fixed "~10 minutes."** Typical/median across these 4 sits around 3 minutes. Small sample, and all four runs were on this project's own test/dev Blotato account under whatever load conditions happened to exist at the time — a genuinely slower run under different conditions can't be ruled out from 4 data points, which is why the packet's wording (below) is phrased as an observed range, not a new guarantee.

**Fixed:**
- §4 and §9 of the packet updated to state the real observed range instead of a fixed number, with an explicit note that the sample is small and directional.
- New intermediate notification: `generation.GENERATION_SLOW_WARNING_MINUTES = 6` (migration 0013 adds `generations.slow_notification_sent_at` so it fires exactly once per generation, not on every poll while a job is legitimately still running). Distinct from the existing 30-minute `GENERATION_STALE_TIMEOUT_MINUTES` hard-failure — this one is a heads-up, not a failure, and doesn't touch `status`.
- Verified with real tests (`tests/test_generation_timeout.py`): fires once past the threshold, doesn't re-fire on a later poll of the same still-slow job, and doesn't fire at all below the threshold.

### Known Issue 2: true non-avatar montage/b-roll-only video generation is still untested

Every template in Blotato's catalog that's realistically generatable from a plain text prompt (no pre-supplied clips) has an avatar component **except** the one that failed (Known Issue 1) and "Combine Clips and Apply Basic Edits" (which requires existing video clip inputs, not pure text-to-video — not attempted, since it doesn't fit this product's generation model). So the "b-roll-inclusive" default currently in place (#3 above) still has a talking avatar in frame, just with b-roll cut in — it is not a pure non-avatar montage. Whether a fully avatar-free option would read even more natural is genuinely unknown. Revisit once Blotato responds on Known Issue 1, or if Blotato adds a new pure-montage template that's generatable from a text prompt alone.
