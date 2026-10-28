"""Calls we made, the accuracy audit and the merged top (Steven, 2026-10-27; critic 10-24 #10D and #7A)."""
import json
import logging
import tempfile
import unittest
from pathlib import Path

from pipeline import audio, audit, consistency, editorial, houseviews, mailer, site, textutil

from tests.test_editorial import Fake, rec
from tests.test_houseviews import TEXT

LOG = logging.getLogger("t")
MD = """# AI Briefing · Tuesday, October 27, 2026

**The day in brief.** Filings and price cuts. A question worth asking in diligence this week: would you keep the margin?

## Top of mind

- **Anthropic's numbers are filed.** The S-1 reports $16.3B H1 revenue. [1](https://x.com/1)

## Must read

### 1. Anthropic files S-1 for Nasdaq IPO
**Crunchbase News** · [source](https://x.com/1)

- **What happened:** Anthropic filed an S-1 reporting H1 2026 revenue of $16.3B (Crunchbase News). It also reported a Q2 operating profit of $974M. Analysts were excited about it.
- **Our read:** We think it is a business. *(House view: Bubbles and real platforms coexist)*

## Worth knowing

- **2. SpaceX leases GPUs from Apollo.** The deal is worth about $40B over five years. ([x](https://x.com/2))
"""
STORIES = [{"headline": "Anthropic files S-1 for Nasdaq IPO", "ids": ["a1"], "what_happened": "S-1 filed", "section": "must"},
           {"headline": "SpaceX leases GPUs from Apollo", "ids": ["b2"], "what_happened": "lease", "section": "worth"}]


def root_with(md=MD, stories=STORIES, day="2026-10-27"):
    root = Path(tempfile.mkdtemp())
    (root / "briefings").mkdir()
    (root / "data" / "stories").mkdir(parents=True)
    (root / "briefings" / f"{day}.md").write_text(md)
    (root / "data" / "stories" / f"{day}.jsonl").write_text(json.dumps({"day": day, "stories": stories}) + "\n")
    return root


class Audit(unittest.TestCase):
    def test_claims_prefer_figures_from_what_happened(self):
        cl = audit.claims(MD, STORIES)
        self.assertEqual(cl[0]["text"], "Anthropic filed an S-1 reporting H1 2026 revenue of $16.3B.")
        self.assertEqual(cl[0]["ids"], ["a1"])
        self.assertTrue(any("SpaceX" not in c["text"] and "$974M" in c["text"] for c in cl))
        self.assertTrue(any("$40B" in c["text"] for c in cl))
        self.assertFalse(any("excited" in c["text"] for c in cl[:3]))

    def test_run_saves_counts_and_issues(self):
        root = root_with()
        out = {"checks": [{"n": 1, "verdict": "supported", "why": "", "source": "Crunchbase"},
                          {"n": 2, "verdict": "contradicted", "why": "the source says $947M", "source": "Crunchbase"},
                          {"n": 3, "verdict": "bogus"}]}
        import pipeline.factcheck as fc
        orig = fc.corpus
        fc.corpus = lambda r, ids: ["Anthropic reported revenue of $16.3B in H1 2026 and an operating profit of $947M."]
        try:
            res = audit.run(root, "2026-10-27", Fake(out), "sys", log=lambda *a: None)
        finally:
            fc.corpus = orig
        self.assertEqual(res["supported"], 1)
        self.assertEqual([r["verdict"] for r in res["issues"]], ["contradicted"])
        self.assertEqual(res["claims"][2]["verdict"], "unchecked")
        self.assertTrue((root / audit.DIR / "2026-10-27.json").exists())
        page = site.accuracy_page(root, {})
        self.assertIn("Claims checked", page)
        self.assertNotIn("947", page)                      # the model's notes stay private; counts are public


