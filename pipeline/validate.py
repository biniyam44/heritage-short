"""Validate storyboard.json (schema + cross-field checks) and print the planned length."""
from .common import CONFIG, MOCK, STORYBOARD, load_storyboard, say

if __name__ == "__main__":
    sb = load_storyboard()
    a = CONFIG["assembly"]
    planned = sum(s["duration_s"] for s in sb["shots"]) + sb["end_card"].get("duration_s", a["end_card_s"])
    say("validate", f"{STORYBOARD.name} OK: {len(sb['shots'])} shots, planned {planned:.0f}s incl. end card, "
                    f"narration in {sb['language']['name']}")
    if not 60 <= planned <= 90:
        say("validate", "WARNING: the brief asks for 60-90 s")
    if sb.get("example") and not MOCK:
        say("validate", "NOTE: storyboard.json is still the shipped EXAMPLE. Fill story/brief.md and run `make draft`.")
