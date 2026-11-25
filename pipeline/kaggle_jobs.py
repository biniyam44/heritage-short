"""GPU jobs on Kaggle (Wan 2.2 shots, ACE-Step music) using the official kaggle CLI.

  make shots            writes build/real/kaggle/shots/ (jobs.json + keyframes + worker) and shots.zip
  make kaggle-push      uploads it as a private dataset and starts a GPU T4 x2 script kernel
  make kaggle-status    shows the kernel status
  make kaggle-pull      downloads the kernel output into inbox/shots/ (its log also to outputs/logs/);
                        then `make shots` imports it
Manual fallback without the CLI: kaggle/README.md, then `make kaggle-import KIND=shots ZIP=...`.
Clips come back named by input hash, so a stale clip can never be imported for a changed shot.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .common import INBOX, OUT, ROOT, RUN_ID, WORK, fail, file_sha, import_runs, say

WORKERS = {"shots": "wan22_i2v.py", "music": "acestep_music.py"}
KERNELS = {"shots": "heritage-wan22", "music": "heritage-acestep"}
DATASETS = {"shots": "heritage-shots-job", "music": "heritage-music-job"}


def bundle_dir(kind: str) -> Path:
    return WORK.parent / "kaggle" / kind


def write_bundle(kind: str, jobs: list[dict], params: dict) -> Path | None:
    """jobs.json + input files + the worker script, as a folder and a zip (for manual upload)."""
    bundle = bundle_dir(kind)
    shutil.rmtree(bundle, ignore_errors=True)
    bundle.with_suffix(".zip").unlink(missing_ok=True)
    if not jobs:
        return None
    bundle.mkdir(parents=True)
    for j in jobs:
        src = j.pop("src", None)
        if src:
            shutil.copy(src, bundle / j["keyframe"])
    doc = {"kind": kind, "run_id": RUN_ID, "params": params, "jobs": jobs}
    (bundle / "jobs.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    shutil.copy(ROOT / "kaggle" / WORKERS[kind], bundle / WORKERS[kind])
    shutil.make_archive(str(bundle), "zip", bundle)
    return bundle


def run_worker(kind: str, bundle: Path, *, mock: bool = False, api_url: str | None = None) -> None:
    """Run the exact worker file that goes to Kaggle, locally (mock mode, or a local ACE-Step server)."""
    cmd = [sys.executable, str(bundle / WORKERS[kind]), "--jobs", str(bundle / "jobs.json"), "--out", str(INBOX / kind)]
    if mock:
        cmd.append("--mock")
    if api_url:
        cmd += ["--api-url", api_url]
    subprocess.run(cmd, check=True)
    import_runs(INBOX / kind / "runs.jsonl")


def kaggle_exe() -> str | None:
    """The kaggle CLI on PATH, or where `uv tool install kaggle` puts it (~/.local/bin)."""
    local = Path.home() / ".local" / "bin" / "kaggle"
    return shutil.which("kaggle") or (str(local) if local.exists() else None)


def kaggle(*args, check: bool = True, live: bool = False) -> subprocess.CompletedProcess:
    """Run the kaggle CLI. live=True shows its output (download progress) as it happens, not afterwards."""
    exe = kaggle_exe() or fail("kaggle CLI not found. Install:  uv tool install kaggle   then  kaggle auth login")
    print("$ kaggle " + " ".join(map(str, args)), flush=True)
    if live:
        r = subprocess.run([exe, *map(str, args)], text=True)
    else:
        r = subprocess.run([exe, *map(str, args)], text=True, capture_output=True)
        print((r.stdout + r.stderr).strip(), flush=True)
    if check and r.returncode:
        fail(f"kaggle {' '.join(map(str, args[:2]))} failed (exit {r.returncode})")
    return r


def user() -> str:
    return os.environ.get("KAGGLE_USERNAME", "").strip() or fail("set KAGGLE_USERNAME in .env (your Kaggle handle)")


def wait_for_version(kind: str, ds: str, run_id: str, minutes: int = 15) -> None:
    """Start the kernel only once Kaggle serves the jobs.json just uploaded. `datasets status` says "ready" while
    the previous version is still the current one: on 2026-11-25 the kernel mounted yesterday's jobs and spent
    2 h 54 min of GPU re-rendering 7 old clips. Downloading jobs.json and comparing its run_id can't be fooled."""
    check = WORK / "kaggle" / "version-check"
    for _ in range(minutes * 4):
        shutil.rmtree(check, ignore_errors=True)
        check.mkdir(parents=True)
        kaggle("datasets", "download", ds, "-f", "jobs.json", "-p", check, "--force", check=False)
        for z in check.glob("*.zip"):
            shutil.unpack_archive(z, check)
        try:
            served = json.loads((check / "jobs.json").read_text()).get("run_id")
        except (OSError, ValueError):
            served = None
        if served == run_id:
            say("kaggle", f"Kaggle now serves the new jobs.json (run {run_id})")
            return
        say("kaggle", f"Kaggle still serves run {served}; waiting for run {run_id}")
        time.sleep(15)
    fail(f"Kaggle still serves an older {ds} after {minutes} min, so the kernel was not started. "
         f"Run `make kaggle-push KIND={kind}` again later.")


