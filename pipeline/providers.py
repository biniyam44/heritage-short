"""Model providers. Each real function makes ONE HTTP request and returns the payload;
retries and runs.jsonl logging live in common.call_model. Mock functions make deterministic
placeholder media with FFmpeg so MOCK=1 runs offline with no keys.

Request formats were checked against the official docs on 2026-11-24:
  Gemini Interactions API  POST /v1beta/interactions      (text + speech)
  Cloudflare Workers AI    POST /accounts/{id}/ai/run/{model}  (FLUX.2 = multipart form, FLUX.1 = JSON)
"""
from __future__ import annotations

import base64
import io
import math
import os
import random
import textwrap
import wave
from pathlib import Path

from .common import CONFIG, FatalError, TransientError, ffmpeg, privacy_check, sha

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"   # v1beta is required for speech
CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
DAILY_QUOTA_MARKERS = ("quota_exceeded", "3036", "daily free allocation")       # a 429 that won't clear by retrying


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise FatalError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


def post(url: str, headers: dict, *, json_body=None, files=None, timeout: int = 300) -> dict:
    """POST and sort failures into retryable (TransientError) or not (FatalError)."""
    import requests

    try:
        r = requests.post(url, headers=headers, json=json_body, files=files, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout) as e:
        raise TransientError(f"network error: {e}") from e
    body = r.text[:600]
    if r.status_code in (408, 429) or r.status_code >= 500:
        ra = r.headers.get("Retry-After", "")
        wait = float(ra) if ra.replace(".", "", 1).isdigit() else None
        # a daily quota (or any wait longer than max_wait_s) won't clear by retrying now: stop with a clear message
        if r.status_code == 429 and (any(m in body for m in DAILY_QUOTA_MARKERS) or "per day" in body
                                     or (wait or 0) > CONFIG["retries"]["max_wait_s"]):
            when = f" Retry in {wait / 3600:.1f} h." if wait else ""
            raise FatalError(f"daily quota used up (HTTP 429).{when} Cloudflare resets 00:00 UTC (03:00 EAT); "
                             f"Gemini at midnight Pacific (11:00 EAT). {body}")
        err = TransientError(f"HTTP {r.status_code}: {body}")
        err.retry_after = wait
        raise err
    if r.status_code >= 400:
        raise FatalError(f"HTTP {r.status_code}: {body}")
    try:
        return r.json()
    except ValueError as e:
        raise TransientError(f"non-JSON response: {body}") from e


# ---------------------------------------------------------------- Gemini (Interactions API)
def _gemini_headers(revision: str = "") -> dict:
    headers = {"x-goog-api-key": env("GEMINI_API_KEY"), "Content-Type": "application/json"}
    if revision:
        headers["Api-Revision"] = revision
    return headers


def _model_output(resp: dict, kind: str) -> list[dict]:
    items = [c for step in resp.get("steps", []) if step.get("type") == "model_output"
             for c in step.get("content", []) if c.get("type") == kind]
    if not items:
        raise TransientError(f"no {kind} in response (status={resp.get('status')}, errors={resp.get('errors')})")
    return items


def gemini_text(prompt: str, *, system: str, model: str) -> tuple[str, dict]:
    privacy_check(system + "\n" + prompt, "Gemini")
    tc = CONFIG["text"]
    body = {"model": model, "input": prompt, "system_instruction": system, "store": CONFIG["gemini"]["store"]}
    if tc.get("thinking_level"):
        body["generation_config"] = {"thinking_level": tc["thinking_level"]}
    resp = post(GEMINI_URL, _gemini_headers(tc.get("api_revision", "")), json_body=body)
    return "".join(c.get("text", "") for c in _model_output(resp, "text")), resp.get("usage", {})


def gemini_tts(text: str, *, voice: str, style: str, model: str) -> tuple[bytes, dict]:
    """The text is read verbatim, so delivery hints go in speech_metadata.style, not in the text."""
    privacy_check(text, "Gemini TTS")
    part = {"type": "text", "text": text}
    if style:
        part["annotations"] = [{"type": "speech_metadata", "style": style}]
    body = {"model": model, "input": [{"type": "user_input", "content": [part]}],
            "response_format": {"type": "audio", "mime_type": "audio/wav"},
            "generation_config": {"speech_config": [{"voice": voice}]},
            "store": CONFIG["gemini"]["store"]}
    resp = post(GEMINI_URL, _gemini_headers(), json_body=body)
    audio = base64.b64decode(_model_output(resp, "audio")[-1]["data"])
    if audio[:4] != b"RIFF":            # raw 24 kHz 16-bit mono PCM: add a WAV header
        audio = pcm_to_wav(audio, 24000)
    return audio, resp.get("usage", {})


def gemini_cost(model: str, usage: dict) -> dict:
    """List-price estimate from usage. Thinking tokens bill as output; audio has its own rate."""
    p = CONFIG["prices"].get(model, {})
    by_modality = {m.get("modality"): m.get("tokens", 0) for m in usage.get("output_tokens_by_modality", [])}
    audio = by_modality.get("audio", 0)
    text_out = max(0, usage.get("total_output_tokens", 0) - audio) + usage.get("total_thought_tokens", 0)
    tin = usage.get("total_input_tokens", 0)
    usd = (tin * p.get("input", 0) + text_out * p.get("output", 0) + audio * p.get("output_audio", 0)) / 1e6
    return {"input_tokens": tin, "output_tokens": text_out, "audio_tokens": audio, "usd_list": round(usd, 6)}


