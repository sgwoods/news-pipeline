"""The critic's first batch (2026-10-24 review): source gate, verdict labels, early-stage line, deep-dive alignment,
cold open, short segments for continuing and deep-dive stories, pronunciation fixes."""
import unittest

from pipeline import audio, consistency, editorial, speech


def story(url, title="Corvane raises $550M", text="Corvane raised $550M.", score=5):
    lead = {"id": "a", "url": url, "title": title, "text": text, "importance": 3}
    return {"key": "k", "ids": ["a"], "names": ["Example News"], "lead": lead, "records": [lead], "score": score,
            "evidence": {"grounded": True}, "headline": title}


class SourceGate(unittest.TestCase):
    def test_homepage_and_sponsored_leads_cannot_be_must_reads(self):
        self.assertIn("homepage", editorial.weak_lead(story("https://www.example.com/")))
        self.assertIn("sponsored", editorial.weak_lead(story("https://ex.com/webinar/x", text="Sponsored by Vecna Robotics")))
        self.assertEqual(editorial.weak_lead(story("https://ex.com/news/corvane-raises")), "")
        sel = editorial.select([story("https://www.example.com/")], {})
        self.assertEqual(sel["must"], [])
        self.assertEqual(len(sel["worth"]), 1)


class Verdicts(unittest.TestCase):
    def test_holds_with_unverified_evidence_becomes_unverified(self):
        s = {"critical_pass": "Holds. Self-reported benchmarks unverified; no independent runs."}
        self.assertTrue(editorial.critical_line(s, {}).startswith("Unverified."))
        s = {"critical_pass": "Holds. Two independent labs reproduced it."}
        self.assertTrue(editorial.critical_line(s, {}).startswith("Holds."))
        s = {"critical_pass": "Overstated. Self-reported."}
        self.assertTrue(editorial.critical_line(s, {}).startswith("Overstated."))


class EarlyStage(unittest.TestCase):
    def test_rendered_after_our_read(self):
        s = story("https://ex.com/news/a")
        s.update({"what_happened": "Corvane raised $550M.", "editor_view": "Margins matter.",
                  "early_stage": "Seed-stage legal tools now compete with a funded incumbent."})
        md, _ = editorial.render("2026-10-26", {"must": [s], "worth": [], "brief": [], "more": 0}, {}, {})
        self.assertIn("- **Our read:** Margins matter.\n- **For early-stage:** Seed-stage legal tools", md)


MD = """# AI Briefing · Monday

**The day in brief.** Security leads. Wiz found PHP flaws with models that remain unverified. Legora raised money with no disclosed ARR.

## Top of mind

- **PHP flaws.** The models Wiz used remain unverified.
- **Legora raises.** Legora raised $550M with no disclosed ARR.

## Must read

### 1. AI-found PHP flaws hit 70% of sites
**Example News** · report · [source](https://ex.com/php)

- **What happened:** Wiz Research found critical PHP flaws. Patches followed weeks later.
- **Evidence check:** Holds. Reported by two outlets.
- **Our read:** The bottleneck is patching.
- **Sources:** [Ex](https://ex.com/php)

### 2. Kimi pricing
**Other News** · report · [source](https://ex.com/kimi)

- **What happened:** Moonshot cut Kimi prices.
- **Our read:** Cheap tokens again.
"""
DD_BODY = ("Wiz Research named Gemini 4 Argon and GPT-5.6 Sol as the models it used to find the PHP flaws. "
           "Legora's ARR stands at more than $200M, the company said.")


class AlignDeepDive(unittest.TestCase):
    def setUp(self):
        self.md, self.notes, self.flags = consistency.align_deepdive(
            MD, "AI Finds the Bugs. Who Ships the Patches?", DD_BODY,
            "Wiz Research used rentable models to find critical PHP flaws; patching is the bottleneck.")

    def test_story_the_deep_dive_covers_becomes_a_pointer(self):
        block = self.md.split("### 1.")[1].split("### 2.")[0]
        self.assertIn("- **Today's deep dive:** \"AI Finds the Bugs. Who Ships the Patches?\" covers this story", block)
        self.assertIn("- **What happened:** Wiz Research found critical PHP flaws.", block)
        self.assertNotIn("Our read", block)
        self.assertIn("- **Sources:**", block)
        self.assertIn("### 2. Kimi pricing", self.md)
        self.assertIn("- **Our read:** Cheap tokens again.", self.md)        # other stories untouched

    def test_not_disclosed_line_the_deep_dive_answers_is_dropped_from_the_header(self):
        self.assertNotIn("no disclosed ARR", self.md.split("## Must read")[0])
        self.assertTrue(any("ARR wasn't disclosed" in n for n in self.notes))

    def test_unverified_claim_the_deep_dive_settles_is_flagged(self):
        self.assertTrue(any("unsettled" in f for f in self.flags))

    def test_unrelated_deep_dive_changes_nothing(self):
        md, notes, _ = consistency.align_deepdive(MD, "Convertible notes explained", "A convertible note is debt.",
                                                  "Anthropic's paper loss")
        self.assertEqual(md, MD)
        self.assertEqual(notes, [])


class Audio(unittest.TestCase):
    def test_cold_open_is_the_lead_storys_sharpest_line(self):
        md = MD.replace("The bottleneck is patching.", "The bottleneck is patching, not finding bugs, and that favours "
                                                       "fix-automation startups.")
        self.assertEqual(audio.cold_open(md), "The bottleneck is patching, not finding bugs, and that favours "
                                              "fix-automation startups.")

    def test_short_segments_for_deep_dive_and_continuing_stories(self):
        md, _, _ = consistency.align_deepdive(MD, "AI Finds the Bugs", DD_BODY, "Wiz Research PHP flaws patching")
        md = md.replace("### 2. Kimi pricing\n**Other News** · report · [source](https://ex.com/kimi)\n",
                        "### 2. Kimi pricing\n**Other News** · report · [source](https://ex.com/kimi)\n\n"
                        "*Developing story · day 3 · first in the briefing Oct 22*\n")
        plan = audio._plan_spec(audio.parse_briefing(md), {"audio": {}})
        lengths = {name: length for name, _, length, _ in plan}
        self.assertEqual(lengths["Story 1"], "About 50 words, never more than 70.")
        self.assertEqual(lengths["Story 2"], "About 120 words, never more than 140.")


class Pronunciation(unittest.TestCase):
    def test_letter_number_models_and_stacked_punctuation(self):
        self.assertEqual(speech.expand("Kimi K3.1 Pro"), "Kimi K three point one Pro")
        self.assertEqual(speech.expand("the Patches?."), "the Patches?")
        self.assertEqual(speech.expand("Q3 revenue"), "Q three revenue")

    def test_lint_lists_tokens_the_table_lacks(self):
        self.assertEqual(speech.lint("HBM3e and NVIDIA and OpenAI", {"NVIDIA": "Nvidia"}), ["HBM3e"])


if __name__ == "__main__":
    unittest.main()
