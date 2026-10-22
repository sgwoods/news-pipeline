import logging
import unittest

from pipeline import stages


class FakeLLM:
    def __init__(self):
        self.seen = []

    def complete_json(self, system, user, retries=1, max_tokens=None):
        ids = [p.split('"')[0] for p in user.split('<item id="')[1:]]
        self.seen += ids
        return {"decisions": [{"id": i, "keep": False, "reason": "x"} for i in ids]}


class TestTuning(unittest.TestCase):
    def test_long_form_skips_model_filter(self):
        long_post = {"id": "L", "url": "u1", "source_kind": "site", "text": "word " * 300, "title": "Import AI"}
        social = {"id": "S", "url": "u2", "source_kind": "bluesky", "text": "short post about movies", "title": "t"}
        llm = FakeLLM()
        d, _, _ = stages.run_filter(llm, [long_post, social], "sys", {}, logging.getLogger("t"))
        self.assertEqual(llm.seen, ["S"])
        self.assertTrue(d["L"]["keep"])
        self.assertFalse(d["S"]["keep"])

    def test_apostrophes_are_not_quotes(self):
        item = {"title": "", "text": "Anthropic's S-1 and hyperscalers' capex."}
        self.assertEqual(stages.unverified_quotes("Corvane's North platform with PwC's team and Anthropic's deal", item), [])
        self.assertEqual(stages.unverified_quotes("he warned of 'rogue agents taking over'.", item), ["rogue agents taking over"])


if __name__ == "__main__":
    unittest.main()
