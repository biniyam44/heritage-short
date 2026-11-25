# Design

_Template. Every answer below must be yours, from real conversations and real tests._

## Audience and intent

- **Who it is for:** _<e.g. my cousins abroad who never met her; age, what they know, the language they speak>_
- **Where they watch:** _<phone, family group chat, Instagram Reels…> → why the master is 9:16 with burned-in subtitles>_
- **What I want them to feel / do at the end:** _<…>_
- **Why this narration language:** _<…>_
- **Constraints I chose:** _<e.g. no AI faces of real people → portraits as Ken Burns over real photos>_

## User test 1: radio cut (≥ 3 people)

`make radio` → `outputs/radio/radio_cut.mp4` (real narration + subtitles over placeholder music, on black).

| Tester (initials / role) | Date | Knows the language? | What they said (their words) |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

Questions I asked: _<e.g. "What is this about?", "Where did you lose interest?", "Which line stayed with you?", "Was any subtitle too fast?">_

**What I changed because of it:** _<line edits, shot order, pacing, voice choice… with the commit or storyboard diff>_

## User test 2: near-final cut (≥ 3 people)

| Tester | Date | Device | What they said |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

**What I changed because of it:** _<…>_

## Why each shot exists

From `storyboard.json` → `shots[].purpose` (keep the two in sync).

| Shot | Time | Scene | Visual and movement | Made with | Purpose |
|---|---|---|---|---|---|
| s01 | 00–08s | Before sunrise | Mother enters the kitchen before dawn; slow push-in. | Ken Burns | I want viewers to see that a mother’s day begins before the rest of the family wakes up. |
| s02 | 08–16s | Preparation | Close-up of her stirring fermented teff batter. | Wan 2.2 | This reminds young viewers how much preparation goes into the food they often take for granted. |
| s03 | 16–24s | Baking | She pours the batter in a spiral onto the mitad. | Wan 2.2 | I want younger Ethiopians to see the skill involved in making injera the traditional way. |
| s04 | 24–32s | Injera | Close-up of injera developing its distinctive holes. | Wan 2.2 | The familiar texture and rising steam are meant to remind Ethiopians living abroad of fresh injera at home. |
| s05 | 32–40s | Mother’s work | Her hands lift the cooked injera from the mitad. | Wan 2.2 | I want the audience to notice the patience and repeated work behind a meal that may seem ordinary. |
| s06 | 40–48s | Her son | Her son enters the kitchen sleepily; slow push-in. | Ken Burns | Showing the boy wake up after his mother has been working helps younger viewers see how easily they can overlook her efforts. |
| s07 | 48–56s | Breakfast | Mother serves injera and shiro at the mesob. | Ken Burns | I want families to recognize how sharing a meal around the mesob brings people together. |
| s08 | 56–64s | Gursha | The son offers his mother the first gursha. | Ken Burns | The son’s gursha shows young viewers that even a small gesture can express gratitude to their parents. |
| s09 | 64–72s | Love and gratitude | They share breakfast as the camera pulls back. | Ken Burns | I want viewers to leave the film remembering the warmth of home and appreciating the people who care for them. |
| end card | 72–75s | End card | Film title and AI disclosure. | text drawn in code | I want viewers to know that the film was made with AI and that its characters are fictional. |

## Visual and sound decisions

- Style prompt and why: _<…>_
- Voice (name + style) and why, after listening to: _<voices compared>_
- Music prompt and why: _<…>_
- 16:9 version: vertical master on a blurred pillarbox (no second GPU pass). Tester reaction: _<…>_
