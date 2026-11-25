"""Stage 1: draft storyboard.json from story/brief.md with the text model (Gemini).

The LLM drafts; you own the result. The draft goes to outputs/script/storyboard.draft.json and only
replaces storyboard.json while that file is still the shipped example, so a rerun never overwrites your
edits. Once storyboard.json is yours the stage makes no model call (so `make film` works from a clean clone
without keys); FORCE=draft writes a fresh draft next to it for comparison. Invalid JSON or schema errors are
fed back to the model, up to 3 tries.
"""
from __future__ import annotations

import json
import shutil

from .common import (CONFIG, MOCK, OUT, ROOT, STORYBOARD, FatalError, TransientError, build, call_model, forced,
                     say, schema_errors, sha)
from .providers import gemini_cost, gemini_text

SYSTEM = """You turn a family story brief into a storyboard for a 60-90 second vertical (9:16) heritage short film.
Return ONLY one JSON object that validates against the JSON Schema you are given. Rules:
- 8 to 12 shots; the sum of duration_s plus end_card.duration_s must be 60 to 90.
- narration: in the narration language named in the brief, written for the ear, short sentences,
  about 2.5 words per second of duration_s at most.
- subtitle_en: a faithful English translation of that shot's narration, at most 80 characters.
- keyframe_prompt: what the camera sees; concrete and visual; no names; no text in the image.
- characters: appearance only, no names. real_person = true for anyone real, with consent_id "C1", "C2", ... in order.
- motion.backend: "wan" for natural motion (hands, fire, water, cloth, smoke) with a short motion.prompt;
  "kenburns" with a camera move for faces, portraits, archival photos and wide still scenes.
- purpose: one sentence on why this shot exists for this audience.
- Use only facts from the brief. Never invent biographical facts; keep unknowns general.
- end_card.lines must include the words "Made with AI".
- Set "version": 1, "example": false, and distinct integer seeds."""


def parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


def ask(prompt: str, attempt: int, brief_chars: int) -> tuple[str, str]:
    """The configured text model, then its fallbacks if it stays overloaded after retries."""
    models = [CONFIG["text"]["model"], *CONFIG["text"].get("fallback_models", [])]
    for i, m in enumerate(models):
        try:
            text, _ = call_model(stage="draft", item=f"storyboard#{attempt}", provider="gemini", model=m,
                                 params={"brief_chars": brief_chars}, seed=None,
                                 fn=lambda: gemini_text(prompt, system=SYSTEM, model=m),
                                 cost=lambda r: gemini_cost(m, r[1]))
            return text, m
        except TransientError:
            if i == len(models) - 1:
                raise
            say("draft", f"{m} still unavailable after retries; falling back to {models[i + 1]}")


def main() -> None:
    brief = (ROOT / "story" / "brief.md").read_text(encoding="utf-8")
    if "TEMPLATE:" in brief:
        say("draft", "story/brief.md is still the template: skipping (write your brief, then `make draft`)")
        return
    model = CONFIG["text"]["model"]
    schema = (ROOT / "schema" / "storyboard.schema.json").read_text()
    out = OUT / "script" / "storyboard.draft.json"
    inputs = {"v": 1, "model": model, "brief": sha(brief), "system": sha(SYSTEM), "schema": sha(schema)}

    def make(tmp):
        prompt = f"JSON Schema:\n{schema}\n\nStory brief:\n{brief}"
        used = model
        for attempt in range(1, 4):
            if MOCK:                                   # offline: echo the current storyboard
                text = STORYBOARD.read_text(encoding="utf-8")
            else:
                text, used = ask(prompt, attempt, len(brief))
            try:
                draft = parse_json(text)
                errors = schema_errors(draft)
            except ValueError as e:
                errors = [f"invalid JSON: {e}"]
            if not errors:
                tmp.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                return {"attempts": attempt, "model_used": used}
            say("draft", f"attempt {attempt}: {len(errors)} schema error(s); asking the model to fix them")
            prompt += "\n\nYour previous reply failed validation:\n" + "\n".join(errors[:25]) + \
                      "\nReturn the corrected, complete JSON object only."
        raise FatalError("draft still invalid after 3 attempts (errors above)")

    current = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    if not current.get("example") and not forced("draft"):
        # storyboard.json is yours: a new draft would be unused, and a clean clone must build without keys
        say("draft", f"storyboard.json is yours: no draft needed (FORCE=draft writes a fresh one to {out} to compare)")
        return
    generated = build("draft", out, inputs, make)
    if current.get("example"):
        shutil.copy(out, STORYBOARD)
        say("draft", "storyboard.json now holds the draft. Read and edit every line: it is yours.")
    elif generated:
        say("draft", f"new draft at {out}; storyboard.json unchanged (merge by hand)")


if __name__ == "__main__":
    main()
