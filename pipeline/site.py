"""make site: index.html, one static page that frames the film as a screening room (ready for GitHub Pages).

Everything on it comes from files the pipeline already writes, so it never drifts from the film:
storyboard.json (lines, purposes, prompts), outputs/film/timeline.json (when each shot starts),
outputs/keyframes/ (shrunk to thumbnails in outputs/site/), runs.jsonl (telemetry) and the docs.
No model calls, no keys. Publish: GitHub -> Settings -> Pages -> Deploy from a branch: main, / (root).
"""
from __future__ import annotations

import html
import json
import subprocess
from collections import defaultdict

from PIL import Image

from .common import CONFIG, OUT, ROOT, RUNS, load_storyboard, say
from .costs import gpu_rate

DOCS = [("README.md", "one command, what it does, what it costs"),
        ("DESIGN.md", "audience, intent, the two user tests, why each shot exists"),
        ("ARCHITECTURE.md", "stages, contracts, caching, failure handling"),
        ("EXPERIMENTS.md", "hypothesis, change, result"),
        ("FAILURES.md", "what broke and what fixed it"),
        ("COSTS.md", "measured time, GPU minutes, list-price equivalent"),
        ("ETHICS.md", "consent, licences, labelling")]
CAMERA = {"static": "static camera", "push_in": "slow push-in", "pull_out": "slow pull-out"}


def esc(s) -> str:
    return html.escape(str(s))


