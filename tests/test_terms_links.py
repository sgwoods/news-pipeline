import unittest

from pipeline import editorial, links
from pipeline.audio import banned, parse_briefing
from pipeline.speech import expand


class TermsAndLinks(unittest.TestCase):
    def test_tracker_never_cited(self):
        r = {"url": "https://link.mail.beehiiv.com/ss/c/u001.abc", "public_url": "https://www.therundown.ai/p/x",
             "source_kind": "email", "person": "The Rundown AI"}
        self.assertEqual(editorial._cite_url(r), "https://www.therundown.ai/p/x")
        r2 = {**r, "public_url": ""}
        self.assertNotIn("beehiiv", editorial._cite_url(r2))
        self.assertTrue(links.is_tracker("https://tracking.tldrnewsletter.com/CL0/x"))
        self.assertFalse(links.is_tracker("https://www.theverge.com/ai"))

    def test_enrich_falls_back_to_public_page(self):
        r = {"url": "https://link.mail.beehiiv.com/ss/c/u001.abc", "public_url": "https://www.therundown.ai/p/x"}
        import json, tempfile
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        (root / "data/state").mkdir(parents=True)
        (root / links.CACHE).write_text(json.dumps({r["url"]: ""}))     # already looked up: no network
        links.enrich(root, [r], {})
        self.assertEqual(r["url"], "https://www.therundown.ai/p/x")

    def test_ranks_spoken_and_allowed(self):
        self.assertEqual(expand("ranks #2 overall"), "ranks number two overall")
        self.assertEqual(banned("Meta ranks #2."), "")
        self.assertTrue(banned("## Heading"))

    def test_evidence_check_label_read_by_audio(self):
        md = ("# AI Briefing · Wed Oct 14, 2026\n\n**The day in brief.** x\n\n## Must read\n\n### 1. Head\n**Src** · [source](https://a.com)\n\n"
              "- **What happened:** y\n- **Evidence check:** Holds. z\n- **The AI-realist view:** w\n")
        st = parse_briefing(md)["stories"][0]
        self.assertEqual(st["Critical pass"], "Holds. z")
        self.assertEqual(st["The AI-realist view"], "w")


if __name__ == "__main__":
    unittest.main()
