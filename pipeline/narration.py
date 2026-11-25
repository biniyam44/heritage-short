"""Stage 5: narration, one TTS call per shot line (Gemini TTS).

One file per shot (not one long take) so that editing one line re-synthesises only that line.
The cache key is model + voice + style + text: change a word in s04 and only s04 is regenerated.
"""
from __future__ import annotations

import time

from .common import CONFIG, MOCK, OUT, build, call_model, load_storyboard, say, selected
from .consent import require
from .providers import gemini_cost, gemini_tts, mock_tts


def main() -> None:
    sb = load_storyboard()
    require(sb, "narration")
    model, voice = CONFIG["tts"]["model"], sb["voice"]
    interval, last = (0 if MOCK else CONFIG["tts"].get("min_interval_s", 0)), [0.0]

    def pace():                                   # free tier allows 3 requests/min: space the calls out
        wait = interval - (time.monotonic() - last[0])
        if wait > 0 and last[0]:
            say("narration", f"waiting {wait:.0f}s (rate limit)")
            time.sleep(wait)
        last[0] = time.monotonic()

    for s in selected(sb["shots"]):
        text = s["narration"].strip()
        if not text:
            continue                                  # a silent beat
        out = OUT / "narration" / f"{s['id']}.wav"
        inputs = {"v": 1, "model": model, "voice": voice["name"], "style": voice["style"], "text": text,
                  "language": sb["language"]["code"]}

        def make(tmp):
            if MOCK:
                call_model(stage="narration", item=s["id"], provider="mock", model="mock-tts",
                           params={"chars": len(text)}, seed=None, fn=lambda: mock_tts(text, tmp))
                return
            pace()
            wav, _ = call_model(stage="narration", item=s["id"], provider="gemini", model=model,
                                params={"voice": voice["name"], "style": voice["style"], "chars": len(text),
                                        "language": sb["language"]["code"]}, seed=None,
                                fn=lambda: gemini_tts(text, voice=voice["name"], style=voice["style"], model=model),
                                cost=lambda r: gemini_cost(model, r[1]))
            tmp.write_bytes(wav)

        build("narration", out, inputs, make)
    say("narration", f"done -> {OUT / 'narration'}")


if __name__ == "__main__":
    main()
