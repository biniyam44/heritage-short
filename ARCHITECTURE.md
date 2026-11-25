# Architecture

```
story/brief.md ──► [1 draft] ──► storyboard.json  ◄── you edit it; validated against schema/ every stage
                                     │
          ┌──────────────────────────┼───────────────────────────┬─────────────────────┐
          ▼                          ▼                           ▼                     ▼
 [2 keyframes]                [5 narration]                [4 music]            (config.toml:
  refsheet/<char>_*.png        narration/sXX.wav           music/score.wav       models, sizes,
  refsheet/style.png           Gemini TTS, 1 call/line     ACE-Step 1.5          prices, mix)
  keyframes/sXX.png            ──────────────┐             (local or Kaggle)
  FLUX.2 klein + ref images                  │                   │
          │                                  │                   │
          ▼                                  │                   │
 [3 shots] shots/sXX.mp4                     │                   │
  wan: job bundle ─► Kaggle T4 ─► inbox/<hash>.mp4 ─► import    │
  kenburns: FFmpeg zoompan (also the stand-in)                   │
          └──────────────────────────┬───────┴───────────────────┘
                                     ▼
                              [6 assemble] FFmpeg
         timeline from narration lengths · subtitle PNG overlays in the 9:16 safe area · end card
         sidechain duck · two-pass loudnorm · film/heritage_9x16.mp4 + heritage_16x9.mp4 + .srt
```

## Contracts

| Contract | Owner | Purpose |
|---|---|---|
| `storyboard.json` + `schema/storyboard.schema.json` | you (the draft stage writes it once) | **what** the film is: shots, prompts, narration, subtitles, seeds, characters, consent IDs |
| `config.toml` | you | **how**: model IDs, sizes, steps, mix settings, prices. No secrets |
| `outputs/<stage>/<item>.<ext>` + `<item>.json` sidecar | the stage | the artifact plus its provenance: input hash, exact inputs, run ID |
| `runs.jsonl` | `call_model()` and the GPU workers | one line per model call: model, params, seed, latency, cost, status, attempt |
| `build/<mode>/kaggle/<kind>/jobs.json` | stage 3 / 4 | the GPU job contract: params + one job per missing clip, keyed by input hash |
| `.env` (git-ignored) | you | API keys only |

Every stage validates the storyboard first: JSON Schema (draft 2020-12), then the cross-field checks a
schema can't express (unique shot IDs, referenced characters exist, image files exist). A bad edit fails
fast with the path to the bad field, before any paid call.

The draft stage never overwrites your storyboard. It writes `outputs/script/storyboard.draft.json`, and it
replaces `storyboard.json` only while that file is still the shipped example. Once `storyboard.json` is yours,
the stage makes no model call at all, so `make film` from a clean clone (no `.env`) runs on cached outputs;
`FORCE=draft` writes a fresh draft next to it for comparison.

## Caching by input hash

`build(stage, out, inputs, make)` in `pipeline/common.py` is the whole mechanism:

1. `key = sha256(json.dumps(inputs, sort_keys=True))[:16]`.
2. If `out` exists and its sidecar has the same key, it is a hit and is skipped.
3. Otherwise `make(tmp)` writes a temp file. It is renamed into place only after success, and the sidecar is
   written last. A crash or failed call can never leave a half-written file that looks cached.
4. On a miss the log says *why*, e.g. `generating (changed: prompt)` or `changed: narration.s04`.

What goes into each key (file inputs are represented by their content hash):

| Stage | Key inputs |
|---|---|
| refsheet | portrait model, prompt (character description), seed, size: the file name carries model and seed, so face candidates sit side by side |
| keyframes | model, full prompt (style + shot prompt + character descriptions), seed, size, **hashes of the reference images** |
| shots (wan) | keyframe hash, motion prompt, negative prompt, seed, Wan params (size, frames, fps, steps, guidance, dtype) |
| shots (kenburns) | keyframe hash, camera move, duration, size, fps |
| music | model, prompt, lyrics, seed, duration, steps, guidance (each of `music.alternatives` is a take with its own key) |
| narration | model, voice, style, text, language |
| assemble | hashes of every clip, narration file and the score, the timeline, subtitles, end card, mix config |

Because file inputs are hashed, changes cascade exactly as far as they should. Edit a character
description and only that character's sheet, the shots it appears in, and those shots' clips regenerate.
Edit one narration line and only that line is re-synthesised; assembly re-renders locally. Stage
version numbers (`STAGE_VERSION`) invalidate a stage on purpose when its code changes its output.
`FORCE=<stage>` bypasses the cache for that stage and `ONLY=s03` limits work to some shots.

Narration is one TTS call per shot line rather than one long take. That is what lets a one-line edit cost
one call. The trade-off is that voice consistency across calls must be checked by ear (an experiment
in EXPERIMENTS.md).

