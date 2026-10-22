import logging
import unittest

from pipeline import audio

MD = """# AI Briefing · Monday, October 5, 2026

**The day in brief.** Agent security went legal.

## Top of mind

- **Lead.** Text. [1](https://x.com/a)

## Must read

### 1. OpenAI pauses training
**The Batch · Gary Marcus** · 2 sources · [source](https://x.com/a)

- **What happened:** OpenAI paused training ([The Batch](https://x.com/a)).
- **Critical pass:** Pause is reported; details thin.
- **Editor's view:** Ask about containment.
- **Sources:** [The Batch: x](https://x.com/a) · [Marcus: y](https://x.com/b)

## Worth knowing

- **2. DeepSeek cuts prices.** Half price off-peak. ([The Batch (DeepLearning.AI)](https://x.com/c), [Willison](https://x.com/d))
"""


class Fake:
    label = "fake"

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user, retries=1, max_tokens=None):
        self.prompts.append(user)
        return {"text": "Spoken text. See https://x.com/a for more."}


class TestAudio(unittest.TestCase):
    def test_parse(self):
        b = audio.parse_briefing(MD)
        self.assertEqual(b["title"], "AI Briefing · Monday, October 5, 2026")
        self.assertEqual(b["day_in_brief"], "Agent security went legal.")
        s = b["stories"][0]
        self.assertEqual(s["headline"], "OpenAI pauses training")
        self.assertEqual(s["What happened"], "OpenAI paused training (The Batch).")
        self.assertNotIn("Sources", s)
        self.assertEqual(b["worth"], ["DeepSeek cuts prices. Half price off-peak."])

    def test_script_sections_and_no_urls(self):
        llm = Fake()
        parts, _, errs = audio.build_script(llm, MD, "sys", {"audio": {"minutes": 5}}, logging.getLogger("t"))
        self.assertEqual([p[0] for p in parts], ["Intro", "Story 1", "Worth knowing", "Outro"])
        self.assertTrue(all("http" not in t for _, t in parts))
        # one call writes the whole episode; this fake returns no sections, so each section is then written alone
        self.assertIn("<section id=", llm.prompts[0])
        self.assertIn("Critical pass", llm.prompts[0])
        self.assertTrue(all("https://" not in p for p in llm.prompts))
        self.assertTrue(parts[0][1].startswith("This is the AI Briefing for Monday, October 5."))
        md = audio.script_markdown("T", parts, {"voice": "kokoro:af_heart"})
        self.assertIn("## Story 1", md)


if __name__ == "__main__":
    unittest.main()
