# Plan to the deadline: Thu 26 Nov 2026, 23:59 EAT (aim to submit by 20:00)

Times are EAT. Cloudflare's free image quota resets at **03:00 EAT** (00:00 UTC). Gemini's daily quota
resets at midnight Pacific (**11:00 EAT**). Kaggle GPU queues are the main risk, so push GPU jobs early.

## Phase 1: story and sound (Tue evening → Wed morning)

| When | Do | Command |
|---|---|---|
| Tue 18:00 | Create keys (Gemini, Cloudflare, Kaggle phone-verified), paste into `.env` | `cp .env.example .env` → `make smoke` |
| Tue 18:30 | Write `story/brief.md` **in my own words**; list private terms in `private_terms.txt` | |
| Tue 19:30 | Ask every real person shown or voiced for consent; fill the table in `ETHICS.md` | `make consent` |
| Tue 20:00 | Draft, then **rewrite the narration myself** in my language; check every subtitle | `make draft` → edit `storyboard.json` → `make validate` |
| Tue 21:00 | Narration + radio cut; send it to 3+ people tonight | `make radio` → `outputs/radio/radio_cut.mp4` |
| Tue 22:00 | First keyframes (before the 03:00 quota reset); pick `wan` vs `kenburns` per shot | `make keyframes` |
| Wed 08:00 | Write user test 1 notes in `DESIGN.md`; edit the storyboard | |

## Phase 2: pictures, motion, music (Wed, revised 09:15 after the film review)

Cloudflare's free images for today ran out at 09:02 with s05, s07 and s08 still to redo, so those wait for
the reset (00:00 UTC = 03:00 EAT). Everything else carries on.

| When | Do | Command |
|---|---|---|
| ~10:30 | Wan clips for s02–s04 (Kaggle, ~70 min) | `make kaggle-status` → when COMPLETE: `make kaggle-pull && make shots` |
| after Wan | Six music takes (Kaggle, queued behind Wan): listen, then copy the chosen take's prompt and seed into `music.prompt` / `music.seed` (no new GPU run) | `make kaggle-status KIND=music` → `make kaggle-pull KIND=music && make music` → `open outputs/music/candidates` → edit → `make music` |
| today | User test 1 if not done yet: the radio cut (voice + subtitles over a placeholder pad, on black) | `make radio` → `outputs/radio/radio_cut.mp4`; notes → `DESIGN.md` |
| today | Start the docs from evidence already saved | `outputs/experiments/`, `runs.jsonl` |

## Phase 3: finish and ship (Thu)

| When | Do | Command |
|---|---|---|
| Thu, when up (after 03:00) | Redo s02, s03, s05, s07, s08 on the fresh quota: 3 versions each (15 images, about 3,500 of the 10,000 neurons), pick one per shot. Check: s02 shows one arm only; s02, s03 and s05 show the dark cardigan sleeve; s05's two hands come from the same side; s07/s08 show the boy, not a second woman; in s08 the boy feeds his mother | `ONLY=s02,s03,s05,s07,s08 make keyframe-candidates N=3` → `open outputs/keyframes/candidates` → put the chosen seeds into `storyboard.json` → `ONLY=s02,s03,s05,s07,s08 make keyframes` (copies my picks, no new calls) |
| then | Wan for s02, s03, s05 in one Kaggle run (~77 min plus any queue; the model loads once). If time is short, set s05's `motion.backend` to `"kenburns"` (instant) | `ONLY=s02,s03,s05 make shots && make kaggle-push` → `make kaggle-status` → `make kaggle-pull && make shots` |
| then | Final film and checks (must be all PASS) | `make film` → `make check` → `make costs` |
| Thu morning | User test 2 (3+ people, on phones) | notes → `DESIGN.md` |
| Thu midday | Fill EXPERIMENTS (~10), FAILURES, COSTS notes, ETHICS, DESIGN with real evidence | |
| Thu 14:00 | Report (below); push the repo public | |
| Thu 16:00 | Walkthrough video ≤ 5 min (below) | |
| Thu 18:00 | Write and publish the post myself, with the platform's AI label on | |
| Thu 20:00 | Submit both assignments. Buffer until 23:59 | |

## Only I can do these

- [ ] Choose the person, place or story and write the brief in my own words
- [ ] Choose the narration language and the audience
- [ ] Get consent from every real person shown or voiced and record it in ETHICS.md (gate: no record = film scores 0)
- [ ] Create the accounts and paste the keys into `.env` myself (Gemini, Cloudflare account ID + token, Kaggle, GitHub repo)
- [ ] Rewrite and approve every narration line and subtitle (I am the native speaker)
- [ ] Run both user tests (3+ people each) and write down what they actually said
- [ ] Record real experiment results, failures and costs from the logs; never invent them
- [ ] Write the report and the public post myself; switch the AI label on
- [ ] Record the walkthrough; be ready to explain the code in the AI interview
- [ ] Commit and push when I am ready (`git init`, `gh repo create --public`)

## Report outline (my words)

1. What I set out to make, and for whom
2. What my audience told me (test 1 → changes, test 2 → changes)
3. The hardest problem and how I solved it (with the log line or commit)
4. One suggested practice that beat my instinct, and one that didn't, each with evidence
   (candidates: radio cut first, drafting at 480p, Ken Burns for faces, per-line TTS, two-pass loudnorm)
5. Ceiling work (e.g. open vs frontier TTS benchmark in my language: EXPERIMENTS #16)
6. What I'd build next

## Walkthrough video (≤ 5 min)

1. 60 s: architecture (ARCHITECTURE.md diagram; storyboard.json as the contract)
2. 60 s: one hard decision and why (my choice)
3. 2 min: edit one narration line in `storyboard.json` → `make film` → show `cached` for everything else,
   `generating (changed: text)` for that shot, and the one new line in `runs.jsonl`
4. 30 s: `make check` passing, then the final film