class Calls(unittest.TestCase):
    def test_scoring_and_page(self):
        root = root_with()
        (root / "data" / "stories" / "2026-11-20.jsonl").write_text(json.dumps({"day": "2026-11-20", "stories": [
            {"headline": "Anthropic S-1 shows Q3 revenue slip", "what_happened": "Revenue fell in Q3."},
            {"headline": "Unrelated robotics round", "what_happened": "A robot company raised money."}]}) + "\n")
        rows = [{"day": "2026-10-27", "key": "k1", "headline": "Anthropic files S-1 for Nasdaq IPO", "view": 7,
                 "view_name": "Bubbles and real platforms coexist", "position": "We think the revenue is real.",
                 "changes_our_mind": "revenue falling next quarter", "check": "2027-01-25", "status": "open"},
                {"day": "2026-10-27", "key": "k2", "headline": "SpaceX leases GPUs", "view": 12, "view_name": "The AI debt",
                 "position": "We think it is debt.", "changes_our_mind": "", "check": "2027-10-01", "status": "open"}]
        houseviews._save(root, rows)
        later = houseviews.later_stories(root, rows[0])
        self.assertEqual([x["headline"] for x in later], ["Anthropic S-1 shows Q3 revenue slip"])
        done = houseviews.score_due(root, Fake({"verdict": "wrong", "why": "Q3 revenue fell [1].", "refs": [1]}),
                                    "sys", "2027-01-25", log=lambda *a: None)
        self.assertEqual([r["key"] for r in done], ["k1"])
        led = {r["key"]: r for r in houseviews.load_ledger(root)}
        self.assertEqual(led["k1"]["status"], "scored")
        self.assertEqual(led["k1"]["history"][0]["evidence"][0]["day"], "2026-11-20")
        self.assertEqual(led["k2"]["status"], "open")
        page = site.calls_page(root, {})
        self.assertIn("1 wrong", page)
        self.assertIn("We think it is debt.", page)

    def test_too_early_gets_more_time(self):
        root = root_with()
        houseviews._save(root, [{"day": "2026-10-27", "key": "k", "headline": "x y z", "check": "2027-01-25",
                                 "status": "open", "position": "p"}])
        houseviews.score_due(root, Fake({"verdict": "too early", "why": "nothing yet"}), "s", "2027-01-25", log=lambda *a: None)
        r = houseviews.load_ledger(root)[0]
        self.assertEqual((r["status"], r["check"]), ("open", "2027-04-25"))


class MergedTop(unittest.TestCase):
    def edition(self, top_format):
        recs = [rec(1, imp=5), rec(2, imp=5, person="Q")]
        by_id = {r["id"]: r for r in recs}
        stories = editorial.build_stories([{"ids": [r["id"]], "headline": None} for r in recs], by_id)
        sel = {"must": stories, "worth": [], "brief": [], "more": 0}
        out = {"day_in_brief": "Two threads today. A question worth asking in diligence this week: who holds the lease?",
               "top_of_mind": [{"lead": f"Lead {i}", "text": f"Text {i}.", "refs": [1]} for i in range(1, 7)]}
        cfg = {"analysis": {"top_format": top_format, "top_of_mind": 4}}
        ed, _, _ = editorial.run_editorial(Fake(out), sel, "sys", LOG, cfg, [], [])
        return editorial.render("2026-10-27", sel, ed, {"models": "m"})[0], cfg

    def test_merged_render_and_readers(self):
        md, cfg = self.edition("merged")
        self.assertIn("## Today in 30 seconds", md)
        self.assertNotIn("The day in brief", md)
        self.assertNotIn("## Top of mind", md)
        self.assertEqual(md.count("- **Lead "), 5)
        self.assertIn("**A question worth asking in diligence this week:** who holds the lease?", md)
        b = audio.parse_briefing(md)
        self.assertEqual(len(b["top"]), 5)
        self.assertTrue(audio.diligence_question(b["day_in_brief"]).endswith("who holds the lease?"))
        m = mailer.parse(md)
        self.assertTrue(m["merged"])
        self.assertEqual(len(m["top"]), 5)
        out, notes = consistency.check_briefing(md, "")
        self.assertIn("## Today in 30 seconds", out)
        self.assertIn("A question worth asking", out)
        self.assertIn("Today in 30 seconds", editorial.editorial_prompt(editorial.prompt("editorial")[0], [], cfg, []))

    def test_separate_is_unchanged(self):
        md, _ = self.edition("separate")
        self.assertIn("**The day in brief.** Two threads today.", md)
        self.assertEqual(md.count("- **Lead "), 4)
        self.assertEqual(textutil.legacy_top(md), md)


if __name__ == "__main__":
    unittest.main()
