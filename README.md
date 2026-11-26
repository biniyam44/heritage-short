# The Heritage Short: an AI film pipeline

A 60–90 s short about a person, place or story that matters to my family. It is narrated in
Amharic with English subtitles, has an original score ducked under the voice and ends with an
AI-disclosure end card. It is exported as **vertical 9:16** (main) and horizontal 16:9.

`storyboard.json` is the contract between the stages. Every stage is one script in `pipeline/` that
reads it, writes `outputs/<stage>/` and skips any work whose inputs did not change.

**The film:** "ፀሐይ ሳትወጣ: Before the Sun Rises", 76 s, Amharic narration with English subtitles.
Watch it on the [Screening Room page](https://biniyam44.github.io/heritage-short/), or download the
[9:16](https://biniyam44.github.io/heritage-short/outputs/film/heritage_9x16.mp4) and
[16:9](https://biniyam44.github.io/heritage-short/outputs/film/heritage_16x9.mp4) files.

**The pipeline in one line:** `storyboard.json` → keyframes (FLUX.2 klein on Cloudflare) → shots (Wan 2.2
on a free Kaggle T4, or a Ken Burns zoom) → music (ACE-Step 1.5 on Kaggle) → narration (Gemini TTS) →
assembly (FFmpeg) → `make check`.

**What it cost:** $0 actually spent (free tiers only). Measured from `runs.jsonl`: 177 logged model calls
(39 failed and retried or reported), 487 GPU minutes on Kaggle, and a $3.06 list-price equivalent if
the same calls were paid. The table per stage and model is in [COSTS.md](COSTS.md).

## Quick start (clean clone)

```bash
brew install ffmpeg          # macOS; Linux: apt install ffmpeg (any build: text is drawn with Pillow)
make setup                   # .venv with Python 3.12 via uv; installs requests, jsonschema, pillow
make mock                    # the WHOLE pipeline offline, no keys -> build/mock/outputs/film/
make test                    # unit tests + "edit one line, only that shot regenerates"
```

For real runs:

```bash
cp .env.example .env         # then paste the API keys in (never commit .env)
make smoke                   # one tiny call per provider; latency goes to runs.jsonl
make film                    # all stages, cached; final files in outputs/film/
```

From a clean clone `make film` re-uses the committed `outputs/`. Every stage reports `cached` and no API
key is needed. `FORCE=all make film` regenerates everything (keys + Kaggle needed).

## Stages

| # | Stage | Script | Model (where) | Writes |
|---|---|---|---|---|
| 1 | Script / storyboard draft | `pipeline/draft.py` | Gemini 3.8 Flash (Gemini API) | `outputs/script/storyboard.draft.json` |
| 2 | Character portraits + keyframes | `pipeline/keyframes.py` | FLUX.2 klein 9B for portraits, 4B for keyframes (Cloudflare Workers AI), guided by real photos in `references/photos/` | `outputs/refsheet/`, `outputs/keyframes/` |
| 3 | Moving shots | `pipeline/shots.py` + `kaggle/wan22_i2v.py` | Wan 2.2 TI2V-5B (Kaggle T4) or Ken Burns (local) | `outputs/shots/` |
| 4 | Music | `pipeline/music.py` + `kaggle/acestep_music.py` | ACE-Step 1.5 (local server or Kaggle) | `outputs/music/score.wav` |
| 5 | Narration | `pipeline/narration.py` | Gemini 3.8 Flash TTS (Gemini API) | `outputs/narration/sXX.wav` |
| 6 | Assembly | `pipeline/assemble.py` | FFmpeg (local) | `outputs/film/heritage_9x16.mp4`, `heritage_16x9.mp4`, `subtitles_en.srt` |

Every output has a sidecar `.json` with its input hash, the exact inputs (prompt, seed, model) and the run
ID. Every model call adds one line to `runs.jsonl` (model, params, seed, latency, cost, status).

## Commands

| Command | What it does |
|---|---|
| `make film` | validate, then stages 1–6, then `check --soft` |
| `make mock` | the same, offline, into `build/mock/` |
| `make radio` | radio cut: narration + subtitles over placeholder music on black (user test 1) |
| `make smoke` | calls each provider once with harmless text, logs latency |
| `make check` | QA gate against the brief (length, sizes, codecs, loudness, subtitles, consent, stand-ins, secrets) |
| `make costs` | writes the measured table in `COSTS.md` from `runs.jsonl` |
| `make site` | writes `index.html`, a Screening Room page for the film built from the repo's own files: both cuts and the radio cut, every shot's lines, purpose and prompts, and the telemetry. Publish it with GitHub Pages (Settings → Pages → branch `main`, folder `/`) |
| `make consent` | shows the consent gate status |
| `make portraits N=3` | face candidates per character; put the chosen seed into `characters[].seed` |
| `make kaggle-push` / `kaggle-status` / `kaggle-pull` | GPU jobs on Kaggle (`KIND=shots` or `KIND=music`) |
| `make kaggle-import KIND=shots ZIP=...` | manual fallback: import a downloaded Kaggle output zip |
| `make <stage>` | run one stage: `draft keyframes shots music narration assemble` |

Useful variables: `ONLY=s03,s04` (limit to shots), `FORCE=keyframes` (ignore the cache for a stage),
`MOCK_FAIL_RATE=0.3` (mock mode: inject failures to watch the retries), `ALLOW_PRIVATE=1` (see ETHICS.md).

## Change one shot, regenerate only that shot

```bash
# edit shots[3].narration (or .keyframe_prompt) in storyboard.json, then:
make film
```

The log shows `cached` for every other item. It shows `s04: generating (changed: text)` for the edited one,
and assembly says which input changed. `runs.jsonl` gains exactly one new model call. `make test` checks
this automatically.

## GPU jobs (Wan 2.2, ACE-Step)

See [kaggle/README.md](kaggle/README.md). It covers the automatic `make kaggle-push`, the manual upload/download
fallback, Colab, and running ACE-Step locally on a Mac. A shot whose Wan clip has not come back yet gets a
Ken Burns stand-in, so the film always renders. `make check` fails while any stand-in is left. Set a
shot's `motion.backend` to `"kenburns"` to make that its final look.

## Docs

[ARCHITECTURE.md](ARCHITECTURE.md) (stages, contracts, caching, failures) ·
[DESIGN.md](DESIGN.md) (audience, user tests, why each shot) · [EXPERIMENTS.md](EXPERIMENTS.md) ·
[FAILURES.md](FAILURES.md) · [COSTS.md](COSTS.md) · [ETHICS.md](ETHICS.md) (consent, licences, labelling) ·
[PLAN.md](PLAN.md) (schedule and checklist)

## AI disclosure

The images, motion, music, narration voice and the first draft of the storyboard were generated with AI
models (listed above). The story, direction, edits and decisions are mine. The film carries a visible
"Made with AI" end card, MP4 metadata saying so, and the platform's AI label when posted.
