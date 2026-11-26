"""Stage 2: character portraits + style frame, then one keyframe per shot (Cloudflare Workers AI, FLUX.2).

Consistency comes from four things: every prompt repeats style.visual and the characters' descriptions;
FLUX.2 also receives reference images (input_image_0..3): the chosen portrait of each character in the shot,
plus the real photos listed in the shot's `references` (objects and places, no faces); each shot has a fixed
seed; and the portraits come from a stronger model ([image].portrait_model) than the keyframes. A keyframe's
cache key includes its reference images' hashes, so changing a character's description regenerates exactly
the shots that character appears in.

Picking faces: `make portraits N=3` renders N portrait candidates per character (seeds seed, seed+1, ...)
into outputs/refsheet/. Put the chosen seed into characters[].seed and run `make keyframes`: that portrait
is already cached, so only the keyframes are generated.

Picking a keyframe: `ONLY=s07 make keyframe-candidates N=3` renders N versions of a shot (seeds seed, seed+1,
...) into outputs/keyframes/candidates/. Put the chosen seed into the shot's seed and run `make keyframes`:
the picked file is copied, not generated again (same inputs, so no second model call).
"""
from __future__ import annotations

import argparse
import shutil

from .common import (CONFIG, MOCK, OUT, ROOT, WORK, build, call_model, ffmpeg, file_sha, fit_png,
                     load_storyboard, read_meta, say, scaled, selected, sha)
from .consent import require
from .providers import cloudflare_cost, cloudflare_image, image_ext, mock_image

STAGE_VERSION = 1


def shrink(ref):
    """FLUX.2 wants each reference image under 512x512."""
    out = WORK / "refs" / f"{file_sha(ref)}.png"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg("-i", ref, "-vf", "scale=496:496:force_original_aspect_ratio=decrease", "-frames:v", "1", out)
    return out


def generate(stage, item, out, prompt, seed, w, h, refs=(), label="", model=None, reuse=None):
    model = model or CONFIG["image"]["model"]
    inputs = {"v": STAGE_VERSION, "model": model, "prompt": prompt, "seed": seed, "size": [w, h],
              "refs": [file_sha(r) for r in refs]}

    def make(tmp):
        if reuse is not None and reuse.exists() and (read_meta(reuse) or {}).get("input_hash") == sha(inputs):
            shutil.copy(reuse, tmp)          # the picked candidate has exactly these inputs: no second call
            say(stage, f"{item}: using the picked candidate {reuse.name} (no model call)")
            return
        if MOCK:
            call_model(stage=stage, item=item, provider="mock", model="mock-image",
                       params={"size": [w, h], "refs": len(refs)}, seed=seed,
                       fn=lambda: mock_image(f"{item}: {label or prompt}", w, h, tmp))
            return
        small = [shrink(r) for r in refs]
        data = call_model(stage=stage, item=item, provider="cloudflare", model=model,
                          params={"width": w, "height": h, "refs": len(small)}, seed=seed,
                          fn=lambda: cloudflare_image(prompt, model=model, width=w, height=h, seed=seed, refs=small),
                          cost=lambda _: cloudflare_cost(model, w, h, len(small)))
        raw = tmp.with_name(f"{tmp.stem}_raw{image_ext(data)}")
        raw.write_bytes(data)
        try:
            fit_png(raw, tmp, w, h)          # schnell returns a square JPEG; normalise every keyframe to w x h PNG
        finally:
            raw.unlink(missing_ok=True)

    build(stage, out, inputs, make)
    return out


def portrait(c, seed, model, w, h):
    """A head-and-shoulders portrait: the identity reference for every shot the character appears in.
    Plain background and no kitchen, because a full-body sheet made FLUX copy its pose into every shot (2026-11-24).
    The file name carries model and seed, so candidates sit side by side and the chosen one stays cached."""
    out = OUT / "refsheet" / f"{c['id']}_{model.rsplit('/', 1)[-1]}_s{seed}.png"
    prompt = (f"Realistic documentary photograph, 35mm, natural skin texture. Head-and-shoulders portrait of "
              f"{c['description']}, looking at the camera, plain neutral background, soft even daylight.")
    return generate("refsheet", f"{c['id']}_s{seed}", out, prompt, seed, w, h, label=c["description"], model=model)


