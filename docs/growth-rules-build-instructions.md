# Build Instructions: Growth Rules — Generator & Playbook System
**Source:** `social-growth-playbook.md` Part 6 | **For:** Claude Code (Antigravity)

This translates the social growth research into concrete rules to build into the content generator, niche playbook system (§4b), and optimizer (§8.2) of the AI content platform. Grouped by difficulty and by whether the rule is fully in our control or depends on Blotato.

**Important framing for Claude Code:** Some rules below depend on what Blotato's API actually supports (audio selection, watermark handling). For those, INVESTIGATE Blotato's real capabilities first and report what's actually possible before building — do not assume, and do not fake enforcement of something we can't truly control. Flag honestly where we can only "attempt" vs. "guarantee" a rule.

---

## GROUP A — Prompt/Generation Rules (fully in our control, build first)

These shape what the generator produces and can be built entirely on our side via prompt engineering and generation logic.

**A1. Front-load a hook on every video.**
Every video generation prompt must instruct the model to open with the payoff, claim, question, or surprising visual in the first 1-3 seconds — never a slow intro, greeting, logo, or setup. Add this to the standard video generation direction (alongside the existing natural-pacing direction already built). Hook formula to encode: trigger emotion/curiosity → state a specific payoff → imply a promise.

**A2. Default video length to short.**
Default TikTok/Reels video generation to ~10-20 seconds unless the content genuinely needs longer. Match length to payoff; never pad with filler. Make this a configurable default, not a hard cap.

**A3. Design for the loop where possible.**
Where the content allows, instruct the generator to end on a line/frame that ties back to the opening, to encourage replays.

**A4. Caption generation — SEO-weighted, natural language.**
Generate keyword-rich captions with the main search phrase front-loaded in the first line. Natural language people actually search for — NOT a hashtag list. Captions are a confirmed ranking factor on both TikTok and Instagram.

**A5. Hashtag limits per platform (hard rules):**
- TikTok / Instagram: 3-5 hyper-relevant niche hashtags maximum.
- X: 0-2 hashtags maximum — NEVER 3+ (triggers X's spam filter).
Enforce these limits in generation logic, not just prompt guidance.

**A6. X content is a completely different format.**
This is the biggest generation-logic change. When generating for X, the generator must NOT reuse the TikTok/Instagram approach. X rules:
- Text-first — lead with a conversation-starting take, question, data point, or non-inflammatory opinion.
- Video is optional, not mandatory (text reportedly outperforms video ~30% on X).
- Any link goes in a REPLY, never the main post (links in main post cut reach 30-90%).
- Shorter, punchier than a caption; built to earn replies, not passive likes.
Build X as its own generation path/branch, distinct from the shared TikTok/Instagram video path.

**A7. ~30% search-optimized content mix.**
In the content planning/suggestion logic, weight roughly 30% of suggested content toward answering specific search queries in the customer's niche (durable search traffic), with the rest weighted toward behind-the-scenes, UGC/testimonials, and educational content.

---

## GROUP B — Niche Playbook Enrichment (fully in our control)

Bake the research into the niche playbook system (§4b) so it informs every generation automatically.

**B1. Add growth-principle fields to the playbook structure**, applied to the General default playbook and every niche:
- Preferred content types for this niche (behind-the-scenes, testimonials, educational, etc.)
- Platform-specific format guidance (Reels for reach, carousels for saves, X text-first)
- The universal hook + retention + shares-over-likes principles as standing guidance
- Realistic growth-timeline expectation (3-6 months to traction) so content strategy is paced, not panic-driven

**B2. Encode format-by-goal logic (Instagram especially):**
- Reels → reaching non-followers / growth
- Carousels → saves / education / depth
- Stories → conversion / link clicks
- Single images → brand recall only, not growth
The generator/suggestion logic should pick format by the customer's stated goal, not default to one format for everything.

---

## GROUP C — Posting-Time Defaults (fully in our control)

**C1. Seed per-platform posting-time defaults** (starting points, per §8 calendar/scheduling):
- TikTok: Tue-Thu 2-6 PM local (test Saturday per account); schedule ~1-2 hrs before the account's real peak.
- Instagram: Tue-Thu 9 AM-12 PM local, Wednesday strong.
- X: Tue-Thu mornings, but prioritize the account's real active window (X's 30-60 min early-velocity dependence).
These are defaults the optimizer refines per account from real data — not fixed rules.

