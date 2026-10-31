import json
import tempfile
import unittest
from pathlib import Path

from pipeline import audit, compare, deepdive


class FramingTest(unittest.TestCase):
    def test_framing_skipped(self):
        for s, sec in [("The AGI-forward reading says models are already useful for most health questions.", "readings"),
                       ("Picture a startup that builds a medication-reminder app on a frontier API.", "plainly"),
                       ("Our read is that this is where chatbot liability starts to get priced.", "evidence"),
                       ("Over a long conversation, a disclaimer can't outweigh a system that agrees.", "readings")]:
            self.assertTrue(audit.dd_framing(s, sec), s)

    def test_facts_kept(self):
        for s, sec in [("On May 21, 2025, Judge Anne Conway refused to dismiss most of the claims.", "evidence"),
                       ("Eric Goldman called it an extremely dangerous ruling for the AI industry.", "readings")]:
            self.assertFalse(audit.dd_framing(s, sec), s)

    def test_dd_claims_excludes_framing(self):
        secs = [("readings", "The AI-realist reading says the problem is built into how models are trained. "
                             "Eric Goldman argues the line the court drew falls apart under its own logic.")]
        texts = [c["text"] for c in audit.dd_claims(secs, ["corpus text"])]
        self.assertEqual(len(texts), 1)
        self.assertIn("Goldman", texts[0])


class CompareDeepDiveTest(unittest.TestCase):
    def test_row(self):
        root = Path(tempfile.mkdtemp())
        (root / "data" / "audit").mkdir(parents=True)
        (root / deepdive.DIR).mkdir(parents=True)
        (root / deepdive.DIR / "2026-10-31.md").write_text("one two three", "utf-8")
        (root / "data" / "audit" / "2026-10-31-deepdive.json").write_text(json.dumps({"checked": 9, "held": [{}, {}]}))
        (root / deepdive.LOG).parent.mkdir(parents=True, exist_ok=True)
        (root / deepdive.LOG).write_text(json.dumps({"day": "2026-10-31", "status": "written", "sources": ["a", "b"]}) + "\n")
        self.assertEqual(compare._deepdive(root, "2026-10-31"), "written, 3 words, 2 sources, fact check 9 checked / 2 held")
        self.assertEqual(compare._deepdive(root, "2026-10-30"), "none")


if __name__ == "__main__":
    unittest.main()
