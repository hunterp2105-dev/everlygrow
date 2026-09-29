"""Thin wrapper over Blotato's REST API (https://backend.blotato.com/v2).

Generation is unified across content types: every template — image,
slideshow, or video-with-voiceover — goes through the same
POST /videos/from-templates -> GET /videos/creations/:id job shape
(queueing -> generating-script -> script-ready -> generating-media ->
media-ready -> exporting -> done). There is no per-content-type endpoint to
wrap, so there's deliberately no per-content-type function here either — see
app/lib/generation.py for the one generic poller this feeds.

Docs: https://help.blotato.com/api/llm (full spec), https://help.blotato.com/api/visuals
"""

import os

import requests

from app.lib import growth_rules

BASE_URL = "https://backend.blotato.com/v2"

# Name -> ElevenLabs voice id, from https://help.blotato.com/api/accounts/voice-ids
# "AI Video with AI Voice" wants the bare name via `voiceName`; other/older
# templates want the full id via `voiceId`. We pass both when a voice is
# selected so either field name works, and unused fields are harmless.
VOICES = {
    "Alice": "elevenlabs/eleven_multilingual_v2/Xb7hH8MSUJpSbSDYk0k2",
    "Aria": "elevenlabs/eleven_multilingual_v2/9BWtsMINqrJLrRacOk9x",
    "Bill": "elevenlabs/eleven_multilingual_v2/pqHfZKP75CvOlQylNhV4",
    "Brian": "elevenlabs/eleven_multilingual_v2/nPczCjzI2devNBz1zQrb",
    "Callum": "elevenlabs/eleven_multilingual_v2/N2lVS1w4EtoT3dr4eOWO",
    "Charlie": "elevenlabs/eleven_multilingual_v2/IKne3meq5aSn9XLyUdCD",
    "Charlotte": "elevenlabs/eleven_multilingual_v2/XB0fDUnXU5powFXDhCwa",
    "Chris": "elevenlabs/eleven_multilingual_v2/iP95p4xoKVk53GoZ742B",
    "Daniel": "elevenlabs/eleven_multilingual_v2/onwK4e9ZLuTAKqWW03F9",
    "Eric": "elevenlabs/eleven_multilingual_v2/cjVigY5qzO86Huf0OWal",
    "George": "elevenlabs/eleven_multilingual_v2/JBFqnCBsd6RMkjVDRZzb",
    "Jessica": "elevenlabs/eleven_multilingual_v2/cgSgspJ2msm6clMCkdW9",
    "Laura": "elevenlabs/eleven_multilingual_v2/FGY2WhTYpPnrIDTdsKH5",
    "Liam": "elevenlabs/eleven_multilingual_v2/TX3LPaxmHKxFdv7VOQHJ",
    "Lily": "elevenlabs/eleven_multilingual_v2/pFZP5JQG7iQjIQuC4Bku",
    "Matilda": "elevenlabs/eleven_multilingual_v2/XrExE9yKIg1WjnnlVkGX",
    "River": "elevenlabs/eleven_multilingual_v2/SAz9YHcvj6GT2YYXdXww",
    "Roger": "elevenlabs/eleven_multilingual_v2/CwhRBWXzGAHq8TQ4Fs17",
    "Sarah": "elevenlabs/eleven_multilingual_v2/EXAVITQu4vr4xnSDxMaL",
    "Will": "elevenlabs/eleven_multilingual_v2/bIHbv24MWmeRgasZH58o",
}


def _headers() -> dict:
    key = os.environ.get("BLOTATO_API_KEY")
    if not key:
        raise RuntimeError("BLOTATO_API_KEY must be set (see .env.example).")
    # The key may end in '=' base64 padding — must not be stripped.
    return {"blotato-api-key": key, "Content-Type": "application/json"}


def list_accounts() -> list[dict]:
    response = requests.get(f"{BASE_URL}/users/me/accounts", headers=_headers())
    response.raise_for_status()
    return response.json().get("items", [])