---

## GROUP D — Optimizer Success Metrics (fully in our control, important)

**D1. Change what the optimizer treats as "success."**
Per the research, retention/completion rate and shares/saves beat likes on every platform. Update the self-learning tracker + optimizer (§8.2) so its PRIMARY success metrics per post are, in priority order:
1. Completion rate / watch time (video)
2. Shares and saves
3. Comments
4. Likes (lowest weight — do not let a high-like/low-share post be judged "successful")
Winning patterns by this ranking feed back into the niche playbook — this is the compounding advantage the playbook system was designed for.

---

## GROUP E — Account-Safety Rules (HARD — investigate Blotato first)

These are the highest-stakes rules (they protect the customer's account from being muted/removed/shadowbanned), AND the ones most dependent on what Blotato actually supports. Investigate real Blotato capability before building.

**E1. TikTok audio must be license-safe — INVESTIGATE FIRST.**
The research is clear: TikTok business accounts can only use the Commercial Music Library (CML) / business-approved audio, or original audio — using unlicensed trending audio risks the customer's video being muted or removed. This is account-safety, not preference.
- **First, investigate:** Does Blotato's API let us control/select audio at all? Does it expose whether a sound is business/commercially licensed? Does Blotato already handle this (e.g. only using licensed audio) on business accounts?
- **If Blotato controls audio and only uses licensed/original audio** — document that we're safe by default, no build needed, just confirm.
- **If we can select audio via Blotato** — enforce CML/business-approved or original audio only in generation logic.
- **If Blotato gives us no control and might use unlicensed audio** — this is a real risk to flag prominently; the safest interim rule is to prefer original/generated audio or no music over trending sounds, and document the limitation honestly. Do NOT claim we're enforcing licensing if we can't actually verify it.

**E2. No watermarks on cross-posted content — INVESTIGATE FIRST.**
Instagram's 2026 Originality Score disqualifies watermarked reposts from recommendations; watermarked content is a hard eligibility failure on both TikTok and Instagram.
- **First, investigate:** Does Blotato's generated content carry any watermark? When the same content goes to multiple platforms, does Blotato re-export clean per platform, or reuse one file? Can we detect a watermark programmatically?
- **If Blotato generates clean, watermark-free content per platform** — document we're safe, confirm, done.
- **If content could carry a watermark** — build a check or a clean-export step per platform; if truly not detectable/controllable via Blotato, flag it honestly as a limitation and recommend a manual review step before cross-posting.
- **Never cross-post the identical file to multiple platforms without confirming it's watermark-free and, ideally, slightly varied** (Originality Score penalizes verbatim reposts).

---

## Build order recommendation

1. **Groups A, B, C, D first** — these are fully in our control, high-value, and unblocked. They make every generation meaningfully better immediately.
2. **Group E after investigation** — start by investigating Blotato's real audio/watermark handling, report findings, THEN decide what's buildable vs. what must be flagged as a limitation or handled with a manual review step.

## After building

- Run the full test suite.
- Generate fresh test content per platform (TikTok video, Instagram Reel, an X text post) for 2-3 niches, and confirm the platform-specific differences actually show up: X reads text-first, hashtag counts differ correctly, hooks are front-loaded, captions are search-weighted.
- Report honestly on Group E: what we can actually guarantee vs. only attempt, given Blotato's real capabilities.

---

## BUILD LOG — what actually happened (2026-09-10 through 2026-09-17)

### Done and live
- **A1/A2/A3** (hook front-load, ~15s length default, loop ending) — `blotato_client.apply_growth_direction()`, applied alongside the existing natural-pacing direction on every video prompt.
- **A5** (hashtag limits) — `growth_rules.enforce_hashtag_limit()`, real code-level trimming (not just prompt guidance) on the Generate (Social) caption field.
- **A6** (X text-first, video optional) — Generate (Social) has an explicit platform selector; picking X switches to a text-first flow with media optional. `generation.start_text_only_generation()` is the one path in the engine with no Blotato media job at all (real 0 credit cost, logged as measured). Also fixed a real bug found building this: guardrails' auto-retry unconditionally assumed every flagged generation came from a real Blotato job — a flagged text-only post hit a real 404 trying to "regenerate" a template id that was never real. Fixed in `guardrails._handle_non_pass` (escalates immediately instead for text-only generations).
- **B1/B2** (universal principles, platform format-by-goal) — kept in code (`app/lib/growth_rules.py`), not duplicated per niche-playbook row, since these facts don't vary by niche. Surfaced in the Playbooks screen and near the Generate (Social) caption field.
- **C1** (posting-time defaults) — advisory only. **Important finding:** this product has no scheduling feature at all — approval publishes immediately, there's no "post later." Surfaced as a reference block on the Calendar screen (guidance for when to approve, not an automatic scheduler). Real per-platform *scheduling* is tracked below, not done.
- **D1** (optimizer success metrics) — **important finding:** completion rate, watch time, and saves (the research's #1/#2 signals) are not available anywhere in this product — confirmed against Blotato's real API responses (`get_top_analytics`/`get_post_analytics` return only views/likes/comments/shares) and `analytics_snapshots.watch_time` has never been populated by any real source. `analytics.engagement_score()` reweighted to favor shares (×5) over comments (×2) over likes (×1) — the highest-priority signal we actually have data for. Does not claim to measure retention.
- **E1 investigated** — no Blotato API parameter exists anywhere to select a specific TikTok Commercial Music Library track; every template we actually use adds only voiceover/narration, never a music track, so the CML rule doesn't apply to anything we currently generate. One real risk found: "Combine Clips and Apply Basic Edits" has a `musicConfig.url` raw passthrough with zero licensing vetting from Blotato — **blocked entirely** (`blotato_client.BLOCKED_TEMPLATE_IDS`, enforced in both `list_templates()` and `create_from_template()`) until licensed-audio handling is deliberately built for it (see below).
- **E2 investigated** — Blotato doesn't force its own branding on exports by default. This product is structurally safe from Instagram's cross-platform-repost penalty already (every generation targets exactly one platform, never "post to all"). Found and fixed a real bug: "Video of Images and Text with Minimal Style" has a `watemark` (their typo) text-overlay parameter that defaults to literally displaying the word "Watemark" on screen if unset — now always blanked unless explicitly overridden (`blotato_client.MINIMAL_STYLE_TEMPLATE_ID`).

### Growth features still to build (real gaps, deliberately deferred — larger than this pass)

1. **A4 — real AI caption generation.** What exists today is guidance only (help text on the caption field telling admin/customer to front-load keywords). There is no actual caption-writing step anywhere in this codebase — captions are always hand-typed. Building real SEO-weighted caption generation means a genuinely new LLM content-generation call (likely Claude, similar in shape to the guardrails call but generative instead of evaluative), not a tweak to an existing one. Needs its own design pass: where it's triggered from, whether it's a suggestion the admin/customer can edit or fully automatic, how it interacts with the niche playbook's content pillars.

2. **C — real per-platform scheduling.** What exists today is advisory only (a "best times to post" reference block on Calendar). There is no scheduling feature anywhere in this product — approval publishes immediately via `approval.approve_generation()` → `_publish()`. Building real scheduling to the research-backed time windows (TikTok Tue-Thu 2-6PM, Instagram Tue-Thu 9AM-12PM, X Tue-Thu mornings) means: a new "scheduled_for" concept on `generations`, a background job/poller to actually fire the publish call at the right time (this app currently has no background scheduler at all — the only place a generation's state is ever re-checked is a manual "check status" button), and a UI for picking or auto-suggesting a time at approval. A real, separate feature, not a rule to bake into the existing generator.

3. **E1 follow-up — licensed-audio handling for `musicConfig`.** If "Combine Clips and Apply Basic Edits" (or any future template with a similar raw-audio-URL passthrough) is ever actually needed, building real safety here means verifying a supplied music URL is either genuinely original audio or confirmed Commercial-Music-Library-cleared before it's ever sent to Blotato — Blotato provides no such verification itself. Until that's built, the template stays blocked (`blotato_client.BLOCKED_TEMPLATE_IDS`) — do not remove the block without building this first.
