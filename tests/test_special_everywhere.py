"""Special editions everywhere (Steven, 2026-11-05): front page, the day's page, the next morning's email."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import mailer, special


def _root():
    root = Path(tempfile.mkdtemp())
    (root / special.DIR).mkdir(parents=True)
    (root / "data").mkdir()
    (root / special.DIR / "2026-11-04.md").write_text("# Deep dive: T\n\n*AI Briefing · special edition*\n\nThe summary.\n\n## Sources\n")
    (root / special.DIR / "2026-11-04.mp3").write_bytes(b"ID3")
    (root / special.LOG).write_text(json.dumps({"day": "2026-11-04", "status": "published", "title": "T"}) + "\n")
    return root


class Everywhere(unittest.TestCase):
    def test_next_morning_email_card(self):
        root = _root()
        cfg = {"publish": {"site_url": "https://example.org/b/"}}
        sp = mailer.special_for(root, cfg, "2026-11-05")
        self.assertEqual((sp["title"], sp["when"], sp["url"]), ("T", "yesterday", "https://example.org/b/2026-11-04/special/"))
        self.assertIsNone(mailer.special_for(root, cfg, "2026-11-07"))

    def test_front_page_and_day_page(self):
        root = _root()
        items = special.landing_items(root)
        self.assertEqual((items[0]["href"], items[0]["special"]), ("2026-11-04/special/index.html", True))
        out = Path(tempfile.mkdtemp())
        (out / "2026-11-04").mkdir()
        (out / "2026-11-04" / "index.html").write_text('<div id="brief">x</div>')
        special.link_day_page(out, "2026-11-04", "Special edition: T")
        special.link_day_page(out, "2026-11-04", "Special edition: T")          # once
        html = (out / "2026-11-04" / "index.html").read_text()
        self.assertEqual(html.count("special/index.html"), 1)

    def test_slack_needs_a_release_and_the_switch(self):
        root = _root()
        self.assertIn("skipped", special.slack(root, {}, "2026-11-04"))         # slack.post.enabled is off
        with self.assertRaises(special.SpecialError):
            special.slack(root, {}, "2026-11-03")


if __name__ == "__main__":
    unittest.main()
