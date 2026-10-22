"""Claim-to-source trace: untraced figures in factual parts are cut, flagged in headlines and analysis."""
import unittest

from pipeline import factcheck

MD = """# AI Briefing · Sunday, October 18, 2026

**The day in brief.** Microsoft walked away from 23,000 chips. The deal was worth $9B over five years.

## Must read

### 1. Microsoft drops Nscale deal for 23K chips
**Reuters** · report · [source](https://www.reuters.com/a)

- **What happened:** Microsoft cancelled its deal to rent 23,000 Nvidia chips. It had paid $4.2B upfront.
- **Our read:** That is 47% of the $9B deal, a big write-off.

## In brief

- Bridge Data Centres seeks $3.8B loan upsizing (Techmeme)
- First in the briefing Oct 11, day 2 · Chapter 11 filing by Character.ai
"""
SOURCES = ["Microsoft cancelled a deal to rent 23K Nvidia chips worth $9 billion over five years.",
           "Bridge Data Centres is in talks to upsize an existing loan from $2.8B to ~$6.6B."]


class FactCheck(unittest.TestCase):
    def test_cuts_untraced_facts_keeps_traced_and_derived(self):
        md, rep = factcheck.check(MD, SOURCES)
        self.assertNotIn("$4.2B", md)                                  # in no source: cut
        self.assertIn("Microsoft cancelled its deal to rent 23,000 Nvidia chips.", md)   # traced: kept
        self.assertIn("$3.8B loan upsizing", md)                       # $6.6B - $2.8B: derived, kept
        self.assertIn("worth $9B", md)
        self.assertTrue(any("$4.2B" in c for c in rep["cut"]))

    def test_analysis_and_headlines_are_flagged_not_cut(self):
        md, rep = factcheck.check(MD.replace("23K chips", "40K chips"), SOURCES)
        self.assertIn("40K chips", md)
        self.assertTrue(any(f.startswith("headline") for f in rep["flagged"]))
        self.assertIn("47% of the $9B deal", md)                       # analysis: flagged at most

    def test_dates_and_chapter_numbers_are_not_figures(self):
        _, rep = factcheck.check(MD, SOURCES)
        self.assertFalse(any("Oct 11" in c or "11" == c.split(": ")[1].split(" ")[0] for c in rep["cut"] + rep["flagged"]))


class SearchBeforeCut(unittest.TestCase):
    def test_found_online_is_kept_with_a_link(self):
        seen = []

        def find(raw, v, kind, base, snt):
            seen.append(raw)
            return {"url": "https://www.example-news.com/a", "outlet": "Example-news", "how": "web"}
        md, rep = factcheck.check(MD, SOURCES, find=find)
        self.assertIn("$4.2B", md)
        self.assertIn("](https://www.example-news.com/a))", md)
        self.assertEqual(rep["cut"], [])
        self.assertTrue(any(s["figure"] == "$4.2B" for s in rep["sourced"]))

    def test_not_found_is_still_cut(self):
        md, rep = factcheck.check(MD, SOURCES, find=lambda *a: None)
        self.assertNotIn("$4.2B", md)
        self.assertTrue(rep["cut"])

    def test_page_must_have_the_figure_near_the_name(self):
        from pipeline import factsearch
        page = "intro " * 200 + "Harvey raised $300 million at a $5 billion valuation. " + "filler " * 400 + "$9 billion"
        self.assertTrue(factsearch.supports(page, 5e9, "money", None, ["Harvey"]))
        self.assertFalse(factsearch.supports(page, 9e9, "money", None, ["Harvey"]))
        self.assertFalse(factsearch.supports(page, 5e9, "money", None, ["Legora"]))

    def test_bing_links_are_unwrapped_and_names_nearest_first(self):
        from pipeline import factsearch
        u = "http://www.bing.com/news/apiclick.aspx?ref=FexRss&url=https%3a%2f%2fwww.lawnext.com%2fa&c=1"
        self.assertEqual(factsearch.real_url(u), "https://www.lawnext.com/a")
        s = "Microsoft's Copilot follows OpenAI, and Harvey raised $300M at a $5B valuation."
        self.assertEqual(factsearch.entities(s, "$5B")[0], "Harvey")
        self.assertEqual(factsearch.query(s, "$5B").split('" ')[0], '"Harvey')

    def test_finder_offline_returns_none(self):
        from pipeline import factsearch

        class Dead:
            def get(self, url):
                raise OSError("no network")
        from unittest import mock
        with mock.patch("pipeline.watchlist._logreq"):
            f = factsearch.Finder(Dead(), ["https://a.example/x"])
            self.assertIsNone(f("$5B", 5e9, "money", None, "Harvey raised at a $5B valuation."))


if __name__ == "__main__":
    unittest.main()
