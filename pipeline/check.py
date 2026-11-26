"""QA gate: checks the deliverables against the brief. Exit 1 on any FAIL (`--soft`: report only).

Checks: schema, 8-12 shots, consent, end card says AI, a voice take for every narration line,
both exports exist as H.264/AAC at the right size,
60-90 s, measured loudness near -14 LUFS with true peak <= -1 dBTP, subtitle line limits and reading
speed, no Ken Burns/placeholder stand-ins left, and no secret from .env inside any repo file.
"""
from __future__ import annotations

import json
import os
import re
import sys

from .common import CONFIG, MOCK, OUT, ROOT, RUNS, STORYBOARD, loudnorm_json, probe, read_meta, scaled, schema_errors
from .consent import problems as consent_problems

SKIP_DIRS = {".git", ".venv", "build", "inbox", "__pycache__", "outputs"}


def secret_hits() -> list[str]:
    secrets = []
    env = ROOT / ".env"
    if env.exists():
        secrets = [l.split("=", 1)[1].strip().strip("'\"") for l in env.read_text().splitlines()
                   if "=" in l and not l.lstrip().startswith("#")]
        secrets = [s for s in secrets if len(s) >= 16]
    hits = []
    for dirpath, dirnames, files in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in files:
            path = os.path.join(dirpath, name)
            if name == ".env" or os.path.getsize(path) > 5_000_000:
                continue
            try:
                text = open(path, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            if any(s in text for s in secrets) or re.search(r"AIza[0-9A-Za-z_\-]{35}", text):
                hits.append(os.path.relpath(path, ROOT))
    return hits


def main() -> None:
    soft = "--soft" in sys.argv
    res = []

    def add(ok, name, detail="", warn_only=False):
        res.append(("PASS" if ok else ("WARN" if warn_only else "FAIL"), name, detail))

    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    errors = schema_errors(sb)
    add(not errors, "storyboard matches schema", "; ".join(errors[:3]))
    add(not sb.get("example"), "storyboard is the real story, not the example", "still the shipped example" if sb.get("example") else "",
        warn_only=MOCK)
    add(8 <= len(sb.get("shots", [])) <= 12, "8-12 shots", str(len(sb.get("shots", []))))
    cp = [] if errors else consent_problems(sb)
    add(not cp, "consent records for real people", "; ".join(cp), warn_only=MOCK)
    add(any(re.search(r"\bAI\b", line) for line in sb.get("end_card", {}).get("lines", [])), "end card says AI")
    # assembly quietly shows a line as subtitle-only when its voice file is missing, so catch that here
    mute = [s["id"] for s in sb.get("shots", [])
            if s.get("narration", "").strip() and not (OUT / "narration" / f"{s['id']}.wav").exists()]
    add(not mute, "every narration line has a voice take", ",".join(mute) + (": run `make narration`" if mute else ""))

    a = CONFIG["assembly"]
    for e in a["exports"]:
        f = OUT / "film" / f"{e['name']}.mp4"
        if not f.exists():
            add(False, f"{e['name']}.mp4 exists", "run `make film`")
            continue
        info = probe(f)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        au = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
        w, h = scaled(e["width"], e["height"])
        add(v["codec_name"] == "h264" and au.get("codec_name") == "aac" and (v["width"], v["height"]) == (w, h),
            f"{e['name']}: H.264/AAC {w}x{h}", f"{v['codec_name']}/{au.get('codec_name')} {v['width']}x{v['height']}")
        dur = float(info["format"]["duration"])
        add(60 <= dur <= 90, f"{e['name']}: 60-90 s", f"{dur:.1f}s")
        L = loudnorm_json(f)
        i, tp = float(L["input_i"]), float(L["input_tp"])
        add(abs(i - a["loudness"]["I"]) <= 1 and tp <= a["loudness"]["TP"],
            f"{e['name']}: loudness", f"{i:.1f} LUFS, true peak {tp:.1f} dBTP")

    tl = OUT / "film" / "timeline.json"
    if tl.exists():
        cue_list = json.loads(tl.read_text())["cues"]
        long_lines = [c["shot"] for c in cue_list if len(c["lines"]) > a["sub_max_lines"]
                      or any(len(x) > a["sub_max_chars"] + 4 for x in c["lines"])]
        add(not long_lines, f"subtitles <= {a['sub_max_lines']} lines of ~{a['sub_max_chars']} chars", ",".join(long_lines))
        fast = [c["shot"] for c in cue_list if len(" ".join(c["lines"])) / max(0.1, c["end"] - c["start"]) > 20]
        add(not fast, "subtitle reading speed <= 20 chars/s", ",".join(sorted(set(fast))), warn_only=True)

    standins = [s["id"] for s in sb.get("shots", []) if (read_meta(OUT / "shots" / f"{s['id']}.mp4") or {}).get("fallback_for")]
    if (read_meta(OUT / "music" / "score.wav") or {}).get("fallback_for"):
        standins.append("music")
    add(not standins, "no stand-ins (pending Wan clips / placeholder score)", ",".join(standins),
        warn_only=MOCK or os.environ.get("ALLOW_FALLBACK") == "1")
    hits = secret_hits()
    add(not hits, "no secrets in repo files", ", ".join(hits))
    add(".env" in (ROOT / ".gitignore").read_text().split(), ".env is git-ignored")
    real = sum(1 for l in RUNS.read_text().splitlines() if l.strip()) if RUNS.exists() else 0
    add(real > 0, f"{RUNS.name} has logged calls", str(real), warn_only=True)

    for status, name, detail in res:
        print(f"  {status}  {name}" + (f"  ({detail})" if detail else ""))
    fails = sum(1 for r in res if r[0] == "FAIL")
    print(f"check: {fails} FAIL, {sum(1 for r in res if r[0] == 'WARN')} WARN")
    if fails and not soft:
        sys.exit(1)


if __name__ == "__main__":
    main()
