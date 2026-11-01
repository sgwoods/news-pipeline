import json
import tempfile
import unittest
from pathlib import Path

from pipeline import chart, editorial, mailer


def st(title, imp=3, score=2.5, ids=("1",)):
    return {"headline": title, "ids": list(ids), "names": ["A"], "score": score,
            "lead": {"id": ids[0], "title": title, "importance": imp}, "records": [{"id": ids[0], "url": "https://ex.com/a"}],
            "evidence": {"primary": 0, "reports": 1, "tested": 0, "grounded": True}}


class MoneyTest(unittest.TestCase):
    def test_is_money(self):
        self.assertTrue(editorial.is_money(st("Baseten raises $2B at a $30B valuation")))
        self.assertTrue(editorial.is_money(st("Guidewire acquires Hyperexponential for $1.7B")))
        self.assertFalse(editorial.is_money(st("Mistral releases a 1T-parameter open model")))
        self.assertFalse(editorial.is_money(st("Startup raises a question about safety")))

    def test_select_routes_deals_to_money(self):
        sel = editorial.select([st("Arca raises $48.5M for AI wealth management"), st("A minor blog post")], {})
        self.assertEqual([s["headline"] for s in sel["money"]], ["Arca raises $48.5M for AI wealth management"])
        self.assertEqual([s["headline"] for s in sel["brief"]], ["A minor blog post"])

    def test_email_parses_money(self):
        md = "# T\n\n## Money\n\n- **Arca raises $48.5M.** Wealth agents. ([x](https://ex.com))\n\n---\n"
        self.assertEqual(len(mailer.parse(md)["money"]), 1)


class ChartTest(unittest.TestCase):
    TEXT = {1: "Alphabet expects up to $205 billion, Amazon $220 billion and Meta as much as $145 billion in capex."}

    def test_values_must_be_in_sources(self):
        good = {"story": 1, "title": "Capex guidance", "unit": "$B", "bars": [
            {"label": "Alphabet", "value": 205}, {"label": "Amazon", "value": 220}, {"label": "Meta", "value": 145}]}
        self.assertEqual(chart.check(good, self.TEXT), "")
        bad = json.loads(json.dumps(good))
        bad["bars"][2]["value"] = 150
        self.assertIn("Meta", chart.check(bad, self.TEXT))
        self.assertIn("no story", chart.check({"story": 0}, self.TEXT))

    def test_make_saves_and_renders(self):
        class LLM:
            def complete_json(self, s, u, max_tokens=None):
                return {"story": 1, "title": "Capex guidance", "unit": "$B", "bars": [
                    {"label": "Alphabet", "value": 205}, {"label": "Amazon", "value": 220}, {"label": "Meta", "value": 145}]}
        root = Path(tempfile.mkdtemp())
        c = chart.make(root, "2026-11-02", [{"n": 1, "headline": "Big Tech capex", "what": ""}], self.TEXT, LLM(), lambda *a: None)
        self.assertEqual(chart.load(root, "2026-11-02")["story"], 1)
        h = chart.html(c)
        self.assertIn("$220B", h)
        self.assertIn("width:100%", h)
        m = mailer.render("2026-11-02", "# T\n\n## Must read\n\n### 1. Big Tech capex\n**X** · [source](https://ex.com)\n\n- **What happened:** Capex.\n\n---\n",
                          {"publish": {"site_url": "https://ex.com/"}}, chart=c)
        self.assertIn("Capex guidance", m["html"])


if __name__ == "__main__":
    unittest.main()


class ChartStoryNumber(unittest.TestCase):
    def test_story_as_string_is_accepted(self):
        from pipeline import chart
        c = {"story": "1", "bars": [{"label": "A", "value": 38}, {"label": "B", "value": 30}, {"label": "C", "value": 12}]}
        self.assertEqual(chart.check(c, {1: "A raised $38 billion, B 30 billion, C 12 billion"}), "")

    def test_story_zero_says_why(self):
        from pipeline import chart
        self.assertIn("comparable", chart.check({"story": 0}, {1: "x"}))


class GiftTokenStripped(unittest.TestCase):
    def test_wapo_gift_token_removed(self):
        from pipeline.textutil import clean_url
        u = clean_url("https://www.washingtonpost.com/technology/2026/10/30/x/?pwapi_token=eyJ0eXAi.eyJyZWFz.sig&itid=gfta")
        self.assertNotIn("token", u)
        self.assertTrue(u.startswith("https://www.washingtonpost.com/technology/2026/10/30/x/"))

