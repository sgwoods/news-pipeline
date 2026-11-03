"""Tightening keeps facts (2026-11-03); the live check retries transient errors; ships wait for the edition."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from pipeline import tighten

LONG = ("OpenAI raised $40B at a $300B valuation in a round led by SoftBank, which also committed to a further "
        "tranche next year if the company converts to a for-profit structure, according to people familiar with "
        "the talks [1](https://a.example/x).")


class Tighten(unittest.TestCase):
    def test_check_keeps_facts(self):
        ok = ("OpenAI raised $40B at a $300B valuation. SoftBank led the round and committed to a further tranche "
              "next year if the company converts to a for-profit structure, according to people familiar with the "
              "talks [1](https://a.example/x).")
        self.assertEqual(tighten.check(LONG, ok), "")
        self.assertEqual(tighten.check(LONG, ok.replace("$40B", "$45B")), "numbers changed")
        self.assertEqual(tighten.check(LONG, ok.replace(" [1](https://a.example/x)", "")), "citations changed")
        self.assertIn("new name", tighten.check(LONG, ok.replace("SoftBank led", "SoftBank and Microsoft led")))
        self.assertIn("length", tighten.check(LONG, "OpenAI raised $40B at a $300B valuation [1](https://a.example/x)."))

    def test_apply_uses_only_checked_rewrites(self):
        md = "# AI Briefing\n\n## Today in 30 seconds\n\n- **Big round.** " + LONG + "\n\n## Sources\n\n- " + LONG + "\n"

        class LLM:
            pass
        import pipeline.stages as stages
        orig = stages._ask
        good = ("OpenAI raised $40B at a $300B valuation. SoftBank led the round and committed to a further tranche "
                "next year if the company converts to a for-profit structure, according to people familiar with the "
                "talks [1](https://a.example/x).")
        stages._ask = lambda *a, **k: {"rewrites": [{"i": 1, "text": good}, {"i": 9, "text": "x"}]}
        try:
            out, st = tighten.apply(md, LLM(), log=lambda *a: None)
        finally:
            stages._ask = orig
        self.assertEqual(st["rewritten"], 1)
        self.assertIn("valuation. SoftBank led", out)
        self.assertIn("## Sources\n\n- " + LONG, out)            # source lists are never touched

    def test_model_error_leaves_edition(self):
        import pipeline.stages as stages
        orig = stages._ask

        def boom(*a, **k):
            raise RuntimeError("down")
        stages._ask = boom
        try:
            md = "## Today\n\n- " + LONG + "\n"
            out, st = tighten.apply(md, object(), log=lambda *a: None)
        finally:
            stages._ask = orig
        self.assertEqual(out, md)
        self.assertIn("error", st)


class LiveRetry(unittest.TestCase):
    def test_transient_503_retried_404_not(self):
        from pipeline import shipped
        root = Path(tempfile.mkdtemp())
        calls = {}

        class R:
            def __init__(self, c):
                self.status_code = c

        class C:
            def get(self, u):
                calls[u] = calls.get(u, 0) + 1
                if u.endswith("/feed.xml"):
                    return R(503 if calls[u] < 2 else 200)      # a GitHub Pages blip
                if u.endswith("/podcast.xml"):
                    return R(404)
                return R(200)
            head = get
        bad = shipped.verify_live(root, "https://x.example/b/", client=C(), log=lambda *a: None, sleep=lambda s: None)
        self.assertEqual(len(bad), 1)
        self.assertIn("podcast.xml -> 404", bad[0])
        self.assertEqual(calls["https://x.example/b/podcast.xml"], 1)

    def test_persistent_503_fails_after_retries(self):
        from pipeline import shipped

        class R:
            status_code = 503

        class C:
            def get(self, u):
                return R()
            head = get
        bad = shipped.verify_live(Path(tempfile.mkdtemp()), "https://x.example/b/", client=C(), log=lambda *a: None,
                                  sleep=lambda s: None, retries=2)
        self.assertTrue(bad and all("503" in b for b in bad))


class ShipWaitsForEdition(unittest.TestCase):
    def test_defer_until_sent_or_11(self):
        from pipeline import runner
        root = Path(tempfile.mkdtemp())
        job = {"id": "x", "recipe": "ship", "args": {"version": "0.2.99-beta", "note": "reviewed: x", "lane": "fix"}}

        def r(h, m, sent):
            return runner.Runner(root, root, root, now=lambda: dt.datetime(2026, 11, 3, h, m), notify=None,
                                 sent_today=lambda: sent)
        self.assertIn("edition goes out first", r(8, 45, False)._defer(job))
        self.assertEqual(r(8, 45, True)._defer(job), "")
        self.assertEqual(r(11, 5, False)._defer(job), "")


if __name__ == "__main__":
    unittest.main()
