#!/usr/bin/env python3
"""Wan 2.2 TI2V-5B image-to-video worker for Kaggle (GPU T4 x2), Colab or any CUDA GPU. Standalone file.

Input : jobs.json + <key>.png keyframes, written by `make shots` (pipeline/shots.py).
Output: <out>/<key>.mp4 per job, and <out>/runs.jsonl (one line per model call; merged into the repo's log).
Run   : as a Kaggle script kernel (`make kaggle-push`), or in a notebook cell with the job dataset attached:
            !python /kaggle/input/<dataset>/wan22_i2v.py            (add --limit 1 to benchmark one shot first)
Test  : python kaggle/wan22_i2v.py --jobs <bundle>/jobs.json --out /tmp/x --mock     (no GPU, Ken Burns clips)

Memory plan for a 16 GB T4 with ~30 GB RAM: load the pipeline WITHOUT the 5B transformer, encode every
prompt with the 11 GB UMT5 text encoder, drop it, then load the transformer and use model CPU offload.
fp16 because the T4 has no fast bf16. WanImageToVideoPipeline handles TI2V-5B via expand_timesteps
(first-frame latent conditioning, no CLIP image encoder). A failing job is logged and skipped so one bad
shot can't waste the GPU session; finished clips are skipped on a rerun.
"""
import argparse
import gc
import glob
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

# `make kaggle-push` replaces None with the run_id of the jobs.json it uploaded, so a kernel that mounts an older
# version of the job dataset stops at once instead of re-rendering old jobs (it did, for 2 h 54 min, on 2026-11-25)
EXPECTED_RUN_ID = None

def log_line(out, doc, mock, **rec):
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": doc.get("run_id"),
            "mock": mock, "call_id": uuid.uuid4().hex[:12], "stage": "shots",
            "provider": "mock" if mock else "kaggle", "attempt": 1, **rec}
    with open(os.path.join(out, "runs.jsonl"), "a") as f:
        f.write(json.dumps(line) + "\n")


def find_jobs(arg):
    if arg:
        return arg
    for pattern in ("/kaggle/input/**/jobs.json", "/content/**/jobs.json", "jobs.json"):
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[0]
    sys.exit("jobs.json not found: attach the job dataset, or pass --jobs")


def mock_clip(png, path, p):
    n = p["num_frames"]
    w, h = p["width"], p["height"]
    vf = (f"scale={2 * w}:{2 * h}:force_original_aspect_ratio=increase,crop={2 * w}:{2 * h},"
          f"zoompan=z='1+0.1*on/{n}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={n}:s={w}x{h}:fps={p['fps']},format=yuv420p")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", png, "-vf", vf,
                    "-frames:v", str(n), "-c:v", "libx264", "-preset", "ultrafast", path], check=True)


