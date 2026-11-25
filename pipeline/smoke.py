"""Smoke test: one tiny call per provider, latency logged to runs.jsonl (stage "smoke").

Only harmless test text is sent, never your story. Set SMOKE_TTS_TEXT to a short neutral sentence
in your narration language to check that Gemini TTS speaks it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from .common import CONFIG, MOCK, WORK, TransientError, call_model, duration, has_filter, say
from .providers import (cloudflare_cost, cloudflare_image, gemini_cost, gemini_text, gemini_tts, image_ext,
                        mock_image, mock_tts)

NEEDED_FILTERS = ("overlay", "sidechaincompress", "loudnorm", "zoompan", "gblur", "tpad", "apad", "amix")


def main() -> None:
    d = WORK / "smoke"
    d.mkdir(parents=True, exist_ok=True)
    results = []

    def run(name, fn):
        t0 = time.monotonic()
        try:
            note = fn() or ""
            results.append((name, "ok", time.monotonic() - t0, str(note)))
        except Exception as e:
            results.append((name, "FAIL", time.monotonic() - t0, str(e)[:200]))

    def ffmpeg_ok():
        missing = [f for f in NEEDED_FILTERS if not has_filter(f)]
        if missing:
            raise RuntimeError(f"ffmpeg lacks {missing}")
        import PIL  # noqa: F401  (subtitles are drawn with Pillow)
        return "all filters present, Pillow ok"

    run("ffmpeg filters", ffmpeg_ok)
    tc, sc, ic = CONFIG["text"], CONFIG["tts"], CONFIG["image"]
    tts_text = os.environ.get("SMOKE_TTS_TEXT", "Hello, this is a short test of the narration voice.")

    if MOCK:
        run("mock tts", lambda: mock_tts(tts_text, d / "tts.wav"))
        run("mock image", lambda: mock_image("smoke", 256, 256, d / "image.png"))
    else:
        def text():                                  # same fallback order as `make draft`
            models = [tc["model"], *tc.get("fallback_models", [])]
            for i, m in enumerate(models):
                try:
                    reply, _ = call_model(stage="smoke", item="text", provider="gemini", model=m, params={},
                                          seed=None, attempts=2,
                                          fn=lambda: gemini_text("Reply with the single word OK.",
                                                                 system="You are a connectivity test.", model=m),
                                          cost=lambda r: gemini_cost(m, r[1]))
                    return f"reply {reply.strip()[:20]!r} from {m}" + (" (fallback)" if i else "")
                except TransientError:
                    if i == len(models) - 1:
                        raise

        def tts():
            wav, _ = call_model(stage="smoke", item="tts", provider="gemini", model=sc["model"],
                                params={"voice": "Kore"}, seed=None,
                                fn=lambda: gemini_tts(tts_text, voice="Kore", style="", model=sc["model"]),
                                cost=lambda r: gemini_cost(sc["model"], r[1]))
            (d / "tts.wav").write_bytes(wav)
            return f"{duration(d / 'tts.wav'):.1f}s of audio in {d / 'tts.wav'}"

        def image():
            data = call_model(stage="smoke", item="image", provider="cloudflare", model=ic["model"],
                              params={"width": 512, "height": 512}, seed=1,
                              fn=lambda: cloudflare_image("a red apple on a wooden table, soft daylight",
                                                          model=ic["model"], width=512, height=512, seed=1),
                              cost=lambda _: cloudflare_cost(ic["model"], 512, 512, 0))
            path = d / f"image{image_ext(data)}"
            path.write_bytes(data)
            return f"{len(data) // 1024} KB image in {path}"

        def kaggle():
            from .kaggle_jobs import kaggle_exe
            exe = kaggle_exe()
            if not exe:
                raise RuntimeError("kaggle CLI not installed (uv tool install kaggle)")
            def list_mine():
                r = subprocess.run([exe, "kernels", "list", "--mine", "--page-size", "1"],
                                   capture_output=True, text=True)
                if r.returncode:                      # show the CLI's own message (usually auth)
                    raise RuntimeError((r.stderr or r.stdout).strip()[-300:] or f"exit {r.returncode}")
                return r

            call_model(stage="smoke", item="kaggle", provider="kaggle", model="kaggle-cli", params={}, seed=None,
                       fn=list_mine)
            return "authenticated"

        def acestep():
            import requests
            url = os.environ.get("ACESTEP_API_URL") or CONFIG["music"]["api_url"]
            return requests.get(url + "/health", timeout=5).json()["data"]["status"] + f" at {url}"

        run(f"gemini text ({tc['model']})", text)
        run(f"gemini tts ({sc['model']})", tts)
        run(f"cloudflare ({ic['model'].split('/')[-1]})", image)
        run("kaggle cli", kaggle)
        if CONFIG["music"]["backend"] == "acestep_api":
            run("ace-step server", acestep)

    width = max(len(r[0]) for r in results)
    for name, status, secs, note in results:
        print(f"  {name:<{width}}  {status:<4}  {secs:6.2f}s  {note}")
    say("smoke", "all ok" if all(r[1] == "ok" for r in results) else "some checks failed (see above)")


if __name__ == "__main__":
    main()
