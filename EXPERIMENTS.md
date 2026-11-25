# Experiments

_Template: about 10 entries are expected. Only record what you actually ran; cite the `run_id` from
`runs.jsonl` or the sidecar `.json` as evidence. The candidates below fit this pipeline. Delete the ones you
don't run._

Format for each entry:

```
## E<n>: <short name>            date · run_id(s)
Hypothesis: <what I expected and why>
Change:     <config.toml / storyboard.json diff, or command>
Measure:    <metric: latency from runs.jsonl, GPU s/clip, LUFS from timeline.json, testers' ratings, …>
Result:     <numbers + what I saw/heard>
Decision:   <kept / reverted / next step>
```

## Candidate experiments

1. **FLUX.2 klein 4B vs FLUX.1 schnell:** character consistency across 4 keyframes (blind 3-person ranking), neurons per image.
2. **Reference images on/off** (`[image].use_references`): does the ref sheet keep the face, clothes and palette consistent?
3. **Wan steps 20 vs 30 (vs 50):** GPU seconds per clip (`gpu_s`) against visible quality.
4. **Wan 480p vs 576p:** cost against sharpness after upscaling to 1080×1920.
5. **Wan 81 vs 121 frames:** stretch and hold in assembly against GPU time.
6. **fp16 on T4:** NaN or black frame rate; bf16 fallback speed.
7. **Ken Burns vs Wan for faces:** artifact rate; tester preference.
8. **TTS voice A/B/C in my language** (e.g. Sulafat, Gacrux, Charon): pronunciation errors counted by a native speaker.
9. **TTS style empty vs "slow, warm":** words per second (from narration durations), naturalness.
10. **Per-line TTS vs whole-script take:** voice consistency against regeneration cost.
11. **Ducking at the brief's defaults vs ratio 4 / release 800 ms:** intelligibility ratings, measured music level under speech.
12. **Loudnorm TP −1 vs −1.5:** measured true peak after AAC encoding (`make check`).
13. **Subtitle size and position on a real phone:** readability with the platform UI on top.
14. **ACE-Step turbo 8 steps vs base model:** time against tester preference; 3 seeds.
15. **Gemini 3.8 Flash vs 3.5 Flash-Lite for drafting:** schema-valid on first try? latency, list-price cost.
16. **Ceiling: open vs frontier TTS in my language,** e.g. Meta MMS-TTS (open) vs Gemini TTS, blind listener scores (MOS), latency, cost.

## Log

_(your entries here)_
