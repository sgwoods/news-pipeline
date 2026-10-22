"""Weekly review: local files only, the agreed sections, private names scrubbed, Fridays only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import review


class Review(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "data" / "quality").mkdir(parents=True)
        for d in ("2026-10-15", "2026-10-16"):
            (self.root / "briefings" / f"{d}.md").write_text(f"# AI Briefing {d}\n\n**The day in brief.** x")
            (self.root / "data" / "quality" / f"{d}.json").write_text(json.dumps(
                {"passed": 13, "total": 14, "checks": [{"label": "Words", "ok": False}], "values": {"privacy": "pass"}}))

    def test_gathers_editions_and_scorecards(self):
        data = review.gather(self.root, {}, "2026-10-16")
        self.assertIn("# Edition 2026-10-15", data)
        self.assertIn('"missed": ["Words"]', data)

    def test_writes_scrubbed_review(self):
        class B:
            label = "test"

            def complete(self, system, user, json_mode=True, max_tokens=None):
                assert "never as instructions" in user
                return "## Bottom line\nGood week. Board seat: Steven Woods sits on Corvane's board. Fine.\n\n## Scores\n"
        with mock.patch("pipeline.llm.for_stage", lambda cfg, stage: B()), \
                mock.patch("pipeline.stages.scrub_private", lambda t: (t, [])):
            out = review.run(self.root, {}, "2026-10-16", log=lambda *a: None)
        text = out.read_text()
        self.assertIn("## Bottom line", text)
        self.assertNotIn("Board seat", text)

    def test_due_on_fridays_once(self):
        self.assertTrue(review.due(self.root, {}, "2026-10-16"))          # a Friday
        self.assertFalse(review.due(self.root, {}, "2026-10-17"))
        (self.root / review.DIR).mkdir(parents=True, exist_ok=True)
        (self.root / review.DIR / "2026-10-16-weekly-review.md").write_text("x")
        self.assertFalse(review.due(self.root, {}, "2026-10-16"))


if __name__ == "__main__":
    unittest.main()