def main() -> None:
    ap = argparse.ArgumentParser(description="character portraits + keyframes")
    ap.add_argument("--candidates", type=int, default=0, help="only render N portrait candidates per character")
    ap.add_argument("--model", help="image model for the portraits (default: [image].portrait_model)")
    ap.add_argument("--shot-candidates", type=int, default=0, help="only render N versions of each selected shot")
    a = ap.parse_args()

    sb = load_storyboard()
    require(sb, "keyframes")
    ic, style = CONFIG["image"], sb["style"]
    w, h = scaled(ic["width"], ic["height"])
    rw, rh = scaled(ic["ref_width"], ic["ref_height"])
    use_refs = ic.get("use_references") and "flux-2" in ic["model"]
    pmodel = a.model or ic.get("portrait_model") or ic["model"]

    if a.candidates:
        for c in sb["characters"]:
            if not c.get("reference_photo"):
                for k in range(a.candidates):
                    portrait(c, c.get("seed", 7) + k, pmodel, rw, rh)
        say("keyframes", f"candidates in {OUT / 'refsheet'}: put the chosen seed into characters[].seed")
        return

    # 1) one portrait per character (or its consented real photo) + one style frame
    sheet = {}
    for c in sb["characters"]:
        if c.get("reference_photo"):        # a real photo (consent checked above) is used as-is
            out = OUT / "refsheet" / f"{c['id']}.png"
            src = ROOT / c["reference_photo"]
            build("refsheet", out, {"v": STAGE_VERSION, "photo": file_sha(src), "size": [rw, rh]},
                  lambda tmp: fit_png(src, tmp, rw, rh))
            sheet[c["id"]] = out
        else:
            sheet[c["id"]] = portrait(c, c.get("seed", 7), pmodel, rw, rh)
    style_ref = generate("refsheet", "style", OUT / "refsheet" / "style.png",
                         f"{style['visual']}. {style['reference_prompt']}", style.get("seed", 7), w, h,
                         label=style["reference_prompt"])

    # 2) keyframes
    for s in selected(sb["shots"]):
        out = OUT / "keyframes" / f"{s['id']}.png"
        if s.get("image"):                  # an archival photo instead of a generated frame
            src = ROOT / s["image"]
            build("keyframes", out, {"v": STAGE_VERSION, "image": file_sha(src), "size": [w, h]},
                  lambda tmp: fit_png(src, tmp, w, h))
            continue
        cast = [c for c in sb["characters"] if c["id"] in s.get("characters", [])]
        prompt = " ".join([f"{style['visual']}.", s["keyframe_prompt"]] + [f"{c['description']}." for c in cast])
        # Reference images steer layout as well as identity, so each one is named in the prompt and the text keeps
        # control of pose and framing. Tested 2026-11-24: the style frame plus full-body sheets in every shot gave
        # the same wide composition everywhere and dropped the second character.
        refs, notes = [], []
        if use_refs:
            for c in cast:
                refs.append(sheet[c["id"]])
                notes.append(f"image {len(refs)} shows the {c['id']}: keep this person's face, skin tone and clothes")
            for r in s.get("references", []):
                refs.append(ROOT / r["photo"])
                notes.append(f"image {len(refs)} is a real photo of {r['shows']}: make them look like the photo")
            refs, notes = refs[:4], notes[:4]
            if notes:
                prompt += (" Reference images: " + "; ".join(notes) +
                           ". Follow the description above for pose, framing and action.")
            else:   # no cast, no photos: the style frame carries the look. Unexplained, FLUX copied its whole
                refs = [style_ref]   # layout instead (2026-11-25: s02 came out as an empty kitchen, no hand)
                prompt += (" Reference image: image 1 is a style frame; take only its light, colours and materials, "
                           "not its layout. Follow the description above for framing and action.")
        cand = OUT / "keyframes" / "candidates"
        if a.shot_candidates:
            for seed in range(s["seed"], s["seed"] + a.shot_candidates):
                generate("keyframes", f"{s['id']}_s{seed}", cand / f"{s['id']}_s{seed}.png", prompt, seed, w, h, refs,
                         label=s["keyframe_prompt"])
            continue
        generate("keyframes", s["id"], out, prompt, s["seed"], w, h, refs, label=s["keyframe_prompt"],
                 reuse=cand / f"{s['id']}_s{s['seed']}.png")
    if a.shot_candidates:
        say("keyframes", f"candidates in {OUT / 'keyframes' / 'candidates'}: put the chosen seed into the shot's seed")
        return
    say("keyframes", f"done -> {OUT / 'keyframes'}")


if __name__ == "__main__":
    main()
