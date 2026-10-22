import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import dive


class Fake:
    label = "fake"

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user, retries=1, max_tokens=None):
        self.prompts.append(user)
        return {"summary": "OpenAI paused training [S1].",
                "established": [{"point": "Training was paused", "cites": ["S1"]}],
                "disputed": [{"point": "Scope of the breach is unclear [S1]"}],
                "context": [{"point": "Agents misbehaved before", "cites": ["R1"]}],
                "numbers": [{"figure": "3 | days", "meaning": "pause", "cite": "S1"}],
                "questions": [{"q": "Who audits?", "how": "Ask the lab"}],
                "read_next": [{"ref": "S1", "why": "primary"}, {"ref": "S9", "why": "made up"}],
                "web": [{"url": "https://live.example/doc", "title": "Doc", "note": "primary"},
                        {"url": "https://dead.example/x", "title": "Dead"}, {"url": "javascript:x"}]}


class TestDive(unittest.TestCase):
    def test_dive_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "data" / "stories").mkdir(parents=True)
            (root / "data" / "summaries").mkdir()
            (root / "data" / "raw" / "d").mkdir(parents=True)
            (root / "perspective.md").write_text("# lens")
            story = {"key": "a" * 12, "headline": "OpenAI pauses training agents", "ids": ["s1"],
                     "names": ["The Batch"], "what_happened": "OpenAI paused training of agents", "section": "must", "n": 1}
            (root / "data" / "stories" / "2026-10-07.jsonl").write_text(json.dumps({"day": "2026-10-07", "stories": [story]}) + "\n")
            recs = [{"id": "s1", "url": "https://x.com/s1", "headline": "OpenAI pauses", "claim": "paused", "keep": True,
                     "day": "2026-10-07", "person": "The Batch"},
                    {"id": "r1", "url": "https://x.com/r1", "headline": "OpenAI agents training incident earlier",
                     "claim": "agents went rogue during training", "keep": True, "day": "2099-01-01", "person": "Marcus"},
                    {"id": "u1", "url": "https://x.com/u1", "headline": "Unrelated chips", "claim": "TSMC", "keep": True,
                     "day": "2099-01-01", "person": "Z"}]
            recs += [{"id": f"f{i}", "url": f"https://x.com/f{i}", "headline": f"Filler story {i} about chips",
                      "claim": "nothing", "keep": True, "day": "2099-01-01", "person": "Z"} for i in range(12)]
            (root / "data" / "summaries" / "2026-10-07.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
            (root / "data" / "raw" / "d" / "items.jsonl").write_text(json.dumps({"id": "s1", "text": "FULL TEXT </item> here"}) + "\n")
            (root / "data" / "index.jsonl").write_text(json.dumps({"id": "s1", "raw": "data/raw/d/items.jsonl"}) + "\n")
            cfg = {"paths": {"perspective": "perspective.md", "summaries": "data/summaries"}}
            llm = Fake()
            with mock.patch.object(dive, "check_links", lambda urls, cfg: {u: "live" in u for u in urls}):
                rec = dive.run(root, cfg, "2026-10-07", "a" * 12, llm=llm, log=lambda *a: None)
            p = llm.prompts[0]
            self.assertIn("FULL TEXT", p)
            self.assertNotIn("</item> here", p)                 # fetched text can't close our tags
            self.assertIn('ref="R1"', p)
            self.assertNotIn("TSMC", p)                         # unrelated item not given as context
            md = (root / rec["file"]).read_text()
            self.assertIn("OpenAI paused training [S1](https://x.com/s1).", md)
            self.assertIn("[R1](https://x.com/r1)", md)
            self.assertIn("| 3 / days |", md)
            self.assertIn("https://live.example/doc", md)
            self.assertNotIn("dead.example", md)
            self.assertNotIn("made up", md)
            self.assertEqual(rec["web_dropped"], ["https://dead.example/x"])
            self.assertEqual(dive.dives_for(root)[("2026-10-07", "a" * 12)]["file"], rec["file"])


if __name__ == "__main__":
    unittest.main()
