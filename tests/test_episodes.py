import datetime as dt
import tempfile
import unittest
from pathlib import Path

from pipeline import episodes, site

MD = """# AI Briefing · {day}

**The day in brief.** Agents went rogue.

## Top of mind

- **Lead.** Text. [1](https://x.com/a)
"""


class TestEpisodes(unittest.TestCase):
    def test_hidden_day_leaves_site_and_feeds(self):
        root = Path(tempfile.mkdtemp())
        b = root / "briefings"
        b.mkdir()
        today = dt.date.today()
        days = [(today - dt.timedelta(days=i)).isoformat() for i in range(2)]
        for d in days:
            (b / f"{d}.md").write_text(MD.format(day=d))
            (b / f"{d}.mp3").write_bytes(b"ID3" + b"\0" * 100)
        episodes.set_hidden(root, days[0], True, "bad audio")
        res = site.build(root, {"podcast": {"title": "AI Briefing"}}, out=root / "site", base_url="https://u.example/b/")
        self.assertEqual(res["days"], 1)
        out = root / "site"
        self.assertFalse((out / days[0]).exists())
        self.assertFalse((out / "audio" / f"{days[0]}.mp3").exists())
        for f in ("index.html", "feed.xml", "podcast.xml"):
            self.assertNotIn(days[0], (out / f).read_text(), f)
        idx = (out / "index.html").read_text()
        self.assertIn("Curated by Steven Woods", idx)
        self.assertIn("Read the full briefing", idx)
        self.assertIn(f'src="audio/{days[1]}.mp3"', idx)
        self.assertNotIn("/control", idx)
        episodes.set_hidden(root, days[0], False)
        self.assertEqual(episodes.hidden_days(root), set())

    def test_delete_audio(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-10-05.mp3").write_bytes(b"x")
        self.assertEqual(episodes.delete_audio(root, {}, "2026-10-05"), ["briefings/2026-10-05.mp3"])
        self.assertEqual(episodes.delete_audio(root, {}, "2026-10-05"), [])


if __name__ == "__main__":
    unittest.main()
