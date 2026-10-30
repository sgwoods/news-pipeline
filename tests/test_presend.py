"""v0.2.33 (Steven 2026-10-30: "do the fact check BEFORE the email is sent"): the pre-send check rewrites a line
its sources don't support, keeps its links, checks it again, and the page notes when it ran and every correction."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import audit, site

DAY = "2026-10-30"
URL = "https://betakit.com/x"
LINE = (f"- **What happened:** Northwind announced a Series E of up to $7B, with Canada's CDIC participating "
        f"via a staged deal [2]({URL}).")
MD = f"""# AI Briefing

## Today in 30 seconds
- **Northwind opens a round.** The target is $7B at about $36B post-money, led by a retail group. [1]({URL})

## Must read

### 1. Northwind opens Series E
- {LINE[2:]}
- **Why it matters:** sovereign money.

## Worth knowing
"""
SRC = "Northwind announced a Series E of up to $7B led by a retail group at $36B post-money. The Government of Canada will invest in stages."


class Fake:
    label = "fake"

    def __init__(self, fixed):
        self.fixed, self.asked = fixed, []

    def complete_json(self, system, user, max_tokens=0):
        self.asked.append(user)
        if "THE LINE" in user:
            return {"line": self.fixed}
        out = []
        for blk in user.split("CLAIM ")[1:]:
            n = int(blk.split(" ", 1)[0])
            bad = "CDIC" in blk.split("SOURCE EXCERPTS")[0]
            out.append({"n": n, "verdict": "partly" if bad else "supported", "why": "sources say Government of Canada" if bad else ""})
        return {"checks": out}


class Presend(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "briefings" / f"{DAY}.md").write_text(MD, "utf-8")
        (self.root / "data" / "stories").mkdir(parents=True)
        (self.root / "data" / "stories" / f"{DAY}.jsonl").write_text(
            json.dumps({"stories": [{"headline": "Northwind opens Series E", "ids": ["a"]}]}) + "\n", "utf-8")
        p = mock.patch.object(audit.factcheck, "corpus", return_value=[SRC])
        p.start()
        self.addCleanup(p.stop)
        self.stamp = lambda: dt.datetime(2026, 10, 30, 6, 12)

    def test_untraced_acronym_is_found(self):
        self.assertEqual(audit.untraced_names("Canada's CDIC joins; AI and CEO", SRC + " AI CEO"), ["CDIC"])

    def test_a_wrong_line_is_rewritten_before_sending_and_checked_again(self):
        good = (f"- **What happened:** Northwind announced a Series E of up to $7B, with the Government of Canada "
                f"investing in stages [2]({URL}).")
        res = audit.presend(self.root, DAY, Fake(good), "sys", log=lambda *a: None, stamp=self.stamp)
        md = (self.root / "briefings" / f"{DAY}.md").read_text("utf-8")
        self.assertIn(good, md)
        self.assertNotIn("CDIC", md)
        self.assertEqual(len(res["fixes"]), 1)
        self.assertEqual(res["held"], [])
        self.assertEqual(res["fixes"][0]["recheck"], ["supported"])
        self.assertEqual(audit.load_presend(self.root, DAY)["at"], "2026-10-30T06:12:00")

    def test_a_rewrite_that_drops_or_adds_links_is_refused_and_held_for_steven(self):
        bad = "- **What happened:** Northwind raised money [9](https://elsewhere.example/y)."
        res = audit.presend(self.root, DAY, Fake(bad), "sys", log=lambda *a: None, stamp=self.stamp)
        self.assertEqual(res["fixes"], [])
        self.assertTrue(res["held"])
        self.assertIn("CDIC", (self.root / "briefings" / f"{DAY}.md").read_text("utf-8"))

    def test_the_page_notes_the_check_and_each_correction_with_its_time_at_the_end(self):
        good = f"- **What happened:** Northwind announced a Series E of up to $7B, with the Government of Canada investing [2]({URL})."
        audit.presend(self.root, DAY, Fake(good), "sys", log=lambda *a: None, stamp=self.stamp)
        top, foot = site._footnotes(self.root, DAY, [{"at": "2026-10-30T11:16:56", "note": "investor is the Government of Canada"}])
        self.assertIn("Oct 30, 2026, 11:16 ET", top)
        self.assertIn('id="notes"', foot)
        self.assertIn("Correction, Oct 30, 2026, 11:16 ET", foot)
        self.assertIn("Fact check, Oct 30, 2026, 06:12 ET", foot)
        self.assertIn("1 line rewritten", foot)
        self.assertEqual(site._footnotes(self.root, "2026-01-01", []), ("", ""))


class Gaps(Presend):
    """v0.2.33 gap fills: a source the line didn't cite, a wider look before "not found", a second judge."""

    def test_a_fact_only_a_found_page_holds_is_kept_and_cited_and_joins_sources(self):
        gov = "https://www.pm.gc.ca/en/news/x"
        page = {"url": gov, "outlet": "Prime Minister of Canada", "title": "Landmark investment", "text":
                "The Government of Canada will invest in Northwind in stages.", "primary": True}
        good = (f"- **What happened:** Northwind announced a Series E of up to $7B, with the Government of Canada "
                f"investing in stages [Prime Minister of Canada]({gov}) [2]({URL}).")
        md = MD.replace("- **Why it matters:** sovereign money.",
                        f"- **Why it matters:** sovereign money.\n- **Sources:** [BetaKit: x]({URL})")
        (self.root / "briefings" / f"{DAY}.md").write_text(md, "utf-8")
        judge = Fake("")
        with mock.patch("pipeline.factsearch.pages_for", return_value=[page]) as pf:
            res = audit.presend(self.root, DAY, Fake(good), "sys", log=lambda *a: None, stamp=self.stamp,
                                finder=object(), judge=judge)
        self.assertTrue(pf.called)
        out = (self.root / "briefings" / f"{DAY}.md").read_text("utf-8")
        self.assertIn(good, out)
        self.assertIn(f"· [Prime Minister of Canada: Landmark investment]({gov})", out)
        self.assertEqual(res["fixes"][0]["added_source"][0]["url"], gov)
        self.assertTrue(judge.asked)                                    # the second model graded the rewrite

    def test_a_link_from_anywhere_else_is_refused(self):
        page = {"url": "https://www.pm.gc.ca/a", "outlet": "PMO", "text": "Northwind", "primary": True}
        bad = f"- **What happened:** Northwind raised money [x](https://elsewhere.example/y) [2]({URL})."
        with mock.patch("pipeline.factsearch.pages_for", return_value=[page]):
            res = audit.presend(self.root, DAY, Fake(bad), "sys", log=lambda *a: None, stamp=self.stamp, finder=object())
        self.assertEqual(res["fixes"], [])
        self.assertTrue(res["held"])

    def test_not_found_is_looked_at_again_with_more_of_the_sources(self):
        class NF(Fake):
            def complete_json(self, system, user, max_tokens=0):
                self.asked.append(user)
                n = len(user.split("CLAIM ")) - 1
                v = "supported" if len(user) > 6000 or len(self.asked) > 1 else "not found"
                return {"checks": [{"n": i + 1, "verdict": v, "why": ""} for i in range(n)]}
        big = "Northwind announced a Series E of up to $7B. " + ("Filler sentence about other things here. " * 200) + SRC
        with mock.patch.object(audit.factcheck, "corpus", return_value=[big]):
            res = audit.presend(self.root, DAY, NF(""), "sys", log=lambda *a: None, stamp=self.stamp)
        self.assertGreater(res["widened"], 0)
        self.assertEqual(res["held"], [])

    def test_excerpt_puts_the_best_match_first(self):
        texts = ["Nothing here. " * 50 + "Northwind and the Government of Canada agreed $1.6 billion."]
        self.assertTrue(audit._excerpt(texts, "Northwind took $1.6 billion from the Government of Canada")
                        .startswith("Northwind and the Government"))

    def test_primary_sources_are_recognised(self):
        from pipeline import factsearch
        self.assertTrue(factsearch.is_primary("https://www.pm.gc.ca/en/news/x"))
        self.assertTrue(factsearch.is_primary("https://www.sec.gov/x"))
        self.assertFalse(factsearch.is_primary("https://betakit.com/x"))


if __name__ == "__main__":
    unittest.main()
