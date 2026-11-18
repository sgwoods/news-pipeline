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

    def test_second_pass_rescues_a_section_whisper_skipped(self):
        # 2026-11-14: the deep-dive opener followed the sound logo; Whisper returned nothing for that window and the
        # check called a fine opener "missing". The second pass transcribes the section's own window and clears it.
        segs = [{"start": 0.0, "end": 3.0, "text": "On today's AI Briefing. Margins are the story."},
                {"start": 30.0, "end": 36.0, "text": "First story. Corvane raised five hundred fifty million dollars from a large group of funds."}]
        heard = " ".join(x["text"] for x in segs)
        res = listen.compare(SCRIPT, heard)
        self.assertEqual(res["missing"], ["Intro"])
        self.assertEqual(listen.window_for(res["sections"], 1, segs), (1.5, 31.5))
        calls = []
        def stt(path):                                     # the clip alone transcribes fine
            calls.append(path)
            return [{"start": 0, "end": 8, "text": SCRIPT[1][1]}]
        with mock.patch("shutil.which", lambda n: "/usr/bin/ffmpeg"):
            out = listen.second_pass(Path("/tmp/x.mp3"), SCRIPT, res, segs, stt, log=lambda *a: None,
                                     run=lambda *a, **k: None)
        self.assertEqual(out["missing"], [])
        self.assertIn("second pass", out["sections"][1]["note"])
        self.assertEqual(out["sections"][1]["window"], "0:01-0:31")
        self.assertEqual(len(calls), 1)
        # still silent on the second pass: stays flagged, with the window to listen to
        res = listen.compare(SCRIPT, heard)
        with mock.patch("shutil.which", lambda n: "/usr/bin/ffmpeg"):
            out = listen.second_pass(Path("/tmp/x.mp3"), SCRIPT, res, segs, lambda p: [], log=lambda *a: None,
                                     run=lambda *a, **k: None)
        self.assertEqual(out["missing"], ["Intro"])
        self.assertEqual(out["sections"][1]["window"], "0:01-0:31")

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


class Names(unittest.TestCase):
    """Names not heard as written (Steven, 11-12: Huang as "H-wong", AMD as "a, MD"): pronunciation candidates."""
    def test_substitutions_are_reported_under_the_real_spelling(self):
        from pipeline import listen
        table = {"Jensen Huang": "Jensen [Hwang](/hwɑŋ/)", "Nvidia": "En-vidia", "Qwen": "Kwen"}
        spoken = ("Jensen [Hwang](/hwɑŋ/) has resigned from En-vidia. AMD shares fell. Clearlake Capital backs it. "
                  "The Kwen model shipped. Then Fractile raised money.")
        heard = ("Jensen H wong has resigned from Nvidia. A MD shares fell. Clear lake capital backs it. "
                 "The Qen model shipped. Then Fractal raised money.")
        got = {x["word"]: x for x in listen.names_check(spoken, heard, table)}
        self.assertEqual(got["Huang"]["heard"], "h wong"); self.assertTrue(got["Huang"]["entry"])
        self.assertEqual(got["Huang"]["said"], "Hwang")
        self.assertEqual(got["AMD"]["heard"], "a md"); self.assertTrue(got["AMD"]["acronym"])
        self.assertTrue(got["Qwen"]["entry"])
        self.assertIn("Fractile", got); self.assertTrue(got["Fractile"]["close"])
        self.assertNotIn("Clearlake", got)                     # the same sound, spelled Whisper's way
        self.assertNotIn("Nvidia", got)                        # heard as written
        self.assertNotIn("Jensen", got)

    def test_acronyms_said_letter_by_letter_are_fine(self):
        from pipeline import listen
        self.assertEqual(listen.names_check("The API and AWS teams.", "the a p i and aws teams", {}), [])
        self.assertEqual(listen.script_names("Today Nvidia fell. Yesterday Huang left. The board met."), ["Nvidia", "Huang"])


class Pronunciations(unittest.TestCase):
    def test_add_and_change_an_entry(self):
        import tempfile
        from pathlib import Path
        from pipeline import speech
        root = Path(tempfile.mkdtemp())
        (root / "pronunciations.yaml").write_text("# header\nLeCun: Luh-Koon\n")
        speech.add_pronunciation(root, "AMD", "Ay-M-D", note="dashboard 2026-11-14")
        t = speech.load_table(root)
        self.assertEqual(t["AMD"], "Ay-M-D"); self.assertEqual(t["LeCun"], "Luh-Koon")
        speech.add_pronunciation(root, "LeCun", "Luh-Kun")
        self.assertEqual(speech.load_table(root)["LeCun"], "Luh-Kun")
        self.assertIn("# --- from the dashboard ---", (root / "pronunciations.yaml").read_text())
        with self.assertRaises(ValueError):
            speech.add_pronunciation(root, "x\ny", "z")

    def test_recent_names_merge_days(self):
        import json, tempfile
        from pathlib import Path
        from pipeline import listen
        root = Path(tempfile.mkdtemp()); (root / listen.DIR).mkdir(parents=True)
        for d in ("2026-11-12", "2026-11-13"):
            (root / listen.DIR / f"{d}.json").write_text(json.dumps({"names": [{"word": "Huang", "heard": "wong", "entry": True}]}))
        got = listen.recent_names(root)
        self.assertEqual((got[0]["word"], got[0]["n"], got[0]["days"]), ("Huang", 2, ["2026-11-13", "2026-11-12"]))


class AAcronyms(unittest.TestCase):
    """2-4 letter acronyms starting with A are spelled with "Ay" (AMD was read "a, MD"; Steven 11-12)."""
    def test_spelled_unless_the_table_or_the_word_list_covers_them(self):
        from pipeline import speech
        self.assertEqual(speech.spell_a_acronyms("AMD and AGI; ARM chips; APIs; A new day; AMD-based; the AI briefing", {}),
                         "Ay M D and Ay G I; ARM chips; Ay P Is; A new day; Ay M D-based; the AI briefing")
        self.assertEqual(speech.spell_a_acronyms("AMD fell", {"AMD": "Ay M D"}), "AMD fell")
        self.assertIn("Ay M D fell three percent", speech.spoken("AMD fell 3%", {}))
        self.assertEqual(speech.spoken("AI-powered, AI.", {}), "AI-powered, AI.")        # 11-16: "I.I. briefing" never again