## Failure handling

| Failure | What happens |
|---|---|
| Network error, timeout, HTTP 408/429/5xx, malformed response | `TransientError` → retry with exponential backoff + jitter (2 s, 4 s, 8 s; honours `Retry-After`), up to 4 attempts. Every attempt is a `runs.jsonl` line with `status`, `error` and `will_retry` |
| HTTP 400/401/403/404, missing key | `FatalError` → stop immediately with the API's message (retrying a bad key wastes quota) |
| Daily quota used up (Cloudflare 3036, Gemini `quota_exceeded`) | `FatalError` with the reset time. Cloudflare resets 00:00 UTC = 03:00 EAT |
| LLM returns invalid JSON or a schema-invalid storyboard | the validation errors go back to the model, up to 3 tries |
| Real person without a consent record | consent gate exits with code 3 before any image, video, voice or film is made (mock mode warns) |
| Private term in a prompt (`private_terms.txt`) | refused before the request is sent, unless `ALLOW_PRIVATE=1` |
| Wan clip not back from Kaggle | Ken Burns stand-in rendered (sidecar records `fallback_for`), so the film still assembles; `make check` FAILs while stand-ins remain |
| A clip from an older storyboard version | impossible to import by mistake: clips come back named by input hash |
| Fresh clone: no `inbox/`, no keys | committed outputs with a matching sidecar count as made, so `make film` reports `cached` and calls no model; the music takes' listening copies (`outputs/music/candidates/`, with sidecars) are kept, not deleted and not requested again |
| Connection drops while downloading a kernel's output | `make kaggle-pull` retries up to 5 times without `-o`, so files that arrived are skipped and a broken one resumes where it stopped |
| Kaggle mounts an older version of the job dataset | `make kaggle-push` starts the kernel only once Kaggle serves the `jobs.json` just uploaded (same `run_id`), and the kernel's copy of the worker exits at once if its `jobs.json` has another `run_id` (2026-11-25: a stale mount re-rendered 7 old clips, 2 h 54 min of GPU) |
| One Wan job crashes (OOM, NaN/blank frames) | the worker logs it and moves to the next job; a rerun skips finished clips |
| ACE-Step server not running | stage prints how to start it and uses a placeholder pad (flagged by `make check`) |
| ffmpeg failure | error with the last stderr lines; the temp file is not promoted |
| FFmpeg build without libass/drawtext (Homebrew's 9.x) | not a failure: subtitles and end-card text are drawn with Pillow (shrunk to fit) and placed with `overlay=enable='between(t,a,b)'` |

`MOCK_FAIL_RATE=0.3 make mock` injects random transient failures so the retry path can be watched.

## Logging and measurement

`runs.jsonl` fields: `ts, run_id, mock, call_id, stage, item, provider, model, params, seed, attempt,
status, latency_s, cost{input_tokens, output_tokens, audio_tokens | neurons_est, usd_list}, error`. Kaggle
lines add `gpu, gpu_s, peak_vram_gb`, and the `_load` line counts model download and load time as GPU
time. Lines written on Kaggle come back in `inbox/<kind>/runs.jsonl` (git-ignored); `make shots` and
`make music` append them to `runs.jsonl` once each, by `call_id`. `make kaggle-pull` also copies each kernel's
log to `outputs/logs/` (named by a hash of its content), because `inbox/` is not committed and every pull
overwrites the last log. Since 2026-11-25 the music worker logs its set-up (clone, install, server start, model
load) as a `_load` line; for earlier runs that time is only in the kernel log (see COSTS.md).
`make costs` groups the lines by stage and model into `COSTS.md`. Costs are list-price equivalents
from `config.toml [prices]`; the actual spend on free tiers is $0.

## Mock mode

`MOCK=1` (`make mock`) swaps every provider for an offline FFmpeg generator: colour cards for images,
noise bursts sized to the word count for speech, and a sine chord for music. It runs the real Kaggle
worker scripts with `--mock`. Outputs go to `build/mock/` with their own `runs.jsonl`, at half resolution,
so real logs are never mixed with mock ones. Everything else is the real code path: schema validation,
hashing, the job bundle round trip, assembly, subtitles, ducking, loudnorm and the QA check.

## Security and reproducibility

- Keys are only in `.env` (git-ignored, with `.env.example` as the template). `make check` scans repo files for
  any `.env` value and for Google key patterns.
- Model IDs and request formats live in `config.toml`. They were checked against the official docs on 2026-11-24.
- Seeds: FLUX.2 and Wan take the shot seed. ACE-Step takes `music.seed`. Gemini TTS has no seed, so re-synthesising a
  line can sound slightly different. That is why takes are cached and committed.
- `outputs/` and `runs.jsonl` are committed, so a clean clone reproduces the film without calling a model.
