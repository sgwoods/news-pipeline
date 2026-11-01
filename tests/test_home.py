import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import home


class HomeTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "data" / "state").mkdir(parents=True)
        (self.root / "briefings" / "2026-11-01.md").write_text(
            "# AI Briefing · Sunday\n\n## Today in 30 seconds\n- **One.** a\n- **Two.** b\n\n## Must read\n", "utf-8")

    def test_edition_blocks(self):
        (self.root / "data" / "email-log.jsonl").write_text(json.dumps(
            {"day": "2026-11-01", "at": "2026-11-01T09:29:44", "ok": True, "sent": 8}) + "\n")
        e = home.edition(self.root, {}, "2026-11-01")
        self.assertTrue(e["built"])
        self.assertEqual(e["top"], ["One.", "Two."])
        self.assertEqual(e["email"], {"at": "09:29", "sent": 8})
        self.assertIsNone(e["slack"])

    def test_unsent_edition_needs_you(self):
        with mock.patch("pipeline.release.check_approval", return_value=(True, "")):
            n = home.needs(self.root, {}, "2026-11-01", now=dt.datetime(2026, 11, 1, 8, 0))
        self.assertEqual(n[0]["level"], "act")
        self.assertIn("not emailed", n[0]["text"])

    def test_calm_when_nothing_due(self):
        (self.root / "data" / "email-log.jsonl").write_text(json.dumps({"day": "2026-11-01", "ok": True, "at": "x"}) + "\n")
        with mock.patch("pipeline.release.check_approval", return_value=(True, "")):
            self.assertEqual(home.needs(self.root, {}, "2026-11-01", now=dt.datetime(2026, 11, 1, 8, 0)), [])


if __name__ == "__main__":
    unittest.main()
