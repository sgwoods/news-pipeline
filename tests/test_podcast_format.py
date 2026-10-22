import logging
import unittest

from pipeline import audio

MD = """# AI Briefing · Wednesday, October 14, 2026

**The day in brief.** Two threads. Labs lose money. Diligence ask this week: gross versus net revenue.

## Must read

""" + "".join(f"""### {i}. Story {i} headline
**Reuters** · report · [source](https://r.com/{i})

- **What happened:** Thing {i} happened.
- **Evidence check:** Holds. Sourced.
- **Our read:** We would ask about margins.

""" for i in range(1, 6)) + """## Worth knowing

""" + "".join(f"- **{i}. Hit {i}.** Small thing {i}. ([x](https://x.com/{i}))\n" for i in range(6, 11)) + """
## Open questions

- **Will OpenAI disclose net revenue?** Matters. *Settled by: filings.*
"""

CFG = {"audio": {"format": "spec", "max_minutes": 10, "max_stories": 4, "max_quick_hits": 3}}


class Fake:
    label = "fake"

    def __init__(self, words=60):
        self.words, self.prompts = words, []

    def complete_json(self, system, user, retries=1, max_tokens=None):
        self.prompts.append(user)
        if "<section id=" in user:
            import re
            ids = re.findall(r'<section id="(s\d+)"', user)
            return {"sections": [{"id": i, "text": "Plain words here. " * (self.words // 3)} for i in ids]}
        return {"text": "Plain words here."}


class PodcastFormat(unittest.TestCase):
    def test_shape(self):
        parts, _, errs = audio.build_script(Fake(), MD, "sys", CFG, logging.getLogger("t"))
        names = [n for n, _ in parts]
        self.assertEqual(names, ["Intro", "Story 1", "Story 2", "Story 3", "Story 4", "Quick hits", "Close", "Outro"])
        self.assertTrue(parts[0][1].startswith("This is the AI Briefing for Wednesday, October 14."))

    def test_close_gets_diligence_and_open_question(self):
        b = audio.parse_briefing(MD)
        plan = dict((n, s) for n, s, *_ in audio._plan(b, CFG))
        self.assertIn("gross versus net revenue", plan["Close"])
        self.assertIn("Will OpenAI disclose net revenue?", plan["Close"])
        self.assertEqual(plan["Quick hits"].count("\n"), 2)                  # three quick hits

    def test_hard_cap_drops_quick_hits_then_last_story(self):
        parts, _, errs = audio.build_script(Fake(words=300), MD, "sys", CFG, logging.getLogger("t"))
        names = [n for n, _ in parts]
        self.assertNotIn("Quick hits", names)
        self.assertLessEqual(sum(len(t.split()) for _, t in parts), 10 * audio.WPM)
        self.assertTrue(any("cap" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
