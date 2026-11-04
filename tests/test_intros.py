"""Who they are (2026-11-04): first mention gets an intro, a company back after a while gets a short reminder that
builds on what we said before, and a company covered recently gets nothing."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import intros

MD = """# AI Briefing · Wednesday

## Must read

### 1. Fal doubles valuation to $16B after $1.3B Bessemer-led funding
**TechCrunch** · report · [source](https://t.example/fal) · 2026-11-04

- **What happened:** Fal raised $1.3B led by Bessemer at a $16B valuation.

## Worth knowing

- **2. Acme Robotics opens a Toronto lab.** It will hire 40 people. ([TC](https://t.example/a))

## In brief

- Zeta Labs ships an agent SDK ([X](https://t.example/z))
- Mistral adds a reranker ([X](https://t.example/c))
"""
FAL = "Fal, which runs a hosted platform for generative image and video models, raised $1.3B at a $16B valuation."
LINE = "Fal runs a hosted platform for image and video models; it competes with Replicate and serves labs like Black Forest Labs."


class Modes(unittest.TestCase):
    def test_mode(self):
        self.assertEqual(intros.mode("Fal", "Falcon news", ""), "intro")
        self.assertEqual(intros.mode("Fal", "Fal raised a seed round", ""), "reminder")
        self.assertEqual(intros.mode("Fal", "Fal raised a seed round", "Fal again"), "")
        self.assertEqual(intros.mode("Nvidia", "", ""), "")

    def test_check_by_kind(self):
        self.assertEqual(intros.check(LINE, FAL, "intro"), "")
        self.assertEqual(intros.check(LINE + " It also offers hosted fine-tuning for teams.", FAL, "reminder"), "too long")
        self.assertEqual(intros.check("Fal hosts image and video models for developers.", FAL, "reminder"), "")
        self.assertIn("number", intros.check("Fal has 2,000 customers.", FAL))

    def test_insert_each_section(self):
        md = intros.insert(MD, "must", "Fal doubles valuation to $16B after $1.3B Bessemer-led funding", LINE)
        self.assertIn("- **Who they are:** " + LINE + "\n- **What happened:**", md)
        md = intros.insert(md, "worth", "Acme Robotics opens a Toronto lab.", "Acme builds warehouse robots.")
        self.assertIn("**2. Acme Robotics opens a Toronto lab.** *Acme builds warehouse robots.* It will hire", md)
        md = intros.insert(md, "brief", "Zeta Labs ships an agent SDK", "Zeta Labs makes developer tools.")
        self.assertIn("- Zeta Labs ships an agent SDK. *Zeta Labs makes developer tools.* ([X]", md)


class Apply(unittest.TestCase):
    def test_intro_reminder_skip(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-09-01.md").write_text("Acme Robotics was in the news.")      # long ago
        (root / "briefings" / "2026-11-02.md").write_text("Mistral raised a round.")              # recent
        (root / intros.MEMORY).parent.mkdir(parents=True)
        (root / intros.MEMORY).write_text(json.dumps({"acme robotics": {"name": "Acme Robotics", "first": "2026-09-01",
                                                      "lines": [{"day": "2026-09-01", "kind": "intro", "line": "Acme builds warehouse robots."}]}}))
        sel = {"must": [{"headline": "Fal doubles valuation to $16B after $1.3B Bessemer-led funding", "ids": ["f"]}],
               "worth": [{"headline": "Acme Robotics opens a Toronto lab", "ids": ["a"]}],
               "brief": [{"headline": "Zeta Labs ships an agent SDK", "ids": ["z"]},
                         {"headline": "Mistral adds a reranker", "ids": ["c"]}]}
        import pipeline.stages as stages
        o_ask, o_raw = stages._ask, stages.raw_items
        stages.raw_items = lambda root, ids, days=21: {"f": {"title": "", "text": FAL}, "a": {"text": "x"},
                                                       "z": {"text": "y"}, "c": {"text": "c"}}
        prompts = []

        def ask(llm, system, prompt, n):
            prompts.append(prompt)
            if "COMPANIES:" not in prompt:
                return {"items": [{"n": 1, "company": "Fal"}, {"n": 2, "company": "Acme Robotics"},
                                  {"n": 3, "company": "Zeta Labs"}, {"n": 4, "company": "Mistral"}]}
            return {"items": [{"n": 1, "line": LINE}, {"n": 2, "line": "Acme makes warehouse robots, now hiring in Toronto."},
                              {"n": 3, "line": "Zeta Labs has 900 clients."}]}
        stages._ask = ask
        try:
            md, st = intros.apply(root, "2026-11-04", MD, sel, object(), log=lambda *a: None)
        finally:
            stages._ask, stages.raw_items = o_ask, o_raw
        self.assertEqual(st["intro"], ["Fal"])
        self.assertEqual(st["reminder"], ["Acme Robotics"])
        self.assertNotIn("Mistral (", prompts[1])                       # covered two days ago: no line asked for
        self.assertIn("our earlier lines: Acme builds warehouse robots.", prompts[1])
        self.assertTrue(any("Zeta Labs" in r for r in st["rejected"]))  # its number isn't in the sources
        mem = json.loads((root / intros.MEMORY).read_text())
        self.assertEqual(mem["acme robotics"]["lines"][-1]["kind"], "reminder")
        self.assertEqual(mem["fal"]["first"], "2026-11-04")


if __name__ == "__main__":
    unittest.main()
