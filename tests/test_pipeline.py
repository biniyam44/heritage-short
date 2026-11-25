"""Unit tests + the walkthrough claim as a test: edit one shot, only that shot regenerates (mock mode)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Units(unittest.TestCase):
    def test_hash_ignores_key_order(self):
        from pipeline.common import sha
        self.assertEqual(sha({"a": 1, "b": [1, 2]}), sha({"b": [1, 2], "a": 1}))
        self.assertNotEqual(sha({"a": 1}), sha({"a": 2}))

    def test_subtitles_fit_two_lines(self):
        from pipeline.assemble import cues
        text = "This is a deliberately long subtitle line that must be split into short readable cues for phones."
        out = cues([{"id": "s01", "start": 0, "dur": 9, "narr": "x", "narr_len": 8, "subtitle": text}])
        self.assertGreaterEqual(len(out), 2)
        for c in out:
            self.assertLessEqual(len(c["lines"]), 2)
            self.assertTrue(all(len(line) <= 40 for line in c["lines"]), c)

    def test_consent_gate_blocks_real_person_without_record(self):
        from pipeline import consent
        sb = json.loads((ROOT / "storyboard.json").read_text())
        sb["characters"] = [{"id": "nana", "description": "an old woman in a white shawl", "real_person": True,
                             "consent_id": "C9"}]
        self.assertTrue(any("C9" in p for p in consent.problems(sb)))


class OnlyTheChangedShotRegenerates(unittest.TestCase):
    def test_edit_one_line(self):
        tmp = Path(tempfile.mkdtemp())
        sb_path = tmp / "storyboard.json"
        sb = json.loads((ROOT / "storyboard.json").read_text())
        sb_path.write_text(json.dumps(sb))
        env = {**os.environ, "MOCK": "1", "STORYBOARD": str(sb_path), "OUT_DIR": str(tmp / "out"),
               "RUNS_FILE": str(tmp / "runs.jsonl"), "INBOX_DIR": str(tmp / "inbox"), "WORK_DIR": str(tmp / "work"),
               "FORCE": "", "ONLY": ""}

        def run(*stages):
            for st in stages:
                r = subprocess.run([sys.executable, "-m", f"pipeline.{st}"], cwd=ROOT, env=env,
                                   capture_output=True, text=True)
                if r.returncode:
                    self.fail(f"{st} failed:\n{r.stdout}\n{r.stderr}")

        def calls():
            return [json.loads(l) for l in (tmp / "runs.jsonl").read_text().splitlines()]

        run("keyframes", "narration", "shots")
        before = len(calls())
        target = sb["shots"][1]["id"]
        sb["shots"][1]["narration"] += " Again."
        sb["shots"][1]["keyframe_prompt"] += ", seen from the doorway"
        sb_path.write_text(json.dumps(sb))
        run("keyframes", "narration", "shots")
        new = calls()[before:]
        self.assertEqual(sorted({(c["stage"], c["item"]) for c in new}),
                         sorted({("keyframes", target), ("narration", target), ("shots", target)}))


if __name__ == "__main__":
    unittest.main()
