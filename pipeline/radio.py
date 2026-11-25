"""Radio cut for user test #1: real narration + English subtitles over placeholder music, on black.

It uses the same timeline and audio mix as the film, so what testers say about pacing carries over.
"""
from __future__ import annotations

import shutil

from .assemble import build_mix, cues, text_overlays, timeline
from .common import CONFIG, OUT, WORK, fail, ffmpeg, load_storyboard, say, scaled
from .providers import mock_music


def main() -> None:
    sb = load_storyboard()
    a = CONFIG["assembly"]
    rows, t = timeline(sb)
    if not any(r["narr"] for r in rows):
        fail("no narration yet. Run `make narration` first.")
    end_dur = sb["end_card"].get("duration_s", a["end_card_s"])
    total = round(t + end_dur, 3)
    work = WORK / "radio"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    mock_music(total + 1, work / "placeholder.wav")
    build_mix(rows, total, work / "placeholder.wav", work / "mix.wav", work)
    w, h = scaled(*a["master"])
    text_args, graph = text_overlays(cues(rows), sb["end_card"]["lines"], t, end_dur, w, h, work, "radio")
    out = OUT / "radio" / "radio_cut.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={a['fps']}:d={total}", "-i", "mix.wav", *text_args,
           "-filter_complex", graph, "-map", "[vout]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
           "-tune", "stillimage", "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-t", f"{total:.3f}", "-movflags", "+faststart", out, cwd=work)
    say("radio", f"wrote {out} ({total:.1f}s). Play it to 3+ people; write what they said in DESIGN.md.")


if __name__ == "__main__":
    main()
