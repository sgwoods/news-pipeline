import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import deepdive, editorial
from pipeline.links import strip_disclosures


def story(title, ids, names=("A",), score=4, ev=None, topics=()):
    return {"headline": title, "ids": list(ids), "names": list(names), "score": score,
            "lead": {"id": ids[0], "title": title, "topics": list(topics)}, "records": [{"id": i} for i in ids],
            "evidence": ev or {"primary": 0, "reports": 1, "tested": 0}}


class VerdictTest(unittest.TestCase):
    def test_unverified_refined(self):
        self.assertEqual(editorial.refine_unverified("Unverified", story("x", ["1"], ev={"primary": 0, "reports": 2})), "Reported")
        self.assertEqual(editorial.refine_unverified("Unverified", story("x", ["1"], ev={"primary": 1, "reports": 0})), "Self-reported")
        self.assertEqual(editorial.refine_unverified("Unverified", story("x", ["1"], ev={"primary": 0, "reports": 0})), "Single source")
        self.assertEqual(editorial.refine_unverified("Holds", story("x", ["1"])), "Holds")


class LintTest(unittest.TestCase):
    def test_machine_phrasing(self):
        out = editorial._clean("Unverified. Techmeme headlines lack full context; the post is unsourced, using "
                               "unsupported terms like 'tepid' without attribution. Two days (CVEs not specified).")
        self.assertNotIn("lack full context", out)
        self.assertNotIn("without attribution", out)
        self.assertNotIn("not specified", out)
        self.assertIn("Only Techmeme's headline is available", out)


class FatigueTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        rec = {"day": "2026-10-30", "stories": [{"section": "must", "n": "1", "headline": "Anthropic S-1 shows $16.3B revenue",
                                                 "ids": ["a", "b"]}]}
        (self.dir / "2026-10-30.jsonl").write_text(json.dumps(rec) + "\n")

    def test_same_lead_moves_down(self):
        sel = {"must": [story("Anthropic S-1 numbers questioned", ["a", "c"]), story("OpenAI raise falls short", ["d"])]}
        with mock.patch("pipeline.profiles.profile", return_value={"kind": "commentary"}):
            why = editorial.stale_lead(sel, self.dir, "2026-10-31")
        self.assertTrue(why)
        self.assertEqual(sel["must"][0]["headline"], "OpenAI raise falls short")

    def test_new_report_keeps_the_lead(self):
        sel = {"must": [story("Anthropic S-1 numbers questioned", ["a", "c"]), story("OpenAI raise falls short", ["d"])]}
        with mock.patch("pipeline.profiles.profile", return_value={"kind": "reporting"}):
            self.assertEqual(editorial.stale_lead(sel, self.dir, "2026-10-31"), "")
        self.assertEqual(sel["must"][0]["headline"], "Anthropic S-1 numbers questioned")


class CapabilityTest(unittest.TestCase):
    def test_promoted_when_missing(self):
        must = [story("OpenAI raise falls short of target", ["1"]), story("Neoclouds lose bond access", ["2"])]
        worth = [story("Genie 4 world model adds audio", ["3", "4"], names=("DeepMind", "TechCrunch"), score=3.5)]
        self.assertIn("Genie 4", editorial.capability_slot(must, worth, 6))
        self.assertTrue(any(editorial.is_capability(s) for s in must))
        self.assertEqual(worth, [])

    def test_left_alone_when_present_or_weak(self):
        must = [story("Mistral releases open weights model", ["1"])]
        self.assertEqual(editorial.capability_slot(must, [story("Genie 4 world model", ["3", "4"])], 6), "")
        must = [story("Startup raises $50M", ["1"])]
        self.assertEqual(editorial.capability_slot(must, [story("A paper on reasoning", ["3"], score=2)], 6), "")


class SentenceTest(unittest.TestCase):
    def test_disclosure_word_kept_mid_sentence(self):
        t = "That is a joke on a recording, not a disclosure. But it matches."
        self.assertEqual(strip_disclosures(t), (t, 0))

    def test_broken_sentence(self):
        self.assertTrue(deepdive.broken_sentence("That is a joke on a recording, not But it matches the numbers."))
        self.assertFalse(deepdive.broken_sentence("Amazon has not denied that racks are staged."))


if __name__ == "__main__":
    unittest.main()
