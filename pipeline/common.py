"""Shared plumbing for every stage.

Each stage script has the same shape:
    sb = load_storyboard()                     # the contract, validated against schema/
    for each item (shot, character, ...):
        inputs = {...}                         # everything that can change this output
        build(stage, out_path, inputs, make)   # hash hit -> skip; miss -> make(tmp) -> atomic rename
Model calls go through call_model(): retries with backoff, one runs.jsonl line per attempt.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import random
import subprocess
import sys
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader (KEY=VALUE per line). Variables already set in the shell win."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if value.strip():
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(ROOT / ".env")

MOCK = os.environ.get("MOCK") == "1"
_MODE = "mock" if MOCK else "real"
OUT = Path(os.environ.get("OUT_DIR") or ROOT / ("build/mock/outputs" if MOCK else "outputs"))
RUNS = Path(os.environ.get("RUNS_FILE") or ROOT / ("build/mock/runs.jsonl" if MOCK else "runs.jsonl"))
INBOX = Path(os.environ.get("INBOX_DIR") or ROOT / ("build/mock/inbox" if MOCK else "inbox"))
WORK = Path(os.environ.get("WORK_DIR") or ROOT / "build" / _MODE / "work")
STORYBOARD = Path(os.environ.get("STORYBOARD") or ROOT / "storyboard.json")
CONFIG = tomllib.loads((ROOT / "config.toml").read_text())
RUN_ID = os.environ.get("RUN_ID") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
FORCE = {s for s in os.environ.get("FORCE", "").split(",") if s}   # e.g. FORCE=keyframes or FORCE=all
ONLY = {s for s in os.environ.get("ONLY", "").split(",") if s}     # e.g. ONLY=s03,s04


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def say(stage: str, msg: str) -> None:
    print(f"[{stage}] {msg}", flush=True)


def fail(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def scaled(w: int, h: int) -> tuple[int, int]:
    """Mock mode renders smaller for speed. Sizes stay even (H.264 needs that)."""
    s = CONFIG["mock"]["scale"] if MOCK else 1
    return int(w * s) // 2 * 2, int(h * s) // 2 * 2


def x264_preset() -> str:
    return CONFIG["mock"]["preset"] if MOCK else CONFIG["assembly"]["preset"]


# ---------------------------------------------------------------- the contract
def schema_errors(sb: dict) -> list[str]:
    """JSON Schema errors first; if none, the cross-field checks a schema cannot express."""
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "schema" / "storyboard.schema.json").read_text())
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
              for e in Draft202012Validator(schema).iter_errors(sb)]
    if errors:
        return errors
    ids = [s["id"] for s in sb["shots"]]
    if len(ids) != len(set(ids)):
        errors.append("shots: ids must be unique")
    cast = {c["id"] for c in sb["characters"]}
    for s in sb["shots"]:
        errors += [f"{s['id']}: unknown character '{c}'" for c in s.get("characters", []) if c not in cast]
        if s.get("image") and not (ROOT / s["image"]).exists():
            errors.append(f"{s['id']}: image not found: {s['image']}")
    for c in sb["characters"]:
        if c.get("reference_photo") and not (ROOT / c["reference_photo"]).exists():
            errors.append(f"character {c['id']}: reference_photo not found: {c['reference_photo']}")
    return errors


def load_storyboard(path: Path = STORYBOARD) -> dict:
    try:
        sb = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read {path}: {e}", 2)
    errors = schema_errors(sb)
    if errors:
        fail(f"{path.name} does not match schema/storyboard.schema.json:\n  " + "\n  ".join(errors), 2)
    return sb


def selected(shots: list[dict]) -> list[dict]:
    return [s for s in shots if not ONLY or s["id"] in ONLY]


# ---------------------------------------------------------------- cache by input hash
def sha(obj) -> str:
    data = obj if isinstance(obj, bytes) else json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()[:16]


def file_sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def read_meta(out: Path) -> dict | None:
    """The sidecar <name>.json next to each output records its input hash and inputs."""
    meta = out.with_suffix(".json")
    return json.loads(meta.read_text()) if out.exists() and meta.exists() else None


def write_meta(out: Path, inputs: dict, **extra) -> None:
    record = {"input_hash": sha(inputs), "inputs": inputs, "created": now(), "run_id": RUN_ID, **extra}
    out.with_suffix(".json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")


def forced(stage: str) -> bool:
    return bool(FORCE & {stage, "all", "1"})


def changed_keys(old: dict, new: dict) -> list[str]:
    """Which inputs differ, e.g. ['prompt'] or ['narration.s03']: printed so a rerun explains itself."""
    keys = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        if isinstance(a, dict) and isinstance(b, dict):
            keys += [f"{k}.{sub}" for sub in changed_keys(a, b)]
        elif a != b:
            keys.append(k)
    return keys


def build(stage: str, out: Path, inputs: dict, make) -> bool:
    """Cache-or-generate one output. Returns True if it was (re)generated.

    make(tmp) writes the file; it is renamed into place only after it succeeded, so a crash or a
    failed API call never leaves a half-written file that would look cached next time."""
    meta = read_meta(out)
    key = sha(inputs)
    if meta and meta.get("input_hash") == key and not forced(stage):
        say(stage, f"{out.stem}: cached ({key})")
        return False
    why = "forced" if forced(stage) else (
        "changed: " + ", ".join(changed_keys(meta.get("inputs", {}), inputs)[:6]) if meta else "new")
    say(stage, f"{out.stem}: generating ({why})")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.stem}.tmp{out.suffix}")
    extra = make(tmp) or {}
    os.replace(tmp, out)
    write_meta(out, inputs, **extra)
    return True


# ---------------------------------------------------------------- run log + retries
class TransientError(Exception):
    """Worth retrying: rate limit, 5xx, timeout, malformed response."""
    retry_after: float | None = None


class FatalError(Exception):
    """Retrying will not help: bad key, bad request, daily quota used up, privacy refusal."""


def log_run(record: dict) -> None:
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    line = {"ts": now(), "run_id": RUN_ID, "mock": MOCK, "call_id": uuid.uuid4().hex[:12], **record}
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def call_model(*, stage, item, provider, model, params, seed, fn, cost=None, attempts=None):
    """Run fn() with exponential backoff on TransientError. Logs every attempt to runs.jsonl."""
    attempts = attempts or CONFIG["retries"]["attempts"]
    base = 0.05 if MOCK else CONFIG["retries"]["base_delay_s"]
    for attempt in range(1, attempts + 1):
        rec = {"stage": stage, "item": item, "provider": provider, "model": model,
               "params": params, "seed": seed, "attempt": attempt}
        t0 = time.monotonic()
        try:
            result = fn()
        except Exception as e:
            retry = isinstance(e, TransientError) and attempt < attempts
            log_run({**rec, "status": "error", "latency_s": round(time.monotonic() - t0, 3),
                     "error": f"{type(e).__name__}: {e}"[:500], "will_retry": retry})
            if not retry:
                raise
            delay = max(min(60.0, base * 2 ** (attempt - 1)) + random.uniform(0, base), e.retry_after or 0)
            say(stage, f"{item}: attempt {attempt} failed ({str(e)[:120]}); retrying in {delay:.1f}s")
            time.sleep(delay)
            continue
        try:
            spent = cost(result) if cost else None
        except Exception:           # a cost estimate must never fail a good call
            spent = None
        log_run({**rec, "status": "ok", "latency_s": round(time.monotonic() - t0, 3), "cost": spent})
        return result


def import_runs(path: Path) -> int:
    """Append a GPU worker's runs.jsonl lines (Kaggle / ACE-Step) to ours, once each (dedup by call_id)."""
    if not path.exists():
        return 0
    seen = set()
    if RUNS.exists():
        seen = {json.loads(l).get("call_id") for l in RUNS.read_text().splitlines() if l.strip()}
    new = [l for l in path.read_text().splitlines() if l.strip() and json.loads(l).get("call_id") not in seen]
    if new:
        RUNS.parent.mkdir(parents=True, exist_ok=True)
        with RUNS.open("a", encoding="utf-8") as f:
            f.writelines(l + "\n" for l in new)
    return len(new)


