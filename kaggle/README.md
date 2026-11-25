# GPU jobs: Wan 2.2 (moving shots) and ACE-Step 1.5 (music)

`make shots` / `make music` write a **job bundle** for whatever is missing: `jobs.json`, the input keyframes,
and the worker script itself. It goes in `build/real/kaggle/<kind>/` and `build/real/kaggle/<kind>.zip`.
Results come back named `<input-hash>.mp4|wav` with a `runs.jsonl`. You put them in `inbox/<kind>/` and run
`make <kind>` again to import them.

Before the first real run, benchmark one shot: `ONLY=s01 make shots`, then push. The kernel log shows the
seconds per clip, so you can size the full batch.

## A. Automatic (kaggle CLI)

One-time setup (phone-verified Kaggle account):

```bash
uv tool install kaggle
kaggle auth login            # or put KAGGLE_API_TOKEN in .env; also set KAGGLE_USERNAME in .env
```

Then:

```bash
make shots                    # writes the bundle for pending Wan clips
make kaggle-push              # private dataset + GPU T4 x2 script kernel with internet
make kaggle-status            # until it says complete (first run downloads ~34 GB of weights: allow 10+ min)
make kaggle-pull              # kernel output -> inbox/shots/
make shots                    # imports the clips; then make film
```

Use `KIND=music` for ACE-Step on Kaggle (set `[music].backend = "kaggle"` in `config.toml` first).

## B. Manual fallback (browser only)

1. kaggle.com → Datasets → New dataset → upload `build/real/kaggle/shots.zip` (keep it private).
2. New notebook → Settings: **Accelerator GPU T4 x2**, **Internet on** → Add input → your dataset.
3. Run one cell: `!python /kaggle/input/*/wan22_i2v.py` (the script finds `jobs.json` itself; add `--limit 1` to benchmark).
4. Output tab → download everything (a zip) → `make kaggle-import KIND=shots ZIP=~/Downloads/<file>.zip` → `make shots`.

Colab: upload the zip, `!unzip shots.zip -d job && python job/wan22_i2v.py --jobs job/jobs.json --out out`, then zip `out/` and import it the same way.

## C. Music on your Mac (no Kaggle)

ACE-Step 1.5 supports Apple Silicon. In a separate terminal:

```bash
git clone https://github.com/ACE-Step/ACE-Step-1.5 ~/ACE-Step-1.5
cd ~/ACE-Step-1.5 && uv sync
ACESTEP_INIT_LLM=false uv run acestep-api     # serves http://127.0.0.1:8001; first start downloads ~10 GB
```

Then `make music` in this repo calls it. `[music].backend = "acestep_api"` is the default.

## If video fails

Set that shot's `"motion": {"backend": "kenburns", "camera": "push_in"}` in `storyboard.json`. That gives a
local pan or zoom over the keyframe, which is free and instant, and it is the brief's accepted fallback.
Faces are often better as Ken Burns anyway.

## Known risks (unverified on a T4 until you run it)

- RAM: the worker loads the 11 GB text encoder first, encodes all prompts, frees it, then loads the transformer.
- fp16: if clips come back black or NaN, the worker logs `blank or NaN frames`. Try `dtype = "bf16"` (slow on T4) or Ken Burns.
- Disk: about 34 GB of weights in the HF cache on the first run.
