"""Stage 3: moving shots.

  motion.backend "kenburns": a local FFmpeg pan/zoom over the keyframe (free, instant, never distorts faces).
  motion.backend "wan":      Wan 2.2 TI2V-5B image-to-video on a Kaggle GPU. For every clip that is
      missing, this stage writes a job bundle (`make kaggle-push` uploads it). Clips that came back are
      imported from inbox/shots/<input-hash>.mp4. Until then a Ken Burns stand-in is rendered, so the
      film always assembles; `make check` lists stand-ins so none slip into the final cut.
In mock mode the same worker script runs locally without a GPU, so the round trip is tested too.
"""
from __future__ import annotations

import os
import shutil

from .common import (CONFIG, INBOX, MOCK, OUT, build, fail, ffmpeg, file_sha, forced, import_runs,
                     load_storyboard, read_meta, say, scaled, selected, sha, write_meta, x264_preset)
from .consent import require
from .kaggle_jobs import run_worker, write_bundle

STAGE_VERSION = 1
# zoompan expressions; P runs 0 -> 1 over the shot with ease-in-out
CAMERA = {
    "push_in":   ("1+0.12*P", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    "pull_out":  ("1.12-0.12*P", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
    "pan_left":  ("1.12", "(iw-iw/zoom)*(1-P)", "(ih-ih/zoom)/2"),
    "pan_right": ("1.12", "(iw-iw/zoom)*P", "(ih-ih/zoom)/2"),
    "tilt_up":   ("1.12", "(iw-iw/zoom)/2", "(ih-ih/zoom)*(1-P)"),
    "tilt_down": ("1.12", "(iw-iw/zoom)/2", "(ih-ih/zoom)*P"),
    "static":    ("1.04", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"),
}


def ken_burns(png, out, camera: str, seconds: float) -> None:
    fps = CONFIG["assembly"]["fps"]
    w, h = scaled(*CONFIG["assembly"]["master"])
    n = max(2, round(seconds * fps))
    p = f"(on/{n - 1})"
    ease = f"(3*pow({p},2)-2*pow({p},3))"
    z, x, y = (e.replace("P", ease) for e in CAMERA[camera])
    # upscale 2x first so zoompan's integer crop positions don't visibly jitter
    vf = (f"scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase:flags=lanczos,crop={2 * w}:{2 * h},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={w}x{h}:fps={fps},format=yuv420p")
    ffmpeg("-i", png, "-vf", vf, "-frames:v", n, "-c:v", "libx264", "-preset", x264_preset(), "-crf", "18", out)


def wan_params() -> dict:
    v = CONFIG["video"]
    return {k: v[k] for k in ("model", "width", "height", "num_frames", "fps", "steps", "guidance", "dtype")}


def wan_inputs(sb: dict, s: dict, kf) -> dict:
    prompt = f"{sb['style']['visual']}. {s['motion'].get('prompt', '')}".strip()
    return {"v": STAGE_VERSION, "backend": "wan", "keyframe": file_sha(kf), "prompt": prompt,
            "negative": sb["style"].get("motion_negative") or CONFIG["video"]["negative"], "seed": s["seed"],
            "params": wan_params()}


def kb_inputs(s: dict, kf) -> dict:
    return {"v": STAGE_VERSION, "backend": "kenburns", "keyframe": file_sha(kf),
            "camera": s["motion"].get("camera", "push_in"), "seconds": s["duration_s"],
            "size": list(scaled(*CONFIG["assembly"]["master"])), "fps": CONFIG["assembly"]["fps"]}


def process(sb: dict) -> list[dict]:
    """Bring every selected shot up to date; return the Wan jobs still missing."""
    jobs = []
    for s in selected(sb["shots"]):
        kf = OUT / "keyframes" / f"{s['id']}.png"
        if not kf.exists():
            fail(f"{s['id']}: no keyframe yet. Run `make keyframes` first.")
        out = OUT / "shots" / f"{s['id']}.mp4"
        kb = kb_inputs(s, kf)

        def render_kb(tmp, kb=kb, kf=kf):
            ken_burns(kf, tmp, kb["camera"], kb["seconds"])

        if s["motion"]["backend"] == "kenburns":
            build("shots", out, kb, render_kb)
            continue
        wan = wan_inputs(sb, s, kf)
        key, meta = sha(wan), read_meta(out) or {}
        if meta.get("input_hash") == key and not forced("shots"):
            say("shots", f"{s['id']}: cached Wan clip ({key})")
            continue
        back = INBOX / "shots" / f"{key}.mp4"
        if back.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(back, out)
            write_meta(out, wan, source="kaggle")
            say("shots", f"{s['id']}: imported Wan clip ({key})")
            continue
        jobs.append({"shot": s["id"], "key": key, "keyframe": f"{key}.png", "prompt": wan["prompt"],
                     "negative": wan["negative"], "seed": s["seed"], "src": str(kf)})
        if meta.get("fallback_for") == key and meta.get("input_hash") == sha(kb):
            say("shots", f"{s['id']}: Wan clip pending ({key}); keeping the Ken Burns stand-in")
            continue
        say("shots", f"{s['id']}: Wan clip pending ({key}); rendering a Ken Burns stand-in")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{s['id']}.tmp.mp4")
        render_kb(tmp)
        os.replace(tmp, out)
        write_meta(out, kb, fallback_for=key)
    return jobs


def main() -> None:
    sb = load_storyboard()
    require(sb, "shots")
    import_runs(INBOX / "shots" / "runs.jsonl")
    jobs = process(sb)
    bundle = write_bundle("shots", [dict(j) for j in jobs], wan_params())
    if jobs and MOCK:                       # simulate the Kaggle round trip locally (no GPU)
        run_worker("shots", bundle, mock=True)
        jobs = process(sb)
        write_bundle("shots", [dict(j) for j in jobs], wan_params())
    if jobs:
        say("shots", f"{len(jobs)} Wan job(s) pending: `make kaggle-push` (or upload {bundle}.zip by hand, "
                     "see kaggle/README.md)")


if __name__ == "__main__":
    main()