def clock(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def repo_url() -> str | None:
    """Docs link to GitHub, which renders Markdown (Pages would serve it as plain text)."""
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    url = r.stdout.strip().removesuffix(".git")
    return url if r.returncode == 0 and url.startswith("https://github.com/") else None


def telemetry() -> tuple[list[dict], dict]:
    """runs.jsonl grouped by stage and model, the same sums as COSTS.md."""
    lines = [json.loads(l) for l in RUNS.read_text().splitlines() if l.strip()] if RUNS.exists() else []
    lines = [r for r in lines if not r.get("mock")]
    groups = defaultdict(lambda: {"ok": 0, "err": 0, "latency": 0.0, "gpu": 0.0, "usd": 0.0})
    for r in lines:
        g = groups[(str(r.get("stage")), str(r.get("model")))]
        g["ok" if r.get("status") == "ok" else "err"] += 1
        g["latency"] += r.get("latency_s") or 0
        g["gpu"] += r.get("gpu_s") or 0
        cost = r.get("cost") if isinstance(r.get("cost"), dict) else {}
        g["usd"] += (cost.get("usd_list") or 0) + (r.get("gpu_s") or 0) / 3600 * gpu_rate(r.get("gpu"))
    table = [{"stage": k[0], "model": k[1], **v} for k, v in sorted(groups.items())]
    total = {k: sum(t[k] for t in table) for k in ("ok", "err", "latency", "gpu", "usd")}
    return table, total


def thumbnail(sid: str) -> str | None:
    src, dst = OUT / "keyframes" / f"{sid}.png", OUT / "site" / f"{sid}.jpg"
    if not src.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    im.thumbnail((360, 640))
    im.save(dst, quality=82)
    return dst.relative_to(ROOT).as_posix()


def how(s: dict) -> str:
    m = s["motion"]
    kind = "Wan 2.2 clip" if m["backend"] == "wan" else "Ken Burns on the keyframe"
    return f"{kind}, {CAMERA.get(m.get('camera'), m.get('camera', ''))}"


def main() -> None:
    sb = load_storyboard()
    tl = json.loads((OUT / "film" / "timeline.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in sb["shots"]}
    n = len(tl["shots"])
    shots = []
    for i, row in enumerate(tl["shots"], 1):
        s = by_id[row["id"]]
        shots.append({"id": s["id"], "start": row["start"], "end": row["start"] + row["dur"], "label": f"Shot {i:02d} of {n:02d}",
                      "clock": f"{clock(row['start'])}–{clock(row['start'] + row['dur'])}", "am": s["narration"],
                      "en": s["subtitle_en"], "why": s["purpose"], "how": how(s), "thumb": thumbnail(s["id"]),
                      "narr": f"outputs/{row['narr']}", "prompt": s["keyframe_prompt"],
                      "motion_prompt": s["motion"].get("prompt", ""), "seed": s["seed"]})
    end = sb["end_card"]["lines"]
    shots.append({"id": "end", "start": tl["total_s"] - tl["end_card_s"], "end": tl["total_s"] + 1, "label": "End card",
                  "clock": f"{clock(tl['total_s'] - tl['end_card_s'])}–{clock(tl['total_s'])}", "am": end[0],
                  "en": " · ".join(end[1:]), "why": "", "how": "drawn in code", "thumb": None})
    table, total = telemetry()
    loud = tl.get("loudness") or {}
    lufs, etp = (loud.get("pass2") or {}).get("output_i", "?"), loud.get("encoded_tp", "?")
    repo = repo_url()
    ic, mc = CONFIG["image"], CONFIG["music"]

    def model(m: str) -> str:
        return esc(m.rsplit("/", 1)[-1])

    strip = "".join(
        f'<button title="{esc(s["label"])}">' + (f'<img src="{s["thumb"]}" alt="">' if s["thumb"] else
                                                 '<div class="tile end">Made with AI</div>') +
        f'{esc(s["clock"].split("–")[0])}</button>' for s in shots)
    cards = "".join(
        f'<article class="card"><img src="{s["thumb"]}" alt="Keyframe of {s["id"]}" loading="lazy"><div class="b">'
        f'<div class="h"><span>{s["id"]} · {s["clock"]}</span><span>{esc(s["how"])}</span></div>'
        f'<p class="am" lang="am">{esc(s["am"])}</p><p class="sub">{esc(s["en"])}</p><p class="why">{esc(s["why"])}</p>'
        f'<audio controls preload="none" src="{s["narr"]}"></audio>'
        f'<details><summary>Prompts and seed</summary><p><b>Keyframe:</b> {esc(s["prompt"])}</p>'
        + (f'<p><b>Motion:</b> {esc(s["motion_prompt"])}</p>' if s["motion_prompt"] else "") +
        f'<p><b>Seed:</b> {s["seed"]}</p></details></div></article>' for s in shots if s["id"] != "end")
    rows = "".join(
        f'<tr><td>{esc(t["stage"])}</td><td>{model(t["model"])}</td><td class="n">{t["ok"]}/{t["err"]}</td>'
        f'<td class="n">{t["latency"] / 60:.1f}</td><td class="n">{t["gpu"] / 60:.1f}</td><td class="n">${t["usd"]:.3f}</td></tr>'
        for t in table)
    docs = "".join(f'<li><a href="{(repo + "/blob/main/" + f) if repo else f}">{f}</a> {esc(d)}</li>' for f, d in DOCS)
    data = json.dumps({"shots": [{k: s[k] for k in ("start", "end", "label", "clock", "am", "en", "why", "how")}
                                 for s in shots]}, ensure_ascii=False).replace("</", "<\\/")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(sb["title"])}: Screening Room</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><h1 lang="am">{esc(end[0])}</h1><p class="en">{esc(end[1])}</p><p>{esc(sb["logline"])}</p>
<div class="chips"><span>{tl["total_s"]:.0f} s</span><span>{n} shots</span><span>Amharic narration</span><span>English subtitles</span>
<span>Characters are fictional</span><span>Made with AI</span></div></header>
<section class="room"><div class="player"><div class="tabs">
<button class="on" data-src="outputs/film/heritage_9x16.mp4">9:16 master</button>
<button data-src="outputs/film/heritage_16x9.mp4">16:9</button>
<button data-src="outputs/radio/radio_cut.mp4">Radio cut</button></div>
<video id="film" controls playsinline preload="metadata" src="outputs/film/heritage_9x16.mp4"></video>
<p class="dl">Download: <a href="outputs/film/heritage_9x16.mp4">9:16 MP4</a> · <a href="outputs/film/heritage_16x9.mp4">16:9 MP4</a>
· <a href="outputs/film/subtitles_en.srt">subtitles (.srt)</a></p></div>
<aside class="now"><div class="k" id="now-k"></div><p class="am" lang="am" id="now-am"></p><p class="sub" id="now-en"></p>
<p class="why" id="now-why"></p><p class="how" id="now-how"></p></aside></section>
<nav class="strip">{strip}</nav>
<h2>Storyboard</h2><p class="lead">Each shot as <code>storyboard.json</code> describes it. Change one prompt or line there and
<code>make film</code> regenerates only that shot.</p><div class="cards">{cards}</div>
<h2>How it was made</h2><div class="pipe"><span>storyboard.json, schema-checked</span>→
<span>keyframes: {model(ic["model"])}, portraits {model(ic["portrait_model"])}</span>→
<span>motion: {model(CONFIG["video"]["model"])} on a Kaggle T4, or Ken Burns</span>→
<span>score: {model(mc["model"])}</span>→<span>narration: {model(CONFIG["tts"]["model"])}</span>→
<span>assembly: FFmpeg</span></div>
<div class="stats"><div><b>{total["ok"] + total["err"]}</b><span>logged model calls ({total["err"]} failed)</span></div>
<div><b>{total["gpu"] / 60:.0f} min</b><span>GPU time on Kaggle</span></div>
<div><b>${total["usd"]:.2f}</b><span>list-price equivalent</span></div><div><b>$0</b><span>actual spend (free tiers)</span></div>
<div><b>{lufs} LUFS</b><span>true peak {etp} dBTP after AAC</span></div></div>
<table><thead><tr><th>Stage</th><th>Model</th><th class="n">Calls ok/failed</th><th class="n">Time (min)</th>
<th class="n">GPU (min)</th><th class="n">List price</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Process</h2><ul class="docs">{docs}</ul>
<footer>Made with AI. Characters are fictional. Reference photos: Wikimedia Commons, CC BY-SA
(<a href="{(repo + "/blob/main/") if repo else ""}references/photos/CREDITS.md">credits</a>). This page is generated by
<code>make site</code> from the repository.</footer></div>
<script type="application/json" id="data">{data}</script><script>{JS}</script></body></html>
"""
    (ROOT / "index.html").write_text(page, encoding="utf-8")
    (ROOT / ".nojekyll").touch()          # serve files as they are (no Jekyll build on GitHub Pages)
    say("site", f"wrote {ROOT / 'index.html'} ({len(shots) - 1} shots, {len(table)} telemetry rows)")


CSS = """:root{--bg:#14110f;--panel:#1d1915;--line:#332c25;--text:#efe7dc;--muted:#a89a88;--accent:#e0a458}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Ethiopic",Kefa,sans-serif}
a{color:var(--accent)}code{background:var(--panel);padding:1px 5px;border-radius:4px;font-size:.9em}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}h1{margin:0;font-size:clamp(30px,5vw,46px)}
.en{color:var(--muted);font-size:20px;margin:0 0 8px}.chips span{display:inline-block;border:1px solid var(--line);
border-radius:99px;padding:2px 10px;margin:4px 6px 0 0;font-size:13px;color:var(--muted)}
.room{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:20px;margin-top:24px}
@media (max-width:860px){.room{grid-template-columns:1fr}}
.player{background:#000;border:1px solid var(--line);border-radius:12px;padding:10px;text-align:center}
.tabs{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;justify-content:center}
.tabs button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 12px;
cursor:pointer;font:inherit;font-size:14px}.tabs button.on{border-color:var(--accent);color:var(--accent)}
video{width:100%;max-height:76vh;background:#000;border-radius:6px}.dl{font-size:13px;color:var(--muted);margin:8px 0 0}
.now{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}
.k{color:var(--accent);font-size:13px;letter-spacing:.08em;text-transform:uppercase}
.am{font-size:21px;line-height:1.6;margin:10px 0 6px}.why{color:var(--muted);font-style:italic}.how{color:var(--muted);font-size:14px}
.strip{display:flex;gap:8px;overflow-x:auto;margin:16px 0 8px;padding-bottom:6px}
.strip button{flex:0 0 auto;width:78px;background:none;border:2px solid transparent;border-radius:8px;padding:0 0 4px;
cursor:pointer;color:var(--muted);font:12px system-ui}.strip button.on{border-color:var(--accent);color:var(--text)}
.strip img,.tile{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:6px;display:block;margin-bottom:3px}
.tile{display:flex;align-items:center;justify-content:center;background:#000;font-size:11px;padding:6px}
h2{margin:46px 0 8px;font-size:23px}.lead{color:var(--muted);margin:0 0 14px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card img{width:100%;aspect-ratio:3/4;object-fit:cover;display:block}.card .b{padding:12px 14px}
.card .h{display:flex;justify-content:space-between;gap:8px;color:var(--muted);font-size:12px}
.card .am{font-size:18px}.card p{margin:6px 0}.card audio{width:100%;height:32px;margin-top:6px}
details{margin-top:8px;color:var(--muted);font-size:13px}summary{cursor:pointer}
.pipe{display:flex;flex-wrap:wrap;gap:8px;align-items:center;color:var(--muted);font-size:14px;margin-bottom:16px}
.pipe span{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px;color:var(--text)}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:14px}.stats div{background:var(--panel);
border:1px solid var(--line);border-radius:10px;padding:10px 14px}.stats b{display:block;font-size:20px}
.stats span{color:var(--muted);font-size:13px}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line)}.n{text-align:right;font-variant-numeric:tabular-nums}
.docs li{margin:4px 0}footer{margin-top:50px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:16px}"""

JS = """const D=JSON.parse(document.getElementById('data').textContent),v=document.getElementById('film');
const strip=[...document.querySelectorAll('.strip button')],tabs=[...document.querySelectorAll('.tabs button')];
const el=id=>document.getElementById(id);let cur=-1;
function show(i){const s=D.shots[i];el('now-k').textContent=s.label+' · '+s.clock;el('now-am').textContent=s.am;
el('now-en').textContent=s.en;el('now-why').textContent=s.why;el('now-how').textContent=s.how;
strip.forEach((b,j)=>b.classList.toggle('on',j===i));}
v.addEventListener('timeupdate',()=>{let i=D.shots.findIndex(s=>v.currentTime>=s.start&&v.currentTime<s.end);
if(i<0)i=D.shots.length-1;if(i!==cur){cur=i;show(i);}});
strip.forEach((b,i)=>b.onclick=()=>{v.currentTime=D.shots[i].start+0.05;v.play();});
tabs.forEach(b=>b.onclick=()=>{const t=v.currentTime,play=!v.paused;tabs.forEach(x=>x.classList.toggle('on',x===b));
v.src=b.dataset.src;v.addEventListener('loadedmetadata',()=>{v.currentTime=Math.min(t,v.duration-0.2);if(play)v.play();},{once:true});});
show(0);"""


if __name__ == "__main__":
    main()
