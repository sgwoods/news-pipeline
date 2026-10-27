"""House views (Steven, 2026-10-27): Our read takes a position under a named view, the lead gets the case for and
against, and every position is logged for scoring."""
import json
import logging
import tempfile
import unittest
from pathlib import Path

from pipeline import audio, editorial, houseviews

from tests.test_editorial import Fake, rec

LOG = logging.getLogger("t")
TEXT = """# house_views.md

## 1. Measurable value beats usage
AI is worth what it moves on a customer's P&L. *Apply:* ask which line moved. *Changes our mind:* audited numbers.
*From:* perspective.md.

## 7. Bubbles and real platforms coexist **[suggested]**
A capital cycle can overbuild. *Apply:* follow capex. *Changes our mind:* capex paid back by customers.

## Steven's theses (added 2026-10-27)
Forecasts.

## 12. The AI debt comes due
The debt is likely to cause a crisis. *Apply:* follow financing. *Changes our mind:* calm credit markets.
*Check:* 2027-10. *Builds on:* view 7.
*In Steven's words:* "It is likely that the enormous debt created by AI acceleration efforts will cause an economic crisis"

## Rules for using these
- Every Must read takes a position.
"""


def selection():
    recs = [rec(1, imp=5), rec(2, imp=5, person="Q")]
    by_id = {r["id"]: r for r in recs}
    stories = editorial.build_stories([{"ids": [r["id"]], "headline": None} for r in recs], by_id)
    return {"must": stories, "worth": [], "brief": [], "more": 0}


class HouseViews(unittest.TestCase):
    def test_parse(self):
        vs = houseviews.parse(TEXT)
        self.assertEqual([v.n for v in vs], [1, 7, 12])
        self.assertEqual(vs[1].name, "Bubbles and real platforms coexist")
        self.assertEqual(vs[0].changes, "audited numbers.")
        self.assertFalse(vs[0].thesis)
        self.assertEqual(vs[2].check, "2027-10")
        self.assertTrue(vs[2].words.startswith("It is likely"))
        self.assertNotIn("Rules", vs[2].view + vs[2].apply)
        block = houseviews.prompt_block(vs)
        self.assertIn("[V12] The AI debt comes due.", block)
        self.assertNotIn("enormous debt", block)          # his verbatim words never go to the model as quotable text

    def test_our_read_names_its_view_and_lead_gets_the_case(self):
        sel = selection()
        n = len(sel["must"])
        out = {"day_in_brief": "B.", "top_of_mind": [],
               "editor_view": {"1": {"text": "We think this is debt moved off the balance sheet.", "view": "V12",
                                     "changes": "revenue paying for it"},
                               "2": {"text": "We think usage is not value.", "view": 99}},
               "lead_case": {"for": "Diversified funding.", "against": "Still a lease.", "deciding": "Who holds it?",
                             "lean": "Against, under view 12."}}
        ed, _, errs = editorial.run_editorial(Fake(out), sel, "sys", LOG, {}, [], houseviews.parse(TEXT))
        self.assertEqual(errs, [])
        self.assertEqual(n, 2)
        lead = sel["must"][0]
        self.assertEqual(lead["house_view"], 12)
        self.assertEqual(lead["changes_our_mind"], "revenue paying for it")
        self.assertNotIn("house_view", sel["must"][1])          # an unknown view number is dropped, the read kept
        self.assertEqual(sel["must"][1]["editor_view"], "We think usage is not value.")
        md, _ = editorial.render("2026-10-27", sel, ed, {"models": "m"})
        self.assertIn("**Our read:** We think this is debt moved off the balance sheet. *(House view: The AI debt comes due)*", md)
        for label in ("The case for", "The case against", "The deciding question", "Our lean"):
            self.assertIn(f"- **{label}:**", md)
        spoken = audio.parse_briefing(md)["stories"][0]
        self.assertEqual(spoken["Our read"], "We think this is debt moved off the balance sheet.")

    def test_without_views_nothing_changes(self):
        sel = selection()
        out = {"editor_view": {"1": "We think it matters."}, "lead_case": {"for": "a", "against": "b", "deciding": "c", "lean": "d"}}
        editorial.run_editorial(Fake(out), sel, "sys", LOG, {}, [], [])
        self.assertEqual(sel["must"][0]["editor_view"], "We think it matters.")
        self.assertNotIn("lead_case", sel["must"][0])
        tmpl, _ = editorial.prompt("editorial")
        p = editorial.editorial_prompt(tmpl, ["[1] x"], {}, [], [])
        self.assertNotIn("HOUSE VIEWS", p)
        self.assertNotIn("{{", p)

    def test_view_numbers_never_reach_readers(self):
        u = editorial._unnumber
        self.assertEqual(u("Under V7, we lean that the revenue is real."), "We lean that the revenue is real.")
        self.assertEqual(u("We lean against (V12) on the lease."), "We lean against on the lease.")
        self.assertEqual(u("This fits V4 well."), "This fits our house view well.")
        self.assertEqual(u("We think GPT-5 and Vision Pro matter."), "We think GPT-5 and Vision Pro matter.")

    def test_ledger(self):
        root = Path(tempfile.mkdtemp())
        vs = houseviews.parse(TEXT)
        sel = selection()
        sel["must"][0].update({"editor_view": "We think so.", "house_view": 12, "changes_our_mind": "calm markets"})
        self.assertEqual(houseviews.log_positions(root, "2026-10-27", sel, vs), 1)
        self.assertEqual(houseviews.log_positions(root, "2026-10-27", sel, vs), 1)     # a rerun replaces the day
        rows = [json.loads(x) for x in (root / houseviews.LEDGER).read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["check"], "2027-10-01")
        self.assertEqual(rows[0]["view_name"], "The AI debt comes due")
        sel["must"][0]["house_view"] = 1
        houseviews.log_positions(root, "2026-10-28", sel, vs)
        rows = [json.loads(x) for x in (root / houseviews.LEDGER).read_text().splitlines()]
        self.assertEqual(rows[1]["check"], "2027-01-26")                                 # 90 days on, no thesis date
        self.assertEqual([r["day"] for r in houseviews.due(root, "2027-01-26")], ["2026-10-28"])


if __name__ == "__main__":
    unittest.main()
