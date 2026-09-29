# Blotato support thread addendum — per-template credit costs

Add to the existing support thread (the one with the voice-generation repro/creation IDs):

---

One more question while we have this thread open: is there a published (or that support can share) per-template credit-cost list for the `/v2/videos/templates` catalog?

We checked `https://help.blotato.com/api/llm` directly and it only documents `GET /credits` (balance + price-per-1000-credits), not a per-template cost breakdown. We measured cost ourselves by diffing our real credit balance immediately before and after a few generations, and found something unexpected: the "TV Wall Infographic" image template cost 50 credits, while the "AI Story Video with AI Voice" video template (voice omitted) cost only 35 credits — and a third template, "Single Centered Text Quote," cost 0 credits. So cost clearly isn't simply "images cost less than videos" — it looks like it varies per template, presumably based on how many generation sub-steps each template's pipeline actually runs.

If there's an official per-template cost table (even an approximate one), that would let us build accurate cost tracking for our customers instead of measuring every template by hand one at a time as we happen to use it. Thanks!

---

I don't have a tool that can post into your existing email/support thread directly (no email-sending capability in this environment — that's also why the app's own `email_client.py` is deliberately stubbed, per its docstring). This is drafted the same way the original voice-generation addendum was: you paste/send it yourself.

---

# Second addendum (2026-08-24) — the same bare-failure signature on a second, unrelated template

Add this one too, in the same thread:

---

We're now seeing the exact same failure signature as the voice-generation issue we reported earlier, but on a completely different template: **"Video of Images and Text with Minimal Style"** (`/base/v2/images-with-text/3ed4bb92-dbfe-45e6-9dc8-605b77f70506/v1`) fails every time we try it — `creation-from-template-failed`, with zero error detail in the creation object, on two independent real attempts. Creation IDs: `77d9450c-9791-4a64-9c4e-423ebba3ff0a` and `d13a5aa4-b8fe-45c6-963c-3f5339bba5b6`.

We're not asking you to debug this template specifically so much as flagging the pattern: this is the second unrelated template where a job fails with a completely bare status and nothing else — no message, no error code, nothing we can act on from our side. Is there a way to get more detail on a failed creation (even just from your own internal logs, given the creation ID), or is a bare failure like this expected to mean something specific we're not accounting for on our end?

---
