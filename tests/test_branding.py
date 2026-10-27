"""The email masthead: Steven's photo and colour, the name and the tagline (v0.2.12, Steven 2026-10-26)."""
import tempfile
import unittest
from pathlib import Path

from pipeline import drivedocs, mailer

ROOT = Path(__file__).resolve().parent.parent
MD = ("# AI Briefing · Monday, October 26, 2026\n\n**The day in brief.** Two stories.\n\n## Top of mind\n\n"
      "- **Margins are the story.** Corvane raised.\n")


class Masthead(unittest.TestCase):
    def test_photo_colour_and_tagline(self):
        m = mailer.render("2026-10-26", MD, {"publish": {"site_url": "https://example.github.io/brief/"}})
        self.assertIn('src="https://example.github.io/brief/steven-woods.jpg"', m["html"])
        self.assertIn(mailer.C["brand"], m["html"])
        self.assertIn(mailer.TAGLINE, m["html"])
        self.assertTrue(m["text"].startswith(f"AI Briefing · {mailer.TAGLINE}"))
        m = mailer.render("2026-10-26", MD, {"email": {"tagline": "Another line."}})
        self.assertIn("Another line.", m["html"])

    def test_photo_is_in_assets_and_copied_to_the_site(self):
        if (ROOT / "owner.yaml").exists():                    # the private repo has the photo; the public export doesn't
            self.assertTrue((ROOT / "assets" / mailer.PHOTO).exists())
        self.assertIn("out / PHOTO", (ROOT / "pipeline" / "site.py").read_text("utf-8"))


class ShareLabels(unittest.TestCase):
    def test_slack_is_shared_internally_and_bluesky_says_so(self):     # Steven, 2026-10-27
        from pipeline.stages import display_name
        self.assertEqual(display_name({"person": "Shared by Steven", "source_kind": "shared", "source_url": "slack",
                                       "url": "https://www.nytimes.com/a"}), "Shared internally today")
        self.assertEqual(display_name({"person": "Steven Woods (own posts)", "source_kind": "bluesky"}),
                         "Posted by Steven on Bluesky")
        self.assertEqual(display_name({"person": "Shared by Steven", "url": "https://www.nytimes.com/a"}),
                         "The New York Times")


class PodcastBrand(unittest.TestCase):
    def test_cover_is_the_teal_brand(self):
        if (ROOT / "owner.yaml").exists():
            import struct                                                    # no PIL on the Mac: read the PNG header
            for name in ("podcast-cover.png", "deepdive-cover.png"):
                head = (ROOT / "assets" / name).read_bytes()[:24]
                self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", head[16:24]), (3000, 3000))   # Apple's maximum

    def test_the_show_is_named_first(self):                               # Steven, 10-27: "no introduction"
        self.assertIn('"Cold open", f"On today\'s AI Briefing. {cold}"', (ROOT / "run.py").read_text("utf-8"))
        self.assertIn(".sections.json", (ROOT / "pipeline" / "audio.py").read_text("utf-8"))


class DriveTidy(unittest.TestCase):
    def test_no_duplicate_why_today_and_no_flags(self):
        from pipeline import deepdive
        root = Path(tempfile.mkdtemp())
        d = root / deepdive.DIR
        d.mkdir(parents=True)
        (d / "2026-10-26.md").write_text("# Deep dive: X\n\nSummary.\n\n**Why today.** Because.\n\n## Sources\n\n- a\n", "utf-8")
        (d / "2026-10-26.script.md").write_text("# x\n\n## why_today\n\nBecause.\n", "utf-8")
        _, md = drivedocs.deepdive_md(root, {}, "2026-10-26")
        self.assertEqual(md.count("Why today"), 1)
        self.assertEqual(drivedocs.FLAGS.sub("", "Tim Bray \U0001F1E8\U0001F1E6 · x"), "Tim Bray  · x")


if __name__ == "__main__":
    unittest.main()