def push(kind: str) -> None:
    bundle = bundle_dir(kind)
    if not (bundle / "jobs.json").exists():
        fail(f"no pending {kind} jobs. Run `make {kind}` first.")
    ds = f"{user()}/{DATASETS[kind]}"
    (bundle / "dataset-metadata.json").write_text(json.dumps(
        {"title": DATASETS[kind], "id": ds, "licenses": [{"name": "CC0-1.0"}]}, indent=2))
    run_id = json.loads((bundle / "jobs.json").read_text())["run_id"]
    if kaggle("datasets", "status", ds, check=False).returncode == 0:
        kaggle("datasets", "version", "-p", bundle, "-m", f"jobs {run_id}")
    else:
        kaggle("datasets", "create", "-p", bundle)
    wait_for_version(kind, ds, run_id)
    kdir = bundle.parent / f"{kind}-kernel"
    shutil.rmtree(kdir, ignore_errors=True)
    kdir.mkdir(parents=True)
    # the kernel's copy of the worker knows which jobs.json it was pushed for, and refuses any other
    src = (ROOT / "kaggle" / WORKERS[kind]).read_text()
    if "EXPECTED_RUN_ID = None" not in src:
        fail(f"kaggle/{WORKERS[kind]} has no `EXPECTED_RUN_ID = None` line to fill in")
    (kdir / WORKERS[kind]).write_text(src.replace("EXPECTED_RUN_ID = None", f'EXPECTED_RUN_ID = "{run_id}"', 1))
    meta = {"id": f"{user()}/{KERNELS[kind]}", "title": KERNELS[kind], "code_file": WORKERS[kind],
            "language": "python", "kernel_type": "script", "is_private": "true", "enable_gpu": "true",
            "enable_internet": "true", "machine_shape": "NvidiaTeslaT4", "dataset_sources": [ds]}
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    kaggle("kernels", "push", "-p", kdir, "--accelerator", "NvidiaTeslaT4")
    say("kaggle", f"kernel started. `make kaggle-status KIND={kind}`; when complete `make kaggle-pull KIND={kind}` "
                  f"then `make {kind}`")


def flatten(dest: Path) -> None:
    """Unzip downloads and lift clips / audio / runs.jsonl to the top of inbox/<kind>/."""
    for z in list(dest.rglob("*.zip")):
        shutil.unpack_archive(z, z.parent)
        z.unlink()
    for f in list(dest.rglob("*")):
        if not f.is_file() or f.parent == dest:
            continue
        if f.name == "runs.jsonl":
            with (dest / "runs.jsonl").open("a") as out:
                out.write(f.read_text())
            f.unlink()
        elif f.suffix in (".mp4", ".wav", ".flac", ".log"):
            os.replace(f, dest / f.name)


def pull(kind: str, attempts: int = 5) -> None:
    """Download the kernel's output. No `-o`: the CLI then skips files it already has complete and resumes broken
    ones, so a dropped connection costs a retry, not the whole download (2026-11-25: with -o, a 19 MB take that
    had arrived was fetched again from zero, and the pull died at 30 kB/s). Clips and takes are named by input
    hash, so a file with the same name is the same content."""
    dest = INBOX / kind
    dest.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, attempts + 1):
        if kaggle("kernels", "output", f"{user()}/{KERNELS[kind]}", "-p", dest, check=False, live=True).returncode == 0:
            break
        if attempt < attempts:
            say("kaggle", f"download attempt {attempt}/{attempts} failed; retrying in 10 s (finished files are kept)")
            time.sleep(10)
    else:
        fail(f"the {kind} output is still incomplete after {attempts} attempts: run `make kaggle-pull KIND={kind}` again")
    flatten(dest)
    keep_logs(dest)
    say("kaggle", f"downloaded into {dest}. Now run `make {kind}` to import.")


def keep_logs(dest: Path) -> None:
    """A kernel log is the evidence for its GPU time and errors, but inbox/ is git-ignored and the next pull
    overwrites it: keep a copy of each distinct log in outputs/logs/, named by a hash of its content."""
    for f in dest.glob("*.log"):
        out = OUT / "logs" / f"{f.stem}_{file_sha(f)[:8]}.log"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, out)
            say("kaggle", f"kernel log kept as {out.relative_to(ROOT)}")


def import_zip(kind: str, path: str) -> None:
    src = Path(path or "").expanduser()
    if not src.exists():
        fail("usage: make kaggle-import KIND=shots ZIP=~/Downloads/output.zip (a zip or a folder)")
    dest = INBOX / kind
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
    else:
        shutil.unpack_archive(src, dest)
    flatten(dest)
    say("kaggle", f"imported into {dest}. Now run `make {kind}`.")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("push", "status", "pull", "import") or sys.argv[2] not in WORKERS:
        fail("usage: python -m pipeline.kaggle_jobs push|status|pull|import shots|music [zip]")
    action, kind = sys.argv[1], sys.argv[2]
    if action == "push":
        push(kind)
    elif action == "status":
        kaggle("kernels", "status", f"{user()}/{KERNELS[kind]}")
    elif action == "pull":
        pull(kind)
    else:
        import_zip(kind, sys.argv[3] if len(sys.argv) > 3 else "")
