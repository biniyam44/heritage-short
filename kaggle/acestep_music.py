#!/usr/bin/env python3
"""ACE-Step 1.5 music worker. Standalone file; uses the ACE-Step REST API:
POST /release_task -> data.task_id; POST /query_result -> status 0 running / 1 done / 2 failed,
result = JSON string with items[].file ("/v1/audio?path=..."); GET that URL for the audio.

  --api-url http://localhost:8001   use a server you already run, e.g. on your Mac:
        git clone https://github.com/ACE-Step/ACE-Step-1.5 ~/ACE-Step-1.5 && cd ~/ACE-Step-1.5 && uv sync
        ACESTEP_INIT_LLM=false uv run acestep-api            # first start downloads ~10 GB of checkpoints
  (no --api-url: Kaggle/Colab GPU)  clones ACE-Step-1.5, `uv sync`, starts the server here, then generates
  --mock                            offline placeholder chord via ffmpeg (plumbing test)
Output: <out>/<key>.wav per job, and <out>/runs.jsonl: one line per take, plus a `_load` line for the set-up
(clone, install, server start, model load) when this worker starts the server itself.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

# `make kaggle-push` replaces None with the run_id of the jobs.json it uploaded, so a kernel that mounts an older
# version of the job dataset stops at once instead of re-rendering old jobs (the Wan kernel did, on 2026-11-25)
EXPECTED_RUN_ID = None

def log_line(out, doc, mock, **rec):
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": doc.get("run_id"),
            "mock": mock, "call_id": uuid.uuid4().hex[:12], "stage": "music",
            "provider": "mock" if mock else "acestep", "attempt": 1, **rec}
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


def start_server(port=8001):
    repo = "/tmp/ACE-Step-1.5"                       # outside /kaggle/working so it is not downloaded as output
    if not os.path.isdir(repo):
        subprocess.check_call(["git", "clone", "--depth", "1", "https://github.com/ACE-Step/ACE-Step-1.5.git", repo])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "uv"])
    subprocess.check_call([sys.executable, "-m", "uv", "sync"], cwd=repo)
    env = {**os.environ, "ACESTEP_INIT_LLM": "false", "ACESTEP_USE_FLASH_ATTENTION": "false",
           "ACESTEP_API_PORT": str(port)}           # DiT only; T4 has no FlashAttention 2
    log = open("/tmp/acestep_server.log", "w")
    subprocess.Popen([sys.executable, "-m", "uv", "run", "acestep-api"], cwd=repo, env=env, stdout=log,
                     stderr=subprocess.STDOUT)
    return f"http://127.0.0.1:{port}"


def wait_ready(requests, url, headers, timeout_s=2400):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if requests.get(url + "/health", headers=headers, timeout=5).json()["data"]["status"] == "ok":
                return
        except Exception:
            pass
        time.sleep(5)
    sys.exit(f"ACE-Step server at {url} not ready after {timeout_s}s (see /tmp/acestep_server.log)")


def generate(requests, url, headers, job, p, path):
    body = {"prompt": job["prompt"], "lyrics": job["lyrics"], "audio_duration": p["duration_s"],
            "inference_steps": p["steps"], "guidance_scale": p["guidance"], "use_random_seed": False,
            "seed": job["seed"], "batch_size": 1, "audio_format": "wav", "thinking": False, "model": p["model"]}
    r = requests.post(url + "/release_task", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    task = r.json()["data"]["task_id"]
    deadline = time.time() + 1800
    while time.time() < deadline:
        r = requests.post(url + "/query_result", json={"task_id_list": [task]}, headers=headers, timeout=60)
        r.raise_for_status()
        q = r.json()["data"][0]
        if q["status"] == 1:
            items = json.loads(q["result"]) if isinstance(q["result"], str) else q["result"]
            file_url = items[0]["file"]
            audio = requests.get(url + file_url if file_url.startswith("/") else file_url, headers=headers, timeout=300)
            audio.raise_for_status()
            with open(path, "wb") as f:
                f.write(audio.content)
            return items[0]
        if q["status"] == 2:
            raise RuntimeError(f"ACE-Step task failed: {str(q.get('result'))[:300]}")
        time.sleep(3)
    raise TimeoutError("ACE-Step task did not finish within 30 min")


def main():
    ap = argparse.ArgumentParser(description="ACE-Step 1.5 music worker")
    ap.add_argument("--jobs")
    ap.add_argument("--out", default="/kaggle/working" if os.path.isdir("/kaggle/working") else "music_out")
    ap.add_argument("--api-url", help="use this running ACE-Step server instead of starting one")
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()

    jobs_path = find_jobs(a.jobs)
    with open(jobs_path) as f:
        doc = json.load(f)
    if EXPECTED_RUN_ID and doc.get("run_id") != EXPECTED_RUN_ID:
        sys.exit(f"jobs.json is from run {doc.get('run_id')}, but this kernel was pushed for run {EXPECTED_RUN_ID}: "
                 "Kaggle mounted an older version of the job dataset. Run `make kaggle-push KIND=music` again.")
    p = doc["params"]
    os.makedirs(a.out, exist_ok=True)
    todo = [j for j in doc["jobs"] if not os.path.exists(os.path.join(a.out, j["key"] + ".wav"))]
    print(f"{len(todo)} music job(s) -> {a.out}", flush=True)
    url, headers, failed = None, {}, 0
    for j in todo:
        path = os.path.join(a.out, j["key"] + ".wav")
        if a.mock:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                            f"sine=f=196:r=48000:d={p['duration_s']}", "-af",
                            "tremolo=f=0.3:d=0.5,volume=0.4,aformat=channel_layouts=stereo", path], check=True)
            log_line(a.out, doc, True, item=j.get("item", "score"), model="mock-music", params=p, seed=j["seed"],
                     status="ok", latency_s=0.0, input_hash=j["key"])
            continue
        import requests
        if url is None:                    # start (or reach) the server once, for every take in this run
            headers = {"Authorization": f"Bearer {os.environ['ACESTEP_API_KEY']}"} if os.environ.get("ACESTEP_API_KEY") else {}
            t_load = time.time()
            url = a.api_url or start_server()
            wait_ready(requests, url, headers, timeout_s=15 if a.api_url else 2400)   # own server: model download
            if not a.api_url:              # clone + install + server start + model load use the GPU session too
                load_s = round(time.time() - t_load, 1)
                log_line(a.out, doc, False, item="_load", model=p["model"], params={"server": "acestep-api"},
                         seed=None, status="ok", latency_s=load_s, gpu_s=load_s, gpu="kaggle-T4")
                print(f"server ready in {load_s}s", flush=True)
        t0, err, info = time.time(), None, {}
        try:
            info = generate(requests, url, headers, j, p, path)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:400]
        dt = round(time.time() - t0, 1)
        log_line(a.out, doc, False, item=j.get("item", "score"), model=p["model"], params=p, seed=j["seed"],
                 status="error" if err else "ok", error=err, latency_s=dt, gpu_s=dt,
                 gpu="local" if a.api_url else "kaggle-T4", input_hash=j["key"],
                 dit_model=info.get("dit_model"), seed_value=info.get("seed_value"))
        print(f"{j.get('item', 'score')}: {'FAILED ' + err if err else 'ok'} in {dt}s", flush=True)
        failed += bool(err)                # one bad take must not cost the others
    if todo and failed == len(todo):
        sys.exit(1)


if __name__ == "__main__":
    main()