# ---------------------------------------------------------------- privacy guard
def privacy_check(text: str, provider: str) -> None:
    """Refuse to send any term listed in private_terms.txt (git-ignored) unless ALLOW_PRIVATE=1."""
    path = ROOT / "private_terms.txt"
    if os.environ.get("ALLOW_PRIVATE") == "1" or not path.exists():
        return
    terms = [t.strip() for t in path.read_text(encoding="utf-8").splitlines()
             if t.strip() and not t.startswith("#")]
    hits = [t for t in terms if t.casefold() in text.casefold()]
    if hits:
        raise FatalError(f"text for {provider} contains private term(s) {hits}. "
                         "Edit it, or rerun with ALLOW_PRIVATE=1 if you accept sending them.")


# ---------------------------------------------------------------- ffmpeg helpers
def ffmpeg(*args, cwd=None) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed ({r.returncode}): {r.stderr.strip()[-1500:]}")


def probe(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def duration(path) -> float:
    return float(probe(path)["format"]["duration"])


def loudnorm_json(path, af: str = "") -> dict:
    """loudnorm in measure mode (pass 1): integrated loudness, true peak, LRA, threshold, offset."""
    L = CONFIG["assembly"]["loudness"]
    chain = f"{af}loudnorm=I={L['I']}:TP={L['TP']}:LRA={L['LRA']}:print_format=json"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-af", chain,
                        "-f", "null", "-"], capture_output=True, text=True)
    s = r.stderr
    return json.loads(s[s.rindex("{"): s.rindex("}") + 1])


@functools.cache
def has_filter(name: str) -> bool:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in r.stdout.splitlines() if len(line.split()) > 1)


def fit_png(src, out, w: int, h: int) -> None:
    """Scale and centre-crop any image to exactly w x h, saved as PNG."""
    ffmpeg("-i", src, "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}",
           "-frames:v", "1", out)
