"""The weekly flagship (Steven, 2026-10-27): Saturday's deep dive as a two-voice, ~22-minute episode."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import deepdive, dive, record

from tests.test_deepdive import STORY, Fake, WRITE

SAT = "2026-10-31"
TURNS = {"title": "Who gets paid in physical AI", "summary": "Robots, money and who captures it.",
         "turns": [{"section": "why_today", "speaker": "host", "text": "This week OpenAI said its model proved a conjecture."},
                   {"section": "why_today", "speaker": "sceptic", "text": "Said is doing a lot of work there, Bella."},
                   {"section": "plainly", "speaker": "host", "text": "A proof is a chain of steps anyone can check."},
                   {"section": "evidence", "speaker": "sceptic", "text": "Referees have not reported yet."},
                   {"section": "evidence", "speaker": "host", "text": "The lab calls it \"a genuine first\" in its post."},
                   {"section": "so_what", "speaker": "host", "text": "We would ask whether a proof checker was used."},
                   {"section": "watch", "speaker": "sceptic", "text": "Watch for a formal verification."},
                   {"section": "bogus", "speaker": "host", "text": "dropped"}],
         "sources": WRITE["sources"]}


class Flagship(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for d in ("briefings", "data/stories", f"data/raw/{SAT}"):
            (self.root / d).mkdir(parents=True)
        (self.root / "perspective.md").write_text("# Perspective\n")
        (self.root / f"briefings/{SAT}.md").write_text("# AI Briefing\n\n**The day in brief.** Proofs.\n")
        (self.root / f"data/stories/{SAT}.jsonl").write_text(json.dumps({"stories": [STORY]}))
        (self.root / f"data/raw/{SAT}/items.jsonl").write_text(json.dumps(
            {"id": "i1", "person": "OpenAI (news)", "url": "https://openai.com/index/proof", "title": "Proof",
             "text": "Our model proved it. This is a genuine first."}))
        self.cfg = {"paths": {"briefings": "briefings", "perspective": "perspective.md"}, "deepdive": {"max_per_week": 7}}
        self._cl, self._pt = dive.check_links, record.page_text
        dive.check_links = lambda urls, cfg: {u: "dead" not in u for u in urls}
        record.page_text = lambda url, cfg, chars=8000: ""

    def tearDown(self):
        dive.check_links, record.page_text = self._cl, self._pt

    def test_saturday_is_the_flagship(self):
        self.assertTrue(deepdive.is_flagship({}, SAT))
        self.assertFalse(deepdive.is_flagship({}, "2026-10-30"))
        self.assertFalse(deepdive.is_flagship({"deepdive": {"flagship": {"enabled": False}}}, SAT))

    def test_two_voice_script_article_and_record(self):
        pick = Fake({"candidates": [{"topic": "AI proofs", "kind": "breakthrough", "why_today": "x", "angle": "a",
                                     "story_numbers": [1], "strength": 5}], "best": 0})
        w = Fake(TURNS)
        r = deepdive.run(self.root, self.cfg, SAT, log=lambda *a: None, llm_pick=pick, llm_write=w, tts=False)
        self.assertEqual(r["status"], "written")
        self.assertEqual(r["format"], "flagship")
        self.assertIn("two-voice conversation", w.prompts[0])
        self.assertIn("Bella is the host", w.prompts[0])
        parts = json.loads((self.root / deepdive.DIR / f"{SAT}.parts.json").read_text())["parts"]
        names = [n for n, _ in parts]
        self.assertEqual(names[1:3], ["why_today~host", "why_today~sceptic"])
        self.assertNotIn("bogus~host", names)
        self.assertIn("with me is Michael, whose job this week is to push back", parts[0][1])
        md = deepdive.written_md(self.root, SAT)
        self.assertIn("## Why today\n\n**Bella:** This week", md)
        self.assertIn("**Michael:** Said is doing", md)
        self.assertEqual(md.count("## What the evidence shows"), 1)            # turns grouped under one heading
        notes = (self.root / deepdive.DIR / f"{SAT}.md").read_text()
        self.assertIn("the weekly flagship, two voices", notes)

    def test_two_voices_engine_picks_by_turn(self):
        calls = []
        host = type("E", (), {"name": "k", "voice": "af_bella", "check": lambda s: None,
                              "synth": lambda s, t, p: calls.append(("host", t))})()
        sc = type("E", (), {"name": "k", "voice": "am_michael", "check": lambda s: None,
                            "synth": lambda s, t, p: calls.append(("sceptic", t))})()
        e = deepdive._TwoVoices(host, sc, ["Opener", "why_today~host", "why_today~sceptic", "Outro"])
        for t in ("a", "b", "c", "d"):
            e.synth(t, None)
        self.assertEqual([c[0] for c in calls], ["host", "host", "sceptic", "host"])


if __name__ == "__main__":
    unittest.main()
