"""Board seats are private context: the public briefing and podcast never mention them (Steven, 2026-10-16)."""
import tempfile
import unittest
from pathlib import Path

from pipeline.links import DISCLOSURE_FLAG, scrub_output, strip_disclosures


class Disclosures(unittest.TestCase):
    CASES = [
        ("- **Our read:** Board seat (Steven Woods sits on Corvane's board). A CVE record beats a demo.",
         "- **Our read:** A CVE record beats a demo."),
        ("- **Corvane moves into AI security.** Board seat: Steven Woods sits on Corvane's board. Corvane signed an LOI.",
         "- **Corvane moves into AI security.** Corvane signed an LOI."),
        ("buying security: Corvane (Steven Woods sits on its board) signed an LOI.",
         "buying security: Corvane signed an LOI."),
        ("- **Editor's view:** Board seat, so I'm not neutral: Mistral competes with Corvane.",
         "- **Editor's view:** Mistral competes with Corvane."),
        ("- **Quillery goes autonomous (board seat).** It is GA.", "- **Quillery goes autonomous.** It is GA."),
        ("feature?** Board seat; tests whether moats hold.", "feature?** Tests whether moats hold."),
        ("Steven Woods, who edits this briefing, sits on Corvane's board, so weigh our view with that in mind. We think so.",
         "We think so."),
    ]

    def test_removed_without_joining_lines(self):
        for before, after in self.CASES:
            out, n = strip_disclosures(before + "\n\nNext line.\n")
            self.assertEqual(out, after + "\n\nNext line.\n")
            self.assertGreater(n, 0)
            self.assertIsNone(DISCLOSURE_FLAG.search(out))

    def test_untouched_copy(self):
        t = "Curated by Steven Woods.\n- **Our read:** Corvane's board approved the deal.\n"
        self.assertEqual(strip_disclosures(t), (t, 0))

    def test_scrub_output_applies_it(self):
        out, removed = scrub_output("- **Our read:** Board seat: Corvane. Fine.", {})
        self.assertEqual(out, "- **Our read:** Fine.")
        self.assertIn("disclosure", removed)

    def test_site_scan_blocks_it(self):
        from pipeline import publish
        with tempfile.TemporaryDirectory() as d:
            site = Path(d)
            (site / "index.html").write_text("<p>Board seat: Steven Woods sits on Corvane's board.</p>")
            self.assertTrue(any("disclosure" in p for p in publish.scan_site(site, site)))


class OwnerAndPersonalLinks(unittest.TestCase):
    def test_steven_is_never_named(self):
        self.assertEqual(strip_disclosures("**Shared by Steven** · [source](x)\n")[0], "**A reader** · [source](x)\n")
        self.assertEqual(strip_disclosures("It was shared by Steven Woods. Reuters says.\n")[0],
                         "It was shared by a reader. Reuters says.\n")
        self.assertEqual(strip_disclosures("Steven, here's your morning briefing.\n")[0], "Here's your morning briefing.\n")
        self.assertEqual(strip_disclosures("Curated by Steven Woods.\n")[1], 0)

    def test_bylines_credit_the_outlet(self):
        from pipeline.stages import display_name
        self.assertEqual(display_name({"person": "Shared by Steven", "url": "https://www.nytimes.com/a"}), "The New York Times")
        self.assertEqual(display_name({"person": "Forwarded by Steven", "url": "https://www.reuters.com/a"}), "Reuters")

    def test_gift_and_tracking_links(self):
        from pipeline.links import is_tracker
        from pipeline.textutil import clean_url
        self.assertEqual(clean_url("https://www.nytimes.com/a.html?unlocked_article_code=1.x&smid=url-share"),
                         "https://www.nytimes.com/a.html")
        self.assertTrue(is_tracker("https://info.deeplearning.ai/e3t/Ctc/LX+113/abc"))
        out, removed = scrub_output("[x](https://info.deeplearning.ai/e3t/Ctc/abc)", {})
        self.assertEqual(out, "x")


if __name__ == "__main__":
    unittest.main()
