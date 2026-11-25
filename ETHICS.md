# Ethics: consent, privacy, licences, labelling

## Consent records

**Gate:** the pipeline refuses to generate an image, clip, voice or film of a character marked
`"real_person": true` until this table has a complete row for its `consent_id`. A real person shown or voiced
without a record here scores 0. Run `make consent` to check.

Columns are parsed by `pipeline/consent.py`: **ID** (C1, C2, ...) · **person** (role or first name) ·
**relationship** · **scope** (`likeness`, `voice`, `name`, `story`: list what they agreed to) · **how**
(e.g. "verbal, recorded phone call", "written WhatsApp message", "signed form") · **date** (YYYY-MM-DD) ·
**public** (`yes` = agreed to public posting on social media + a public GitHub repo) · **withdrawal** (how
they can withdraw, and what you will do).

| ID | Person | Relationship | Scope | How | Date | Public | Withdrawal |
|---|---|---|---|---|---|---|---|

<!-- Example row format (comments are ignored by the gate):
| C1 | Grandmother (first name only) | my grandmother | likeness, story | verbal, recorded call; she watched the radio cut | 2026-11-24 | yes | tell me any time; I take the film and repo down within 24 h |
-->

For someone who has died, record who gave consent on the family's behalf (role, relationship) in **how**.
If a shot uses a real photo (`"image"` or `"reference_photo"`), list the people in it as characters with
`real_person: true`.

## Privacy: what goes where

| Data | Sent to | Used for training? |
|---|---|---|
| `story/brief.md`, narration lines | Gemini API, free tier | Yes, it may be. Google's terms say free-tier content may improve its products and humans may review it; do not send sensitive personal data. Requests set `store: false` |
| Image prompts, reference images | Cloudflare Workers AI | Cloudflare states it does not train on Workers AI customer content |
| Keyframes, motion prompts | Kaggle (private dataset + private kernel) | runs open models on a VM; nothing sent to a model vendor |
| Final film, outputs/, runs.jsonl | public GitHub repo + social post | public |

What I kept out of prompts: _<fill in: e.g. full names, place names, dates of birth>_.
Mechanism: put such terms in `private_terms.txt` (git-ignored, one per line). The pipeline refuses to send
a prompt containing them unless I run with `ALLOW_PRIVATE=1` after deciding it is acceptable.

## Licences (checked 2026-11-24; verify before publishing)

| Component | Licence / terms | Note |
|---|---|---|
| Gemini 3.8 Flash (text), Gemini 3.8 Flash-Lite TTS (narration) | Gemini API Terms of Service | outputs usable; free-tier data terms above |
| FLUX.2 [klein] 4B via Cloudflare (keyframes) | Apache-2.0 (Hugging Face model card, checked 2026-11-25) + Cloudflare terms | |
| FLUX.2 [klein] 9B via Cloudflare (the two character portraits) | FLUX Non-Commercial License (Hugging Face model card, checked 2026-11-25) + Cloudflare terms | every keyframe with a person uses these portraits as references; check what the licence allows for outputs before any commercial use |
| Wan 2.2 TI2V-5B | Apache-2.0 (model card) | |
| ACE-Step 1.5 | MIT (code and weights, per repo + HF card) | card says generated music may be used commercially |
| FFmpeg (Homebrew build) | GPL (libx264) / LGPL | used locally as a tool |
| Fonts | system font (Arial Bold / Helvetica) drawn with Pillow into subtitles | set `font_file` in config.toml for non-Latin end-card text |
| Reference photos, `references/photos/` (7 from Wikimedia Commons) | CC BY-SA 2.0 / 4.0; author, licence and source of each in `references/photos/CREDITS.md` (checked 2026-11-25) | used only as image-model references, not shown in the film; none shows a face; one cropped (noted in CREDITS.md) |

## Labelling plan

1. Visible end card (2–4 s): "Made with AI", plus the models used (`end_card.lines` in storyboard.json).
2. MP4 metadata `comment=Made with AI ...` (set by the assembly stage).
3. Platform AI label switched on when posting (TikTok/Instagram/YouTube "AI-generated" toggle). _<record which platform and a screenshot link>_
4. The README's AI disclosure and this file in the public repo.

## Representation and sensitivity

_<Your notes: how you checked the visuals respect the person/culture (dress, places, rituals), what you
changed after feedback, and anything deliberately not shown.>_