# §16 growth-rules Group E1 investigation (2026-09-11), blocked 2026-09-17:
# "Combine Clips and Apply Basic Edits" has a real `musicConfig.url`
# parameter — a raw music-file-URL passthrough. Confirmed via Blotato's
# own docs: Blotato does not host, vet, or license the track; the caller
# supplies the URL and is entirely responsible for its licensing. TikTok
# business accounts may only use Commercial-Music-Library-cleared or
# original audio — using unlicensed trending audio risks the customer's
# real connected account being muted or removed (see
# docs/social-growth-playbook.md Part 2.6, Part 6 Group E1). This is a
# real account-safety risk, not a preference, so it's blocked at the
# source (every screen that lists templates calls this one function) —
# NOT because it's ever actually been used, but because leaving a known,
# unvetted risk reachable "since nobody's hit it yet" is exactly how a
# real customer account gets muted. Do not remove this block without
# first building real licensed-audio handling for musicConfig (verifying
# the URL is Commercial-Music-Library-cleared or genuinely original audio
# before it's ever sent to Blotato) — see the "growth features still to
# build" list in docs/growth-rules-build-instructions.md.
BLOCKED_TEMPLATE_IDS = {
    "/base/v2/combine-clips/c306ae43-1dcc-4f45-ac2b-88e75430ffd8/v1",
}


def list_templates() -> list[dict]:
    response = requests.get(f"{BASE_URL}/videos/templates", headers=_headers())
    response.raise_for_status()
    items = response.json().get("items", [])
    return [t for t in items if t["id"] not in BLOCKED_TEMPLATE_IDS]


def create_from_template(template_id: str, prompt: str, inputs: dict | None = None, voice_name: str | None = None) -> dict:
    """Kicks off one async generation job. Returns {"id": ..., "status": ...}.

    KNOWN LIVE ISSUE, CAUSE STILL UNCERTAIN — voice selection on the
    "AI Video with AI Voice" template (/base/v2/ai-story-video/.../v1)
    failed every time we tried it (voiceName+voiceId together, voiceName
    alone), always within ~20-30s of "generating-script", with zero error
    detail (bare creation-from-template-failed). The identical request
    with no voice field succeeds reliably (~105s, real mediaUrl). BUT:
    testing voice on a second template (AI Selfie Talking Video) returned
    a clean `insufficient-credits` status WITH a real error message —
    meaning our test account ran out of Blotato credits partway through
    this investigation. We can't rule out that the earlier "no error
    detail" failures were ALSO credit exhaustion, just surfaced
    inconsistently (sometimes a clear insufficient-credits message,
    sometimes a bare unexplained failure) rather than a genuine
    voice-specific bug. Plan-tier gating IS ruled out (Blotato's pricing
    docs confirm voice is included on every plan). Support ticket filed
    with the full repro + specific creation IDs so Blotato can check their
    own logs. Until that's resolved, treat voice-enabled generation as
    unreliable regardless of cause; generation without a voice is solid.

    TEMPLATE-SPECIFIC INPUT BUILDING (2026-08-27): the Selfie/Consistent-
    Character template needs structured inputs (characterDescription +
    scenes), not the flat prompt most templates here accept — see
    build_selfie_character_inputs. Auto-built here (transparent to every
    caller, including generation.start_generation, which has no `inputs`
    param) only when the caller hasn't already supplied their own
    `inputs`, so an explicit caller-provided dict is never overridden."""
    if template_id in BLOCKED_TEMPLATE_IDS:
        raise ValueError(
            f"Template {template_id} is blocked (see BLOCKED_TEMPLATE_IDS) — a real account-safety "
            "risk, not just filtered from the picker. Don't call it directly either."
        )
    if template_id == SELFIE_CHARACTER_TEMPLATE_ID and not inputs:
        payload_inputs = build_selfie_character_inputs(prompt)
    else:
        payload_inputs = dict(inputs or {})
    if voice_name:
        payload_inputs["voiceName"] = voice_name

    # §16 growth-rules Group E2 investigation (2026-09-11): "Video of
    # Images and Text with Minimal Style" has a real, misspelled
    # `watemark` text-overlay parameter (confirmed via Blotato's own
    # docs) whose DEFAULT if never set is the literal placeholder text
    # "Watemark" rendered on screen — not a platform-imposed watermark,
    # but a real content-quality bug waiting to happen the moment this
    # template's separate known reliability issue (bare
    # creation-from-template-failed, see docs/phase13-validation-notes.md
    # Known Issue 1) is ever resolved on Blotato's side. Always default it
    # to blank unless the caller explicitly wants different on-screen text.
    if template_id == MINIMAL_STYLE_TEMPLATE_ID and "watemark" not in payload_inputs:
        payload_inputs["watemark"] = ""

    response = requests.post(
        f"{BASE_URL}/videos/from-templates",
        headers=_headers(),
        json={"templateId": template_id, "inputs": payload_inputs, "prompt": prompt, "render": True},
    )
    response.raise_for_status()
    return response.json()["item"]


