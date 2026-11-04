"""Fact checks in the takes email (2026-11-04): options and a recommendation per item, chosen in the takes reply,
applied before the edition is published."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import factopts, takes

DAY = "2026-11-04"
MD = """# AI Briefing

## Top of mind

- **Fal doubles to $16B.** A $1.3B Bessemer-led round prices Fal at about 20x revenue. [4](https://t.example/fal)
- **DeepSeek raises.** DeepSeek raised $15.9B. Seven rounds took 40% of October's $59B. [1](https://c.example/d)
- **Old line.** Something vague happened. [2](https://x.example/o)
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "briefings" / f"{DAY}.md").write_text(MD)
        a = self.root / "data" / "audit"
        a.mkdir(parents=True)
        fixed = "- **Fal doubles to $16B.** A $1.3B Bessemer-led round prices Fal at about 20x revenue. [4](https://t.example/fal)"
        (a / f"{DAY}-presend.json").write_text(json.dumps({
            "checked": 9, "fixes": [{"before": fixed.replace("round", "Series F round"), "after": fixed, "why": "no series in the source"}],
            "held": [{"claim": "Old line. Something vague happened.", "verdict": "rewrite not confirmed", "why": "second check: supported",
                      "before_md": "- **Old line.** Something vague happened. [2](https://x.example/o)",
                      "proposed_md": "- **Old line.** Something specific happened. [2](https://x.example/o)", "recheck": ["supported"]}]}))
        (a / f"{DAY}.json").write_text(json.dumps({"issues": [
            {"claim": "Seven rounds took 40% of October's $59B.", "verdict": "contradicted", "why": "it was 30%"}]}))


class Items(Base):
    def test_items_options_and_recommendations(self):
        its = factopts.items(self.root, DAY)
        self.assertEqual([i["id"] for i in its], ["F1", "F2", "F3"])
        self.assertEqual((its[0]["kind"], its[0]["rec"]), ("fixed", "A"))
        self.assertEqual(its[1]["rec"], "B")                                   # the proposed rewrite re-checked
        self.assertEqual(its[2]["rec"], "C")                                   # contradicted
        lines, html = factopts.section(its)
        text = "\n".join(lines)
        self.assertIn("F2 · Edition", text)
        self.assertIn("→ I recommend B", text)
        self.assertIn("No answer = my recommendation", text)
        self.assertIn("Fact checks", html)

    def test_email_puts_fact_checks_at_the_bottom(self):
        orig = takes._sections
        takes._sections = lambda root, cfg, day: [("1", "Must read", "<p>x</p>", ["1 · Must read"])]
        try:
            m = takes.build_email(self.root, {}, DAY, review=False)
        finally:
            takes._sections = orig
        t = m["text"]
        self.assertLess(t.index("1 · Must read"), t.index("FACT CHECKS"))     # after the sections
        self.assertIn("3 fact check(s) at the bottom", t.split("1 · Must read")[0])


class Replies(Base):
    def test_parse_keeps_choices_apart_from_takes(self):
        r = takes.parse("1: Margins matter more than the headline.\nF2: b\nF3 C\ndone")
        self.assertEqual(r["takes"], {"1": "Margins matter more than the headline."})
        self.assertEqual(r["facts"], {"F2": "B", "F3": "C"})
        self.assertTrue(r["done"])

    def test_apply_steven_and_recommendations(self):
        out = factopts.apply(self.root, {}, DAY, {"F1": "B", "F3": "A"}, log=lambda *a: None)
        md = (self.root / "briefings" / f"{DAY}.md").read_text()
        self.assertIn("Series F round", md)                                    # F1 B: back to the original
        self.assertIn("Something specific happened", md)                       # F2: the recommendation (B)
        self.assertIn("Seven rounds took 40%", md)                             # F3 A: kept, Steven's choice
        self.assertTrue(out["edition_changed"])
        by = {r["id"]: r["by"] for r in out["results"]}
        self.assertEqual(by, {"F1": "Steven", "F2": "recommendation", "F3": "Steven"})

    def test_cut_a_sentence(self):
        factopts.apply(self.root, {}, DAY, {"F1": "A", "F2": "A"}, log=lambda *a: None)
        md = (self.root / "briefings" / f"{DAY}.md").read_text()
        self.assertNotIn("Seven rounds took", md)                              # F3: the recommendation (C)
        self.assertIn("DeepSeek raised $15.9B.", md)


if __name__ == "__main__":
    unittest.main()
