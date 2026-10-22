import json
import tempfile
import unittest
from pathlib import Path

from pipeline import feedback, quality

MD = """# AI Briefing · Wednesday, October 14, 2026

**The day in brief.** x

## Must read

### 1. A
**Reuters** · report · [source](https://www.reuters.com/a)

- **Evidence check:** Overstated. y
- **Our read:** This helps app-layer companies.

### 2. B
**Rundown** · summary · [source](https://link.mail.beehiiv.com/ss/c/u001.x)

- **Evidence check:** Holds. z
- **Our read:** Treat as unverified.

## Worth knowing

- **3. C.** w ([x](https://techmeme.com/a))
"""


class Quality(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "data").mkdir()
        (self.root / "briefings/2026-10-14.md").write_text(MD + " word" * 900)
        (self.root / "data/briefings.jsonl").write_text(json.dumps({"day": "2026-10-14", "quotes_removed": 1,
                                                                   "balance": {"must": 2, "must_grounded": 1}}))
        (self.root / "data/runs.jsonl").write_text(json.dumps({"day": "2026-10-14", "stages": {
            "critique": {"verdicts": {"holds": 6, "mixed": 4, "overstated": 6, "unsupported": 4}},
            "audio": {"minutes": 8.7, "errors": []}}}))

    def test_scorecard(self):
        r = quality.score_day(self.root, {}, "2026-10-14")
        v = r["values"]
        self.assertEqual((v["must"], v["worth"]), (2, 1))
        self.assertEqual(v["critical_share"], 0.5)
        self.assertEqual(v["opportunity_share"], 0.5)
        self.assertEqual(v["personal_links"], 1)
        self.assertEqual(v["privacy"], "fail")
        self.assertEqual(v["must_grounded"], 0.5)
        bad = {c["key"] for c in r["checks"] if not c["ok"]}
        self.assertTrue({"privacy", "critical_share", "must_grounded", "quotes_removed"} <= bad)
        self.assertTrue((self.root / quality.DIR / "2026-10-14.json").exists())

    def test_ratings(self):
        quality.add_rating(self.root, "2026-10-14", 4)
        quality.add_rating(self.root, "2026-10-14", 2, "reader:abc")
        quality.add_rating(self.root, "2026-10-14", 4, "reader:def")
        r = quality.score_day(self.root, {}, "2026-10-14")
        self.assertEqual((r["rating_steven"], r["rating_readers"], r["n_reader_ratings"]), (4, 3.0, 2))
        with self.assertRaises(ValueError):
            quality.add_rating(self.root, "2026-10-14", 9)

    def test_reply_rating_parsed(self):
        from email.message import EmailMessage
        m = EmailMessage()
        m["From"], m["Subject"], m["Date"] = "J <j@example.com>", "Re: AI Briefing · Wed Oct 14: x", "Wed, 14 Oct 2026 09:00:00 -0400"
        m["Message-ID"] = "<r1@example.com>"
        m.set_content("4 - good, a bit long")
        self.assertEqual(feedback.parse_reply(m.as_bytes(), {})["rating"], 4)
        m.replace_header("Message-ID", "<r2@example.com>")
        m.set_content("$4B figure is wrong")
        self.assertNotIn("rating", feedback.parse_reply(m.as_bytes(), {}))


if __name__ == "__main__":
    unittest.main()