def get_creation(creation_id: str) -> dict:
    """Poll a job's status. Returns the raw Blotato shape: status, mediaUrl,
    imageUrls, id, createdAt — the exact same shape for every content type."""
    response = requests.get(f"{BASE_URL}/videos/creations/{creation_id}", headers=_headers())
    response.raise_for_status()
    return response.json().get("item", response.json())


# ---------------------------------------------------------------------------
# PUBLISHING — real as of Phase 6.
#
# This posts to the customer's live connected account. It's only ever
# reachable in this codebase via app/lib/approval.py's approve_generation(),
# which only calls this once guardrails have passed (Phase 5) AND the
# customer has explicitly approved (Phase 6) — that's the real gate now,
# not a stub flag. There is no other call site.
# ---------------------------------------------------------------------------


def create_post(account_id: str, content: dict, target: dict) -> dict:
    """POST /v2/posts. Returns {"postSubmissionId": "..."}."""
    response = requests.post(
        f"{BASE_URL}/posts",
        headers=_headers(),
        json={"post": {"accountId": account_id, "content": content, "target": target}},
    )
    response.raise_for_status()
    return response.json()


def get_post(post_submission_id: str) -> dict:
    """Poll a publish job's status by postSubmissionId (the UUID POST
    /posts returns). Confirmed live: {"postSubmissionId", "status",
    "publicUrl"} — NOT the {state:{type,postUrl}} shape the list/analytics
    endpoints below use. Different endpoint, different id namespace,
    different response shape — don't conflate them."""
    response = requests.get(f"{BASE_URL}/posts/{post_submission_id}", headers=_headers())
    response.raise_for_status()
    return response.json()


def list_posts(limit: int = 50, cursor: str | None = None) -> dict:
    """GET /v2/posts. CONFIRMED LIVE: this is NOT a full history — it only
    ever returned a handful of items from the last ~hour, no matter the
    limit, with no cursor once that short window is exhausted. Fine for
    "what just happened" but useless for finding an older post. Kept for
    that narrow use; use search_published_posts() to find a specific past
    post (see app/lib/analytics.py's resolve_numeric_post_id)."""
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    response = requests.get(f"{BASE_URL}/posts", headers=_headers(), params=params)
    response.raise_for_status()
    return response.json()


def search_published_posts(limit: int = 100, offset: int = 0) -> dict:
    """GET /v2/published-posts — the real way to find a specific past post.
    Confirmed live: richer/flatter shape than list_posts (bare `postUrl`,
    not nested under `state`), and its `offset` pagination actually reaches
    back through real history (confirmed finding a 13-day-old post at
    offset=25 that wasn't in the more recent pages — the ordering isn't a
    simple monotonic date sort page-to-page, so don't assume you can binary
    search it; linear scan with a bounded page count is what's implemented
    in analytics.py). Response: {"items": [...], "count": <total>}."""
    response = requests.get(f"{BASE_URL}/published-posts", headers=_headers(), params={"limit": limit, "offset": offset})
    response.raise_for_status()
    return response.json()


def get_post_analytics(numeric_post_id: str) -> dict:
    """GET /v2/posts/:id/analytics — Blotato's OWN numeric id, not
    postSubmissionId. Analytics can take up to 24h to sync after publish
    (confirmed live: 404 with an explicit "not yet synced" message
    immediately after our first real post went out) — callers should
    treat a 404 here as "not ready yet", not a real error."""
    response = requests.get(f"{BASE_URL}/posts/{numeric_post_id}/analytics", headers=_headers())
    response.raise_for_status()
    return response.json()


VIDEO_TEMPLATE_KEYWORDS = ("video", "selfie", "avatar", "broll", "clips")
"""Blotato's /videos/templates response gives only {id, description} — no
structured output-type field — so templates are classified by keyword
matching on id/description. Heuristic, not authoritative; re-check against
the live template list if Blotato adds new naming conventions. Lives here
(not in app/lib/design.py, which only owns Video Design & Graphic Creator
concerns) so both that module's image/video caps AND the Social module's
video-prompt handling below classify templates identically — one place,
not two lists that can drift apart."""

