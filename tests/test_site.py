import json
import tempfile
import unittest
from pathlib import Path

from pipeline import site
from pipeline.textutil import item_id

MD = """# AI Briefing · Monday, October 5, 2026

**The day in brief.** Agent security went legal.

## Top of mind

- **Lead.** Text. [1](https://x.com/a)

## Must read

### 1. OpenAI halts training
**The Batch** · [source](https://x.com/a)

- **What happened:** Paused. <script>alert(1)</script>
"""


class TestSite(unittest.TestCase):
    def test_build_includes_takes_escapes_html_and_excludes_data(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-10-05.md").write_text(MD)
        (root / "briefings" / "2026-10-05.script.md").write_text("not a day")
        (root / "data" / "commentary").mkdir(parents=True)
        (root / "data" / "raw").mkdir(parents=True)
        (root / "data" / "raw" / "secret.txt").write_text("full article text")
        notes = {"notes": {item_id("https://x.com/a"): {"text": "Big deal <b>really</b>"},
                           "overall": {"text": "Overall view"}}}
        (root / "data" / "commentary" / "2026-10-05.json").write_text(json.dumps(notes))
        res = site.build(root, {}, out=root / "site", base_url="https://u.github.io/b/")
        self.assertEqual(res["days"], 1)
        page = (root / "site" / "2026-10-05" / "index.html").read_text()
        self.assertIn("Steven's take</b>Big deal &lt;b&gt;really&lt;/b&gt;", page)
        self.assertIn("Overall view", page)
        self.assertNotIn("<script>alert", page)
        self.assertIn('name="viewport"', page)
        files = {p.name for p in (root / "site").rglob("*")}
        self.assertNotIn("secret.txt", files)
        self.assertIn("feed.xml", files)
        self.assertIn("https://u.github.io/b/2026-10-05/", (root / "site" / "feed.xml").read_text())


if __name__ == "__main__":
    unittest.main()


class TestPodcast(unittest.TestCase):
    def test_podcast_feed_is_valid_rss_with_enclosures(self):
        import datetime as dt
        import xml.etree.ElementTree as ET
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        day = dt.date.today().isoformat()
        (root / "briefings" / f"{day}.md").write_text(MD.replace("Monday, October 5, 2026", "Today"))
        (root / "briefings" / f"{day}.mp3").write_bytes(b"ID3" + b"\0" * 1000)
        (root / "assets").mkdir()
        (root / "assets" / "podcast-cover.png").write_bytes(b"png")
        res = site.build(root, {"podcast": {"author": "Steven"}}, out=root / "site", base_url="https://u.github.io/b/")
        self.assertEqual(res["podcast"], "https://u.github.io/b/podcast.xml")
        x = ET.parse(root / "site" / "podcast.xml").getroot()
        ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        ch = x.find("channel")
        self.assertRegex(ch.find("itunes:image", ns).get("href"), r"^https://u\.github\.io/b/podcast-cover-[0-9a-f]{8}\.png$")
        item = ch.find("item")
        enc = item.find("enclosure")
        self.assertEqual(enc.get("url"), f"https://u.github.io/b/audio/{day}.mp3")
        self.assertEqual(enc.get("type"), "audio/mpeg")
        self.assertIn("OpenAI halts training", item.find("{http://purl.org/rss/1.0/modules/content/}encoded").text)
        self.assertTrue((root / "site" / "podcast-cover.png").exists())