def pcm_to_wav(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------- Cloudflare Workers AI (FLUX)
def cloudflare_image(prompt: str, *, model: str, width: int, height: int, seed: int, refs=()) -> bytes:
    privacy_check(prompt, "Cloudflare")
    url = CF_URL.format(account=env("CLOUDFLARE_ACCOUNT_ID"), model=model)
    headers = {"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"}
    if "flux-2" in model:   # FLUX.2 takes multipart form data, even for a text-only prompt
        form = {"prompt": (None, prompt), "width": (None, str(width)),
                "height": (None, str(height)), "seed": (None, str(seed))}
        for i, ref in enumerate(list(refs)[:4]):   # up to 4 reference images, each under 512x512
            form[f"input_image_{i}"] = (f"ref{i}.png", Path(ref).read_bytes(), "image/png")
        data = post(url, headers, files=form)
    else:                   # FLUX.1 schnell: JSON with prompt + steps only (square output, no seed)
        data = post(url, headers, json_body={"prompt": prompt, "steps": CONFIG["image"]["steps"]})
    b64 = (data.get("result") or {}).get("image") or data.get("image")
    if not b64:
        raise TransientError(f"no image in response: {str(data)[:300]}")
    return base64.b64decode(b64)


def cloudflare_cost(model: str, width: int, height: int, n_refs: int) -> dict:
    """Neurons from the published price table (estimate: tiles rounded up)."""
    p = CONFIG["prices"].get(model, {})
    if "neurons_first_mp" in p:          # klein 9B is priced per megapixel (inputs rounded up to 1 MP each)
        mp = math.ceil(width * height / 1024 ** 2)
        neurons = p["neurons_first_mp"] + (mp - 1) * p["neurons_per_extra_mp"] + n_refs * p["neurons_per_input_mp"]
        usd = neurons * CONFIG["prices"]["cloudflare_usd_per_1k_neurons"] / 1000
        return {"neurons_est": round(neurons, 2), "usd_list": round(usd, 6)}
    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    neurons = (tiles * p.get("neurons_per_output_tile", 0) + n_refs * p.get("neurons_per_input_tile", 0)
               + CONFIG["image"]["steps"] * p.get("neurons_per_step", 0))
    usd = neurons * CONFIG["prices"]["cloudflare_usd_per_1k_neurons"] / 1000
    return {"neurons_est": round(neurons, 2), "usd_list": round(usd, 6)}


def image_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    raise TransientError("response is not a PNG/JPEG/WebP image")


# ---------------------------------------------------------------- mocks (offline)
def maybe_fail() -> None:
    """MOCK_FAIL_RATE=0.3 makes mock calls fail at random, to watch the retry logic work."""
    rate = float(os.environ.get("MOCK_FAIL_RATE") or 0)
    if rate and random.random() < rate:
        raise TransientError("mock: injected failure (MOCK_FAIL_RATE)")


def mock_image(label: str, width: int, height: int, out: Path) -> None:
    """A colour card (colour from the prompt hash) with the label written on it."""
    from PIL import Image, ImageDraw, ImageFont

    maybe_fail()
    img = Image.new("RGB", (width, height), "#" + sha(label)[:6])
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=max(12, height // 28))
    text = "MOCK\n" + textwrap.fill(label[:140], 26)
    x0, y0, x1, y1 = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    draw.multiline_text(((width - (x1 - x0)) / 2, (height - (y1 - y0)) / 2), text, font=font, fill="white",
                        align="center", stroke_width=2, stroke_fill="black")
    img.save(out)


def mock_tts(text: str, out: Path) -> None:
    """Speech-like noise bursts whose length follows the word count."""
    maybe_fail()
    d = round(max(1.2, len(text.split()) / CONFIG["mock"]["words_per_s"]), 2)
    ffmpeg("-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:r=24000:a=0.5:seed={int(sha(text)[:6], 16)}",
           "-af", f"bandpass=f=650:width_type=h:width=900,tremolo=f=4.5:d=0.9,"
                  f"afade=t=in:d=0.05,afade=t=out:st={d - 0.15:.2f}:d=0.15",
           "-ac", "1", "-c:a", "pcm_s16le", out)


def mock_music(seconds: float, out: Path) -> None:
    """A soft sustained chord: placeholder score for mock mode and the radio cut."""
    notes = (130.81, 196.0, 261.63, 329.63)
    inputs = [x for f in notes for x in ("-f", "lavfi", "-i", f"sine=f={f}:r=48000:d={seconds:.2f}")]
    graph = "".join(f"[{i}]" for i in range(len(notes))) + (
        f"amix=inputs={len(notes)},tremolo=f=0.25:d=0.6,lowpass=f=900,volume=0.6,aformat=channel_layouts=stereo")
    ffmpeg(*inputs, "-filter_complex", graph, "-c:a", "pcm_s16le", out)