_PREFERRED_VIDEO_TEMPLATE_KEYWORDS = ()
"""RETRACTED (2026-08-27) — was ("broll", "b-roll"), preferring "AI Avatar
with AI Generated B-roll" as the default video template. That template's
own Blotato docs (https://help.blotato.com/api/visuals/7c26a1cd-...) list
`avatarVideoUrl` — a real video of a person's face — as a REQUIRED input.
This app has no mechanism anywhere to supply one, and every call this
project has ever made to that template omitted it entirely. Blotato still
returned success every time, which means it was silently substituting some
fixed fallback/demo clip for the missing required avatar — confirmed by
direct user report: every generated video showed what looked like the same
person, regardless of prompt. The earlier "confirmed by comparison"
finding (docs/phase13-validation-notes.md, 2026-08-24) was built on
generations using this same broken fallback and is NOT reliable — see the
2026-08-27 retraction entry there. No template is preferred here until one
is properly tested with its actual required inputs — see
"AI Selfie Talking Video with Consistent Character"'s `characterDescription`
+ `scenes` fields, untested as of this retraction, as the likely next
candidate (it's the one template documented to synthesize a character from
a text description with no real footage required)."""

NATURAL_PACING_VIDEO_DIRECTION = (
    "Natural, candid pacing, like an unscripted documentary clip, not a polished "
    "advertisement. Vary shot lengths, some quick 1-2 second cuts mixed with some "
    "longer lingering shots. Handheld-feel framing with slightly imperfect, "
    "off-center composition, and real-world lighting. Avoid overly smooth "
    "stock-video motion, avoid a scripted presenter voice-over feel, avoid "
    "perfectly symmetric or polished framing."
)
"""Appended automatically to every video-template generation prompt (see
apply_natural_pacing_direction). Partially retracted alongside the template
preference above (2026-08-27): the specific "b-roll template + this
direction together" conclusion is unreliable (see that retraction), but the
narrower comparison this direction itself was based on — same template
("AI Video with AI Voice"), plain prompt vs. this exact direction — did NOT
involve avatarVideoUrl and isn't affected by that bug; it showed the
direction ALONE, on that template, was not sufficient to fix the original
"robotic" complaint. Left applied (harmless, plausibly still helpful) but
no longer claimed as a confirmed fix by itself — the real fix still depends
on which template ends up properly wired and re-tested."""


def is_video_template(template: dict) -> bool:
    haystack = f"{template['id']} {template['description']}".lower()
    return any(keyword in haystack for keyword in VIDEO_TEMPLATE_KEYWORDS)


def preferred_video_template(templates: list[dict]) -> dict | None:
    """No preference currently applied — see _PREFERRED_VIDEO_TEMPLATE_KEYWORDS'
    retraction note above. Returns the first video template found (natural
    list order), or None if there are no video templates at all. Kept as a
    named function (not inlined at call sites) so a real, correctly-tested
    preference can be reinstated in one place once one exists."""
    video_templates = [t for t in templates if is_video_template(t)]
    if not video_templates:
        return None
    for template in video_templates:
        haystack = f"{template['id']} {template['description']}".lower()
        if any(keyword in haystack for keyword in _PREFERRED_VIDEO_TEMPLATE_KEYWORDS):
            return template
    return video_templates[0]


def apply_natural_pacing_direction(prompt: str, template: dict) -> str:
    """Auto-appends NATURAL_PACING_VIDEO_DIRECTION to prompt if template is
    a video template and the direction isn't already present (e.g. an
    admin who typed their own similar wording) — never applied to image
    templates, where it has no meaning."""
    if not is_video_template(template):
        return prompt
    if NATURAL_PACING_VIDEO_DIRECTION in prompt:
        return prompt
    return f"{prompt.rstrip()} {NATURAL_PACING_VIDEO_DIRECTION}"


