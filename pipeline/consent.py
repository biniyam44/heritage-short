"""Consent gate: refuses to depict or voice a real person until ETHICS.md holds a complete consent record.

A character (or the voice) with "real_person": true must name a consent_id (C1, C2, ...) that appears as a
row of the "Consent records" table in ETHICS.md, covering the right scope ("likeness" to be shown,
"voice" to be voiced), with a date, how consent was given, and "yes" for public posting.
Real mode exits with code 3; mock mode only warns. Run `make consent` to see the status.
"""
from __future__ import annotations

import re

from .common import MOCK, ROOT, fail, load_storyboard, say

FIELDS = ["id", "person", "relationship", "scope", "how", "date", "public_ok", "withdrawal"]


def records(path=ROOT / "ETHICS.md") -> dict[str, dict]:
    if not path.exists():
        return {}
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.S)  # ignore commented examples
    found = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= len(FIELDS) and re.fullmatch(r"C\d+", cells[0]):
            found[cells[0]] = dict(zip(FIELDS, cells))
    return found


def problems(sb: dict) -> list[str]:
    recs, out = records(), []

    def check(cid, who, scope):
        r = recs.get(cid or "")
        if not r:
            out.append(f"{who}: no consent record '{cid}' in ETHICS.md")
            return
        if scope not in r["scope"].lower():
            out.append(f"{who}: record {cid} does not cover '{scope}'")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]):
            out.append(f"{who}: record {cid} needs a date (YYYY-MM-DD)")
        if not r["how"] or "todo" in " ".join(r.values()).lower():
            out.append(f"{who}: record {cid} is incomplete")
        if r["public_ok"].lower() not in ("yes", "y"):
            out.append(f"{who}: record {cid} does not allow public posting")

    for c in sb["characters"]:
        if c["real_person"]:
            check(c.get("consent_id"), f"character '{c['id']}'", "likeness")
    if sb["voice"].get("real_person"):
        check(sb["voice"].get("consent_id"), "narration voice", "voice")
    return out


def require(sb: dict, stage: str) -> None:
    found = problems(sb)
    if not found:
        return
    if MOCK:
        say(stage, "consent WARNING (mock mode, not blocking): " + "; ".join(found))
        return
    fail("consent gate: " + "; ".join(found) + "\nAdd the record(s) to the 'Consent records' table in ETHICS.md.", 3)


if __name__ == "__main__":
    sb = load_storyboard()
    real = [c["id"] for c in sb["characters"] if c["real_person"]] + (["voice"] if sb["voice"].get("real_person") else [])
    found = problems(sb)
    print(f"real people in storyboard: {real or 'none'}; consent records in ETHICS.md: {sorted(records()) or 'none'}")
    print("consent gate: OK" if not found else "consent gate: BLOCKED\n  " + "\n  ".join(found))