def run_wan(jobs, base, out, p, doc):
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")   # less fragmentation
    import numpy as np
    import torch
    from diffusers import AutoencoderKLWan, WanImageToVideoPipeline, WanTransformer3DModel
    from diffusers.utils import export_to_video
    from PIL import Image, ImageOps

    t0 = time.time()
    gpu = torch.cuda.get_device_name(0)
    dtype = {"fp16": torch.float16, "bf16": torch.bfloat16, "fp32": torch.float32}[p["dtype"]]
    vae = AutoencoderKLWan.from_pretrained(p["model"], subfolder="vae", torch_dtype=torch.float32)
    pipe = WanImageToVideoPipeline.from_pretrained(p["model"], vae=vae, transformer=None, torch_dtype=dtype)
    pipe.text_encoder.to("cuda")
    embeds = {}
    with torch.no_grad():
        for j in jobs:
            pe, ne = pipe.encode_prompt(prompt=j["prompt"], negative_prompt=j["negative"],
                                        do_classifier_free_guidance=p["guidance"] > 1,
                                        max_sequence_length=512, device="cuda")
            embeds[j["key"]] = (pe.cpu(), None if ne is None else ne.cpu())
    pipe.text_encoder = None                      # free ~11 GB before the 5B transformer arrives
    gc.collect()
    torch.cuda.empty_cache()
    pipe.register_modules(transformer=WanTransformer3DModel.from_pretrained(
        p["model"], subfolder="transformer", torch_dtype=dtype))
    pipe.enable_model_cpu_offload()

    def vae_off(module, args, kwargs):
        # Image-to-video encodes the first frame with the VAE *before* the transformer runs, and model CPU offload
        # only offloads in sequence order (text_encoder -> transformer -> vae), so the 2.8 GB fp32 VAE stayed on
        # the GPU next to the 10 GB transformer: CUDA OOM at step 0 on a 15 GB T4 (kernel v1, 2026-11-24).
        # Move it off before each transformer call; its own offload hook brings it back for decoding.
        if next(pipe.vae.parameters()).device.type == "cuda":
            pipe.vae.to("cpu")
            torch.cuda.empty_cache()

    pipe.transformer.register_forward_pre_hook(vae_off, with_kwargs=True)
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass
    load_s = round(time.time() - t0, 1)
    log_line(out, doc, False, item="_load", model=p["model"], params={"dtype": p["dtype"]}, seed=None,
             status="ok", latency_s=load_s, gpu_s=load_s, gpu=gpu)
    print(f"models loaded in {load_s}s on {gpu}", flush=True)

    keep = ("width", "height", "num_frames", "fps", "steps", "guidance", "dtype")
    for j in jobs:
        final = os.path.join(out, j["key"] + ".mp4")
        tmp = final + ".tmp.mp4"
        image = ImageOps.fit(Image.open(os.path.join(base, j["keyframe"])).convert("RGB"),
                             (p["width"], p["height"]), Image.LANCZOS)
        pe, ne = embeds[j["key"]]
        torch.cuda.reset_peak_memory_stats()
        t1, err = time.time(), None
        try:
            with torch.no_grad():
                frames = pipe(image=image, prompt_embeds=pe.to("cuda"),
                              negative_prompt_embeds=None if ne is None else ne.to("cuda"),
                              height=p["height"], width=p["width"], num_frames=p["num_frames"],
                              num_inference_steps=p["steps"], guidance_scale=p["guidance"],
                              generator=torch.Generator("cpu").manual_seed(j["seed"]), output_type="np").frames[0]
            if not np.isfinite(frames).all() or float(frames.std()) < 0.01:
                raise RuntimeError("blank or NaN frames (fp16 overflow?): try dtype bf16, or Ken Burns for this shot")
            export_to_video(list(frames), tmp, fps=p["fps"])
            os.replace(tmp, final)
        except Exception as e:                       # log and move on to the next shot
            err = f"{type(e).__name__}: {e}"[:400]
            gc.collect()
            torch.cuda.empty_cache()
        dt = round(time.time() - t1, 1)
        log_line(out, doc, False, item=j["shot"], model=p["model"], params={k: p[k] for k in keep}, seed=j["seed"],
                 status="error" if err else "ok", error=err, latency_s=dt, gpu_s=dt, gpu=gpu,
                 peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2), input_hash=j["key"])
        print(f"{j['shot']}: {'FAILED ' + err if err else 'ok'} in {dt}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Wan 2.2 TI2V-5B image-to-video worker")
    ap.add_argument("--jobs", help="path to jobs.json (default: search /kaggle/input and /content)")
    ap.add_argument("--out", default="/kaggle/working" if os.path.isdir("/kaggle/working") else "shots_out")
    ap.add_argument("--mock", action="store_true", help="no GPU: Ken Burns stand-ins via ffmpeg")
    ap.add_argument("--no-install", action="store_true", help="skip pip install (deps already present)")
    ap.add_argument("--limit", type=int, default=0, help="render only the first N jobs (benchmark)")
    a = ap.parse_args()

    jobs_path = find_jobs(a.jobs)
    base = os.path.dirname(os.path.abspath(jobs_path))
    with open(jobs_path) as f:
        doc = json.load(f)
    if EXPECTED_RUN_ID and doc.get("run_id") != EXPECTED_RUN_ID:
        sys.exit(f"jobs.json is from run {doc.get('run_id')}, but this kernel was pushed for run {EXPECTED_RUN_ID}: "
                 "Kaggle mounted an older version of the job dataset. Run `make kaggle-push` again.")
    p = doc["params"]
    os.makedirs(a.out, exist_ok=True)
    todo = [j for j in doc["jobs"][: a.limit or None] if not os.path.exists(os.path.join(a.out, j["key"] + ".mp4"))]
    print(f"{len(doc['jobs'])} job(s), {len(todo)} to render -> {a.out}", flush=True)
    if not todo:
        return
    if a.mock:
        for j in todo:
            t0 = time.time()
            mock_clip(os.path.join(base, j["keyframe"]), os.path.join(a.out, j["key"] + ".mp4"), p)
            log_line(a.out, doc, True, item=j["shot"], model="mock-wan", params=p, seed=j["seed"], status="ok",
                     latency_s=round(time.time() - t0, 2), input_hash=j["key"])
        return
    if not a.no_install:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "diffusers>=0.35", "accelerate",
                               "ftfy", "imageio", "imageio-ffmpeg"])
    run_wan(todo, base, a.out, p, doc)


if __name__ == "__main__":
    main()
