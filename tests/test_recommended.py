import logging
import unittest

from pipeline import editorial


def r(i, person, url, kind="site"):
    return {"id": i, "person": person, "url": url, "source_kind": kind, "tier": "follow closely", "importance": 4,
            "claim": "c", "headline": f"headline {i}"}


class Fake:
    def __init__(self, out):
        self.out = out
        self.prompts = []

    def complete_json(self, system, user, max_tokens=None, retries=1):
        self.prompts.append(user)
        return self.out


class Recommended(unittest.TestCase):
    def test_editor_pick_and_fallback(self):
        recs = [r("a", "Techmeme", "https://bsky.app/x", "bluesky"), r("b", "Simon Willison", "https://simonwillison.net/2026/x/")]
        by_id = {x["id"]: x for x in recs}
        st = editorial.build_stories([{"ids": ["a", "b"], "headline": "Model launch"}], by_id)
        sel = {"must": st, "worth": [], "brief": [], "more": 0}
        llm = Fake({"day_in_brief": "x", "recommended_reading": {"n": 1, "source": "Simon Willison", "why": "He ran it."}})
        ed, _, errs = editorial.run_editorial(llm, sel, "sys", logging.getLogger("t"))
        self.assertIn("readable sources: ", llm.prompts[0])
        rr = ed["recommended_reading"]
        self.assertEqual((rr["id"], rr["kind"], rr["why"]), ("b", "hands-on test", "He ran it."))
        self.assertEqual(editorial.recommended_record(st[0])["id"], "b")      # best long read without a name
        ed2, _, _ = editorial.run_editorial(Fake({"day_in_brief": "x", "recommended_reading": {"n": 9, "why": "?"}}), sel, "s",
                                            logging.getLogger("t"))
        self.assertNotIn("recommended_reading", ed2)


if __name__ == "__main__":
    unittest.main()