def apply_growth_direction(prompt: str, template: dict, target_seconds: int | None = None) -> str:
    """§16 growth-rules Group A1-A3: front-loads the hook/loop direction
    and a length target onto a video prompt, using the same is_video_template
    guard and idempotent "already present" check as
    apply_natural_pacing_direction. Kept as a separate function/constant
    (see growth_rules.HOOK_AND_LOOP_VIDEO_DIRECTION) rather than merged
    into that one — each was validated independently and either could
    need to change alone. Apply both when generating a video prompt."""
    if not is_video_template(template):
        return prompt
    target_seconds = target_seconds or growth_rules.DEFAULT_VIDEO_LENGTH_SECONDS
    prompt = prompt.rstrip()
    if growth_rules.HOOK_AND_LOOP_VIDEO_DIRECTION not in prompt:
        prompt = f"{prompt} {growth_rules.HOOK_AND_LOOP_VIDEO_DIRECTION}"
    length_direction = (
        f"Target roughly {target_seconds} seconds — only go longer if the content genuinely "
        "needs it to land the payoff; never pad with filler."
    )
    if length_direction not in prompt:
        prompt = f"{prompt} {length_direction}"
    return prompt


MINIMAL_STYLE_TEMPLATE_ID = "/base/v2/images-with-text/3ed4bb92-dbfe-45e6-9dc8-605b77f70506/v1"
"""§16 growth-rules Group E2 investigation (2026-09-11): "Video of Images
and Text with Minimal Style" — see create_from_template's `watemark`
default-blanking special case. Also the same template tracked as Known
Issue 1 (docs/phase13-validation-notes.md): fails reliably with a bare
creation-from-template-failed, unrelated to this watermark finding."""

SELFIE_CHARACTER_TEMPLATE_ID = "/base/v2/ai-selfie-video/57f5a565-fd17-458b-be43-4a2d8ccaca75/v1"
"""§16 video-naturalness follow-up (2026-08-27), the real next candidate
after the b-roll template retraction above: this is the one template
Blotato documents as synthesizing its presenter from a text description
(`characterDescription`) rather than requiring real footage — no
`avatarVideoUrl`-style trap. Untested against a real call as of this
constant's introduction; see build_selfie_character_inputs below for why
it needs special-casing at all."""

DEFAULT_SELFIE_CHARACTER_DESCRIPTION = (
    "A friendly, approachable small business owner or spokesperson, "
    "professional but warm, speaking directly to camera."
)


def build_selfie_character_inputs(prompt: str, character_description: str | None = None) -> dict:
    """This template's real schema (https://help.blotato.com/api/visuals/
    57f5a565-...) is {characterDescription: str, scenes: [{description,
    narration}], style, aspectRatio} — unlike most templates here, its
    docs give no prompt-only example, so (unconfirmed either way) it may
    not auto-fill from a bare `prompt` the way "AI Video with AI Voice"
    does. Rather than add new UI fields before this is even confirmed to
    work, derives a single-scene breakdown from the existing flat admin
    prompt: Blotato wants `description` (visual) and `narration` (spoken)
    as distinct fields, but this app only collects one prompt string, so
    both reuse it verbatim. `character_description` is optional so a
    caller can vary it per generation once that's worth surfacing in the
    UI — different text here is what should make different generations
    show a genuinely different synthesized person, unlike the retracted
    b-roll default's fixed fallback avatar."""
    return {
        "characterDescription": character_description or DEFAULT_SELFIE_CHARACTER_DESCRIPTION,
        "scenes": [{"description": prompt, "narration": prompt}],
        "style": "realistic",
    }


def get_credit_balance() -> int:
    """GET /v2/credits — real live credit balance. Used to LEARN each
    template's real cost by diffing this value immediately before a
    generation starts against immediately after it finishes (see
    generation.py's cost-learning mechanism, and
    docs/phase13-validation-notes.md for the manual measurements that
    seeded this approach)."""
    response = requests.get(f"{BASE_URL}/credits", headers=_headers())
    response.raise_for_status()
    return response.json()["creditsRemaining"]


def get_top_analytics(limit: int = 50) -> list[dict]:
    """GET /v2/analytics — top-performing posts across all connected
    accounts, each with `latestMetrics.metrics` (commentsCount, likesCount,
    sharesCount, viewsCount — confirmed live these come back as STRINGS,
    not numbers) and `metricsHistory`. Confirmed live this includes TikTok
    posts with real metrics, despite §4/§5a's "no TikTok analytics via
    API" — that premise may only hold for the per-post endpoint above, not
    this aggregate one; worth re-checking as more data comes in rather
    than assuming either endpoint's TikTok coverage is fixed."""
    response = requests.get(f"{BASE_URL}/analytics", headers=_headers(), params={"limit": limit})
    response.raise_for_status()
    return response.json().get("items", [])
