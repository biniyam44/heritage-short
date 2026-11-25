"""Stage 6: assembly with FFmpeg.

1. Timeline: each shot lasts max(duration_s, lead-in + narration + tail), rounded to whole frames.
2. Audio: narration lines level-matched and placed on one bed; the score is ducked under it with
   sidechaincompress (threshold 0.02, ratio 6, attack 300 ms, release 1500 ms); then a two-pass
   loudnorm to -14 LUFS, true peak aimed 0.5 dB under -1 dBTP so the AAC file still meets it
   (pass 1 measures, pass 2 applies linearly).
3. Video per export: each clip is normalised (time-fit, scale/crop or blurred pillarbox), the end card is
   added, everything is concatenated, and English subtitles (at most 2 lines of ~40 chars, inside the
   9:16 safe area) plus the end-card text are burned in as Pillow-rendered PNG overlays. That works with
   any FFmpeg build (Homebrew's has no libass/drawtext). Output H.264/AAC MP4 plus an .srt sidecar.
The whole stage is skipped when none of its inputs changed (one hash over all of them).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import wave
from pathlib import Path

from .common import (CONFIG, OUT, WORK, changed_keys, duration, fail, ffmpeg, file_sha, forced, load_storyboard,
                     loudnorm_json, read_meta, say, scaled, sha, write_meta, x264_preset)
from .consent import require

STAGE_VERSION = 3          # 2: subtitles stay up long enough to read; 3: true-peak headroom for AAC
SR = 48000


# ---------------------------------------------------------------- timeline + subtitles
def timeline(sb: dict) -> tuple[list[dict], float]:
    a = CONFIG["assembly"]
    fps, t, rows = a["fps"], 0.0, []
    for s in sb["shots"]:
        rel = f"narration/{s['id']}.wav"
        has = bool(s["narration"].strip()) and (OUT / rel).exists()
        nl = round(duration(OUT / rel), 3) if has else 0.0
        need = a["lead_in_s"] + nl + a["tail_s"] if has else 0.0
        dur = math.ceil(max(s["duration_s"], need) * fps - 1e-6) / fps
        rows.append({"id": s["id"], "start": round(t, 3), "dur": round(dur, 3), "narr": rel if has else None,
                     "narr_len": nl, "subtitle": s["subtitle_en"].strip()})
        t += dur
    return rows, round(t, 3)


def wrap(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def balanced(words: list[str], width: int) -> list[str]:
    """One line if it fits, else the two-line split with the shortest longest line."""
    text = " ".join(words)
    if len(text) <= width or len(words) < 2:
        return [text]
    _, i = min((max(len(" ".join(words[:i])), len(" ".join(words[i:]))), i) for i in range(1, len(words)))
    return [" ".join(words[:i]), " ".join(words[i:])]


def cues(rows: list[dict]) -> list[dict]:
    """Subtitle cues of at most sub_max_lines lines, timed to the narration, split by character count."""
    a = CONFIG["assembly"]
    width, nmax = a["sub_max_chars"], a["sub_max_lines"]
    out = []
    for r in rows:
        if not r["subtitle"]:
            continue
        t0 = r["start"] + (a["lead_in_s"] if r["narr"] else 0.3)
        t1 = t0 + r["narr_len"] if r["narr"] else r["start"] + r["dur"] - 0.3
        # an English subtitle can be longer than the Amharic line it translates: keep it up long enough
        # to read (~15 chars/s), but never past the end of its shot
        t1 = max(t1, min(t0 + len(r["subtitle"]) / 15, r["start"] + r["dur"] - 0.2))
        lines = wrap(r["subtitle"], width)
        chunks = [balanced(" ".join(lines[i:i + nmax]).split(), width) if nmax > 1 else lines[i:i + 1]
                  for i in range(0, len(lines), nmax)]
        total, t = sum(len(" ".join(c)) for c in chunks), t0
        for c in chunks:
            d = (t1 - t0) * len(" ".join(c)) / total
            out.append({"shot": r["id"], "start": round(t, 2), "end": round(t + d, 2), "lines": c})
            t += d
    return out


FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]


ETHIOPIC_FONTS = ["/System/Library/Fonts/Supplemental/KefaIII.ttf", "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
                  "/usr/share/fonts/truetype/abyssinica/AbyssinicaSIL-Regular.ttf", "C:/Windows/Fonts/nyala.ttf"]


def _font(size: int, text: str = ""):
    """Latin font by default; an Ethiopic font for lines in Ge'ez script (e.g. an Amharic title)."""
    from PIL import ImageFont

    ethiopic = any("\u1200" <= ch <= "\u139f" or "\u2d80" <= ch <= "\u2ddf" for ch in text)
    a = CONFIG["assembly"]
    paths = [a.get("font_file_ethiopic")] + ETHIOPIC_FONTS if ethiopic else [a.get("font_file")] + FONTS
    for path in paths:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def text_png(lines: list[str], path, size: int, max_w: int, outline: bool = True) -> tuple[int, int]:
    """Centred white text on a transparent PNG, shrunk until the widest line fits max_w. Returns its size."""
    from PIL import Image, ImageDraw

    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    while True:
        fonts, stroke, pad = [_font(size, line) for line in lines], (max(2, size // 14) if outline else 0), size // 3
        widths = [measure.textlength(line, font=f) + 2 * stroke for line, f in zip(lines, fonts)]
        if max(widths, default=0) + 2 * pad <= max_w or size <= 14:
            break
        size -= 2
    step = round(size * 1.3)
    w, h = int(min(max_w, max(widths, default=0) + 2 * pad)), step * len(lines) + 2 * pad
    img = Image.new("RGBA", (max(w, 2), max(h, 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, (line, lw, f) in enumerate(zip(lines, widths, fonts)):
        draw.text(((w - lw) / 2 + stroke, pad + i * step), line, font=f, fill="white",
                  stroke_width=stroke, stroke_fill="black")
    img.save(path)
    return img.size


def text_overlays(cue_list, end_lines, end_start, end_dur, w, h, work, name) -> tuple[list[str], str]:
    """One PNG per subtitle cue plus one for the end card, each overlaid only during its time window.
    Returns the extra ffmpeg inputs (they become inputs 2, 3, ...) and a filter graph from [0:v] to [vout]."""
    vertical = h > w
    size = round(h * (0.024 if vertical else 0.045))
    bottom = round(h * (0.20 if vertical else 0.06))       # 9:16: stay above the caption/UI zone of Reels/TikTok/Shorts
    left, right = (round(w * 0.06), round(w * 0.10)) if vertical else (round(w * 0.1), round(w * 0.1))  # right: buttons
    end_text = [x for line in end_lines for x in wrap(line, 28 if vertical else 56) + [""]][:-1]
    items = [(c["start"], c["end"], c["lines"], True) for c in cue_list] + \
            [(end_start + 0.2, end_start + end_dur, end_text, False)]
    args, graph, last = [], [], "0:v"
    for i, (t0, t1, lines, is_sub) in enumerate(items):
        png = work / f"{name}_text{i:02d}.png"
        box = w - left - right if is_sub else w - 2 * left
        tw, th = text_png(lines, png, size if is_sub else round(size * 0.9), box, outline=is_sub)
        x, y = (left + (box - tw) // 2, h - bottom - th) if is_sub else ((w - tw) // 2, (h - th) // 2)
        args += ["-i", png.name]
        graph.append(f"[{last}][{i + 2}:v]overlay=x={x}:y={y}:enable='between(t,{t0:.2f},{t1:.2f})'[t{i}]")
        last = f"t{i}"
    graph.append(f"[{last}]format=yuv420p[vout]")
    return args, ";".join(graph)


def write_srt(path, cue_list) -> None:
    def ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    blocks = [f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n" + "\n".join(c["lines"]) + "\n"
              for i, c in enumerate(cue_list, 1)]
    path.write_text("\n".join(blocks), encoding="utf-8")


# ---------------------------------------------------------------- audio
def build_mix(rows: list[dict], total: float, music, out_wav, work) -> dict:
    a = CONFIG["assembly"]
    bed = bytearray(int(total * SR) * 2)           # 16-bit mono narration bed for the whole film
    for r in rows:
        if not r["narr"]:
            continue
        src, norm = OUT / r["narr"], work / f"narr_{r['id']}.wav"
        try:
            gain = max(-15.0, min(15.0, a["narration_lufs"] - float(loudnorm_json(src)["input_i"])))
        except (ValueError, KeyError):
            gain = 0.0
        ffmpeg("-i", src, "-af", f"volume={gain:.2f}dB", "-ac", "1", "-ar", SR, "-c:a", "pcm_s16le", norm)
        with wave.open(str(norm)) as w:
            pcm = w.readframes(w.getnframes())
        start = int((r["start"] + a["lead_in_s"]) * SR) * 2
        pcm = pcm[: max(0, len(bed) - start)]
        bed[start:start + len(pcm)] = pcm
    bed_path = work / "narration_bed.wav"
    with wave.open(str(bed_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(bed))

    d, fmt = a["duck"], f"aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo"
    graph = (f"[0:a]{fmt},atrim=0:{total},apad=whole_dur={total},afade=t=in:d=1.5,"
             f"afade=t=out:st={max(0.0, total - 3):.2f}:d=3,volume={a['music_gain_db']}dB[m];"
             f"[1:a]{fmt},asplit=2[sc][vo];"
             f"[m][sc]sidechaincompress=threshold={d['threshold']}:ratio={d['ratio']}:"
             f"attack={d['attack_ms']}:release={d['release_ms']}[duck];"
             f"[duck][vo]amix=inputs=2:duration=first:normalize=0[mix]")
    raw = work / "mix_raw.wav"
    ffmpeg("-i", music, "-i", bed_path, "-filter_complex", graph, "-map", "[mix]", "-c:a", "pcm_f32le", raw)

    L, m = a["loudness"], loudnorm_json(raw)             # pass 1: measure
    # Aim 0.5 dB under the true-peak spec: AAC encoding adds peaks after this step (a -1 dBTP mix measured
    # -0.8 dBTP in the encoded film on 2026-11-25), and make check measures the encoded film.
    tp = L["TP"] - 0.5
    second = (f"loudnorm=I={L['I']}:TP={tp}:LRA={L['LRA']}:measured_I={m['input_i']}:"
              f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true:print_format=json")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-y", "-i", str(raw), "-af", second,
                        "-ar", str(SR), "-c:a", "pcm_s16le", str(out_wav)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"loudnorm pass 2 failed: {r.stderr[-1500:]}")
    p2 = json.loads(r.stderr[r.stderr.rindex("{"): r.stderr.rindex("}") + 1])   # pass 2: applied
    return {"pass1": m, "pass2": p2}


# ---------------------------------------------------------------- video
def segment(clip, out, dur: float, w: int, h: int, fit: str, fade_in: bool, fade_out: bool) -> None:
    """Fit one clip to exactly `dur` seconds: slow it down (up to max_stretch), then hold the last frame."""
    a = CONFIG["assembly"]
    fps, clen = a["fps"], duration(clip)
    k = 1.0 if clen >= dur else min(dur / clen, a["max_stretch"])
    hold = max(0.0, dur - clen * k)
    chain = f"setpts={k:.4f}*PTS,fps={fps}"
    if hold > 0.01:
        chain += f",tpad=stop_mode=clone:stop_duration={hold + 0.1:.3f}"
    chain += f",trim=duration={dur:.3f},setpts=PTS-STARTPTS"
    if fit == "cover":
        graph = f"[0:v]{chain},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}[base]"
    else:   # blurpad: the vertical shot centred on a blurred, darkened copy of itself (for 16:9)
        graph = (f"[0:v]{chain},split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                 f"gblur=sigma={max(8, w // 48)},eq=brightness=-0.12[bg];[b]scale=-2:{h}:flags=lanczos[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
    tail = (["fade=t=in:st=0:d=0.5"] if fade_in else []) + \
           ([f"fade=t=out:st={max(0.0, dur - 0.4):.3f}:d=0.4"] if fade_out else []) + ["setsar=1", "format=yuv420p"]
    graph += f";[base]{','.join(tail)}[v]"
    ffmpeg("-i", clip, "-filter_complex", graph, "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "16", "-r", fps, out)


def end_segment(out, dur: float, w: int, h: int) -> None:
    fps = CONFIG["assembly"]["fps"]
    ffmpeg("-f", "lavfi", "-i", f"color=c=0x0b0b0b:s={w}x{h}:r={fps}:d={dur}", "-vf", "format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out)


def main() -> None:
    sb = load_storyboard()
    require(sb, "assemble")
    a = CONFIG["assembly"]
    rows, t = timeline(sb)
    end_dur = sb["end_card"].get("duration_s", a["end_card_s"])
    total = round(t + end_dur, 3)
    clips = {s["id"]: OUT / "shots" / f"{s['id']}.mp4" for s in sb["shots"]}
    missing = [k for k, p in clips.items() if not p.exists()]
    if missing:
        fail(f"no clip for {missing}. Run `make shots` first.")
    music = OUT / "music" / "score.wav"
    if not music.exists():
        fail("no score yet. Run `make music` first.")
    exports = [{**e, "width": scaled(e["width"], e["height"])[0], "height": scaled(e["width"], e["height"])[1]}
               for e in a["exports"]]
    cue_list = cues(rows)
    inputs = {"v": STAGE_VERSION, "clips": {k: file_sha(p) for k, p in clips.items()},
              "narration": {r["id"]: file_sha(OUT / r["narr"]) for r in rows if r["narr"]},
              "music": file_sha(music), "timeline": rows, "end_card": sb["end_card"], "title": sb["title"],
              "config": a, "exports": exports}
    film = OUT / "film"
    primary = film / f"{exports[0]['name']}.mp4"
    outs = [film / f"{e['name']}.mp4" for e in exports] + [film / "subtitles_en.srt", film / "timeline.json"]
    meta = read_meta(primary)
    if meta and meta["input_hash"] == sha(inputs) and all(o.exists() for o in outs) and not forced("assemble"):
        say("assemble", f"film: cached ({sha(inputs)})")
        return
    why = "forced" if forced("assemble") else (
        "changed: " + ", ".join(changed_keys(meta["inputs"], inputs)[:8]) if meta else "new")
    say("assemble", f"rendering film ({why})")
    work = WORK / "assemble"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    film.mkdir(parents=True, exist_ok=True)

    loud = build_mix(rows, total, music, work / "mix.wav", work)
    for e in exports:
        w, h, name = e["width"], e["height"], e["name"]
        segs = []
        for i, r in enumerate(rows):
            seg = work / f"{name}_{r['id']}.mp4"
            segment(clips[r["id"]], seg, r["dur"], w, h, e["fit"], fade_in=i == 0, fade_out=i == len(rows) - 1)
            segs.append(seg)
        segs.append(work / f"{name}_end.mp4")
        end_segment(segs[-1], end_dur, w, h)
        (work / f"{name}.txt").write_text("".join(f"file '{p.name}'\n" for p in segs))
        text_args, graph = text_overlays(cue_list, sb["end_card"]["lines"], t, end_dur, w, h, work, name)
        tmp = film / f"{name}.tmp.mp4"
        ffmpeg("-f", "concat", "-safe", "0", "-i", f"{name}.txt", "-i", "mix.wav", *text_args, "-filter_complex", graph,
               "-map", "[vout]", "-map", "1:a", "-c:v", "libx264", "-preset", x264_preset(), "-crf", a["crf"],
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", a["fps"], "-c:a", "aac", "-b:a", "192k",
               "-ar", SR, "-t", f"{total:.3f}", "-movflags", "+faststart", "-metadata", f"title={sb['title']}",
               "-metadata", "comment=Made with AI. See the end card and README for the models used.",
               tmp, cwd=work)
        os.replace(tmp, film / f"{name}.mp4")
        say("assemble", f"wrote {name}.mp4 ({w}x{h}, {total:.1f}s)")
    write_srt(film / "subtitles_en.srt", cue_list)
    (film / "timeline.json").write_text(json.dumps(
        {"total_s": total, "end_card_s": end_dur, "shots": rows, "cues": cue_list, "loudness": loud},
        indent=2, ensure_ascii=False) + "\n")
    write_meta(primary, inputs)


if __name__ == "__main__":
    main()
