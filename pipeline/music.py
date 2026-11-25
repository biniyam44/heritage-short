"""Stage 4: original score with ACE-Step 1.5 (instrumental, one track for the whole film).

  backend "acestep_api": a server you start yourself, e.g. on your Mac (see kaggle/acestep_music.py)
  backend "kaggle":      the same worker on a Kaggle GPU (`make kaggle-push KIND=music`)
Until the score exists a placeholder pad stands in, so the film still assembles; `make check` flags it.

Choosing a score by ear: music.alternatives lists other prompt/seed pairs. They are rendered in the same GPU
run and land in outputs/music/candidates/ (v1.m4a, v2.m4a, ... with index.md saying which is which). Copy the
prompt and seed you like into music.prompt / music.seed: that take is already in inbox/, so `make music` just
imports it as the score, with no new GPU run.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .common import (CONFIG, INBOX, MOCK, OUT, ffmpeg, forced, import_runs, load_storyboard, read_meta, say, sha,
                     write_meta)
from .kaggle_jobs import run_worker, write_bundle
from .providers import mock_music


def take_inputs(mc: dict, prompt: str, seed: int, lyrics: str) -> dict:
    """Everything that changes the audio: the cache key of one take."""
    return {"v": 1, "model": mc["model"], "prompt": prompt, "lyrics": lyrics, "seed": seed,
            "duration_s": mc["duration_s"], "steps": mc["steps"], "guidance": mc["guidance"]}


def main() -> None:
    # takes made on Kaggle come back with the worker's own log: copy its lines into runs.jsonl (once each, by
    # call_id), because inbox/ is git-ignored and those calls would otherwise never reach the repo
    import_runs(INBOX / "music" / "runs.jsonl")
    sb = load_storyboard()
    mc, m = CONFIG["music"], sb["music"]
    lyrics = m.get("lyrics", "[Instrumental]")
    out = OUT / "music" / "score.wav"
    inputs = take_inputs(mc, m["prompt"], m["seed"], lyrics)
    key, meta = sha(inputs), read_meta(out) or {}
    alts = [(f"v{i}", take_inputs(mc, a["prompt"], a["seed"], lyrics)) for i, a in enumerate(m.get("alternatives", []), 1)]
    score_done = meta.get("input_hash") == key and not forced("music")

    # A listening copy committed in outputs/ with its sidecar counts as made. A fresh clone has no inbox/, and
    # without this the stage deleted the six committed takes and asked for them again (clean-clone test, 2026-11-25).
    cand = OUT / "music" / "candidates"

    def kept(label: str, inp: dict) -> bool:
        return (read_meta(cand / f"{label}.m4a") or {}).get("input_hash") == sha(inp)

    # every take that is neither imported, nor waiting in inbox/, nor kept as a listening copy goes into one job bundle
    jobs = {}
    for item, inp in ([] if score_done else [("score", inputs)]) + alts:
        k = sha(inp)
        if not (INBOX / "music" / f"{k}.wav").exists() and not (item != "score" and kept(item, inp)) and k not in jobs:
            jobs[k] = {"key": k, "item": item, "prompt": inp["prompt"], "lyrics": lyrics, "seed": inp["seed"]}
    if jobs:
        bundle = write_bundle("music", list(jobs.values()), {k: mc[k] for k in ("model", "steps", "guidance", "duration_s")})
        try:
            if MOCK:
                run_worker("music", bundle, mock=True)
            elif mc["backend"] == "acestep_api":
                run_worker("music", bundle, api_url=os.environ.get("ACESTEP_API_URL") or mc["api_url"])
        except subprocess.CalledProcessError:
            say("music", "ACE-Step worker failed (is the server running? see kaggle/README.md)")

    if alts:                               # small AAC copies to listen to, and an index of what each one is
        cand.mkdir(parents=True, exist_ok=True)
        rows = ["| take | seed | status | prompt |", "|---|---|---|---|"]
        ready = 0
        for label, inp in alts:
            src, dst = INBOX / "music" / f"{sha(inp)}.wav", cand / f"{label}.m4a"
            if src.exists() and not kept(label, inp):
                ffmpeg("-i", src, "-c:a", "aac", "-b:a", "160k", dst)
                write_meta(dst, inp)
            elif not src.exists() and not kept(label, inp):   # a copy of an older take no longer matches its prompt
                dst.unlink(missing_ok=True)
                dst.with_suffix(".json").unlink(missing_ok=True)
            ok = kept(label, inp)
            ready += ok
            rows.append(f"| {label} | {inp['seed']} | {'ready' if ok else 'pending'} | {inp['prompt']} |")
        (cand / "index.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
        say("music", f"alternatives: {ready}/{len(alts)} ready in {cand} (index.md says which is which)")

    if score_done:
        say("music", f"score: cached ({key})")
        return
    back = INBOX / "music" / f"{key}.wav"
    if back.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(back, out)
        write_meta(out, inputs, source=mc["backend"] if not MOCK else "mock")
        say("music", f"score: ready ({key})")
        return
    if meta.get("fallback_for") == key:
        say("music", f"score pending ({key}); keeping the placeholder pad")
        return
    say("music", f"score pending ({key}); placeholder pad until it arrives "
                 "(start the ACE-Step server, or `make kaggle-push KIND=music`)")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name("score.tmp.wav")
    mock_music(mc["duration_s"], tmp)
    os.replace(tmp, out)
    write_meta(out, {"placeholder": True, "duration_s": mc["duration_s"]}, fallback_for=key)


if __name__ == "__main__":
    main()
