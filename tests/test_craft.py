"""Craft metrics (2026-11-03): paragraphing, long sentences, repeated phrases, pace; and the audio symbol on posts."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import craft, critic

PARA = ("Nvidia is reportedly in talks to guarantee credit for a large data center. The deal would shift risk "
        "onto the chip maker. Investors should watch the terms closely before drawing conclusions about demand.")


class Measure(unittest.TestCase):
    def test_paragraphs_and_long_sentences(self):
        wall = " ".join([PARA] * 8)                                  # one 260-word paragraph
        m = craft.measure("# Title\n\n" + wall + "\n\n" + PARA)
        self.assertGreater(m["long_para_pct"], 0)
        ramble = "This " + "and that " * 30 + "ends here. " + PARA
        self.assertGreater(craft.measure(ramble)["long_sent_pct"], 0)

    def test_repeats_found_but_not_citations_or_title(self):
        tic = "The labs are racing for compute and capital. " * 4
        text = "# The Third Scaling Law\n\n" + (PARA + " [thein.fo via The Information](https://thein.fo/x) ") * 3 \
            + "\n\n" + tic + "\n\nThe third scaling law matters. The third scaling law costs. The third scaling law wins."
        reps = [g for g, _ in craft.repeats(text)]
        self.assertTrue(any("racing for compute" in g for g in reps))
        self.assertFalse(any("information" in g or "via" in g for g in reps))
        self.assertFalse(any(g == "the third scaling law" for g in reps))

    def test_checks_flag_pace_and_repeats(self):
        m = {"briefing": craft.measure(PARA * 3 + " Same words again here. " * 4), "script": {"pace_wpm": 130, "repeats": 0}}
        ks = {k: ok for k, _, ok, _ in craft.checks(m)}
        self.assertFalse(ks["pace_podcast"])
        self.assertFalse(ks["repeats_briefing"])

    def test_field_measures_bench_and_ours(self):
        import datetime as dt
        root = Path(tempfile.mkdtemp())
        day = dt.date.today().isoformat()
        (root / "data" / "raw" / day).mkdir(parents=True)
        (root / "data" / "raw" / day / "items.jsonl").write_text(json.dumps(
            {"source_kind": "email", "person": "The Rundown AI", "text": "\n\n".join([PARA] * 6)}) + "\n")
        (root / "briefings").mkdir()
        (root / "briefings" / f"{day}.md").write_text("# AI Briefing\n\n" + "\n\n".join([PARA] * 6))
        f = craft.field(root, 3)
        self.assertEqual(f["The Rundown AI"]["issues"], 1)
        self.assertIn(craft.OURS, f)


class Reports(unittest.TestCase):
    def test_critic_craft_section(self):
        week = {"shows": [{"name": "X", "scores": {}, "craft": {k: 7 for k, _ in critic.CRAFT}}],
                "ours": {"scores": {}, "craft": {k: 6 for k, _ in critic.CRAFT}},
                "measured": {critic.OURS: {"para_words": 18, "long_sent_pct": 19}}}
        h = critic.chart_craft(week)
        self.assertIn("Focus, no rambling", h)
        self.assertIn("words/para", h)
        self.assertEqual(critic.chart_craft({"shows": [], "ours": {}}), "")

    def test_slack_post_has_headphones_for_briefing_and_deep_dive(self):
        from pipeline import slackpost
        src = Path(slackpost.__file__).read_text("utf-8")
        self.assertIn(":headphones: <{base}/{day}/#listen|Listen to the briefing>", src)
        self.assertIn(":headphones: <{dd_url}|Listen to the deep dive>", src)


if __name__ == "__main__":
    unittest.main()
