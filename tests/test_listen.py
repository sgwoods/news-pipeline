"""v0.2.17 (Steven, 2026-10-27): the as-published listen check, transcripts in the feed, and the deep-dive feed."""
import datetime as dt
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from pipeline import listen, site

SCRIPT = [("Cold open", "On today's AI Briefing. Margins are the story."),
          ("Intro", "This is the AI Briefing for Tuesday, October twenty seven. I'm Michael. Like everything here, "
                    "this briefing is written and read by AI, from public sources."),
          ("Story 1", "First story. Corvane raised five hundred fifty million dollars from a large group of funds.")]


class Compare(unittest.TestCase):
    def test_a_missing_intro_is_flagged(self):
        heard = "On today's AI Briefing. Margins are the story. First story. Corvane raised five hundred fifty million dollars from a large group of funds."
        r = listen.compare(SCRIPT, heard)
        self.assertEqual(r["missing"], ["Intro"])
        self.assertLess(r["overall"], 0.8)
        full = " ".join(t for _, t in SCRIPT).replace("I'm", "I am")      # small transcription differences pass
        r = listen.compare(SCRIPT, full)
        self.assertEqual(r["missing"], [])
        self.assertGreater(r["overall"], 0.9)

    def test_episode_url_is_the_main_episode_not_the_deep_dive(self):
        feed = ('<rss><channel><item><guid>ai-briefing-deepdive-2026-10-27</guid><enclosure url="https://s/a/deepdive-2026-10-27.mp3"/></item>'
                '<item><guid isPermaLink="false">ai-briefing-2026-10-27</guid><enclosure url="https://s/a/2026-10-27-full.mp3"/></item>'
                '</channel></rss>')
        self.assertEqual(listen.episode_url(feed, "2026-10-27"), "https://s/a/2026-10-27-full.mp3")
        self.assertEqual(listen.episode_url(feed, "2026-10-28"), "")

    def test_check_saves_transcript_and_vtt(self):
        root = Path(tempfile.mkdtemp())
        b = root / "briefings"
        b.mkdir()
        (b / "2026-10-27.spoken.txt").write_text("".join(f"[{n}]\n{t}\n\n" for n, t in SCRIPT), "utf-8")
        feed = '<item><guid>ai-briefing-2026-10-27</guid><enclosure url="https://s/audio/2026-10-27.mp3"/></item>'
        fetch = lambda url: type("R", (), {"text": feed, "content": b"ID3"})()  # noqa: E731
        segs = [{"start": 0.0, "end": 3.5, "text": " ".join(t for _, t in SCRIPT)}]
        with mock.patch.object(Path, "home", return_value=root):
            r = listen.check(root, {"paths": {"briefings": "briefings"}, "publish": {"site_url": "https://s"}},
                             "2026-10-27", log=lambda *a: None, fetch=fetch, stt=lambda p: segs)
        self.assertTrue(r["ok"])
        self.assertTrue((root / listen.DIR / "2026-10-27.vtt").read_text().startswith("WEBVTT"))
        self.assertIn("00:00:03.500", (root / listen.DIR / "2026-10-27.vtt").read_text())
        self.assertEqual(json.loads((root / listen.DIR / "2026-10-27.json").read_text())["segments"], segs)


class Feeds(unittest.TestCase):
    def test_transcript_tag_and_deep_dive_feed(self):
        root = Path(tempfile.mkdtemp())
        day = dt.date.today().isoformat()
        b = root / "briefings"
        (b / "deepdives").mkdir(parents=True)
        (b / f"{day}.md").write_text("# AI Briefing · Today\n\n**The day in brief.** Two stories.\n", "utf-8")
        (b / f"{day}.mp3").write_bytes(b"ID3" + b"\0" * 500)
        (b / "deepdives" / f"{day}.md").write_text("# Deep dive: Robots\n\n*x*\n\nSummary.\n", "utf-8")
        (b / "deepdives" / f"{day}.mp3").write_bytes(b"ID3" + b"\0" * 500)
        (root / "data").mkdir()
        (root / "data" / "deepdives.jsonl").write_text(json.dumps({"day": day, "status": "published", "title": "Robots"}) + "\n")
        (root / "data" / "transcripts").mkdir()
        (root / "data" / "transcripts" / f"{day}.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n")
        (root / "assets").mkdir()
        (root / "assets" / "podcast-cover.png").write_bytes(b"png")
        (root / "assets" / "deepdive-cover.png").write_bytes(b"png")
        site.build(root, {"podcast": {"author": "Steven"}}, out=root / "site", base_url="https://u.github.io/b/")
        ns = {"podcast": "https://podcastindex.org/namespace/1.0", "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        main = ET.parse(root / "site" / "podcast.xml").getroot()
        tr = main.find(".//item/podcast:transcript", ns)
        self.assertEqual(tr.get("url"), f"https://u.github.io/b/audio/{day}.vtt")
        self.assertTrue((root / "site" / "audio" / f"{day}.vtt").exists())
        dd = ET.parse(root / "site" / site.DD_FEED).getroot()
        self.assertEqual(dd.find("channel/title").text, site.DD_TITLE)
        self.assertRegex(dd.find("channel/itunes:image", ns).get("href"), r"^https://u\.github\.io/b/deepdive-cover-[0-9a-f]{8}\.png$")
        items = dd.findall("channel/item")
        self.assertEqual(len(items), 1)
        self.assertIn("ai-briefing-dd-", items[0].find("guid").text)
        self.assertIn(site.DD_FEED, (root / "site" / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
