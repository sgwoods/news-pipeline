"""v0.2.33 (Steven 2026-10-30: "lets do the deep dive now"): the deep dive's factual sentences are checked against
its sources before it is recorded; a wrong one is rewritten as a plain spoken sentence, a page found by search joins
its Sources, a second model re-checks, and what is left goes to Steven (the draft Doc, the takes email)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import audit, deepdive

DAY = "2026-10-31"
SRC = "The Government of Canada will invest up to $1.6 billion in Northwind in stages, the release said."
SECTIONS = [("why_today", "Northwind took a big government cheque this week from the federal deposit insurer, CDIC, in a staged deal."),
            ("evidence", "The Government of Canada will invest up to $1.6 billion in Northwind in stages."),
            ("so_what", "For builders, CDIC money may come with strings attached across many years ahead.")]


class Fake:
    label = "fake"

    def __init__(self, sentence="", verdict_for_fixed="supported"):
        self.sentence, self.vf, self.asked = sentence, verdict_for_fixed, []

    def complete_json(self, system, user, max_tokens=0):
        self.asked.append(user)
        if "THE SENTENCE" in user:
            return {"sentence": self.sentence}
        out = []
        for blk in user.split("CLAIM ")[1:]:
            n = int(blk.split(" ", 1)[0])
            claim = blk.split("SOURCE EXCERPTS")[0]
            v = "partly" if "CDIC" in claim else "supported"
            out.append({"n": n, "verdict": v, "why": "sources say Government of Canada" if v != "supported" else ""})
        return {"checks": out}


class DeepDiveCheck(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.stamp = lambda: dt.datetime(2026, 10, 30, 15, 31)

    def test_only_factual_sections_are_checked_and_a_wrong_sentence_is_rewritten(self):
        good = "Northwind took a staged investment of up to $1.6 billion from the Government of Canada this week."
        judge = Fake()
        new, res, pages = audit.check_sections(self.root, DAY, SECTIONS, [SRC], Fake(good), "sys", judge=judge,
                                               log=lambda *a: None, stamp=self.stamp)
        self.assertEqual(dict(new)["why_today"], good)
        self.assertIn("CDIC", dict(new)["so_what"])                    # analysis isn't rewritten
        self.assertEqual(res["fixes"][0]["recheck"], "supported")
        self.assertTrue(judge.asked)
        self.assertEqual(audit.load_deepdive_check(self.root, DAY)["at"], "2026-10-30T15:31:00")

    def test_a_rewrite_with_links_or_markup_or_failing_audio_rules_is_refused(self):
        for bad in ("See [here](https://x.example) for **more** detail on Northwind.", ""):
            new, res, _ = audit.check_sections(self.root, DAY, SECTIONS, [SRC], Fake(bad), "sys", log=lambda *a: None)
            self.assertIn("CDIC", dict(new)["why_today"])
            self.assertTrue(res["held"])
        new, res, _ = audit.check_sections(self.root, DAY, SECTIONS, [SRC], Fake("Northwind took a staged deal."), "sys",
                                           log=lambda *a: None, ok_sentence=lambda t: False)
        self.assertIn("CDIC", dict(new)["why_today"])

    def test_a_found_page_becomes_a_source_when_the_fix_checks_out(self):
        page = {"url": "https://www.pm.gc.ca/en/news/x", "outlet": "Prime Minister of Canada", "title": "Landmark",
                "text": SRC, "primary": True}
        good = "According to the Prime Minister's Office, the Government of Canada will invest in Northwind in stages."
        with mock.patch("pipeline.factsearch.pages_for", return_value=[page]):
            new, res, pages = audit.check_sections(self.root, DAY, SECTIONS, [SRC], Fake(good), "sys",
                                                   log=lambda *a: None, finder=object())
        self.assertEqual([p["url"] for p in pages], [page["url"]])
        self.assertEqual(res["added_sources"][0]["url"], page["url"])

    def test_the_dive_adds_the_page_to_its_sources_and_runs_its_script_checks_again(self):
        page = {"url": "https://www.pm.gc.ca/en/news/x", "outlet": "Prime Minister of Canada", "title": "Landmark",
                "text": SRC, "primary": True}
        good = "According to the Prime Minister's Office, the Government of Canada will invest in Northwind in stages."
        with mock.patch("pipeline.factsearch.pages_for", return_value=[page]):
            new, srcs, notes = deepdive._fact_check(self.root, {}, DAY, SECTIONS, [SRC], [{"url": "https://a.example/1"}],
                                                    "sys", llm_check=Fake(good), judge=Fake(), finder=object(),
                                                    log=lambda *a: None)
        self.assertIn("https://www.pm.gc.ca/en/news/x", [s["url"] for s in srcs])
        self.assertTrue(notes[0].startswith("fact check:"))
        self.assertIn("1 source(s) added", notes[0])

    def test_a_rewrite_the_second_check_doesnt_confirm_is_undone_and_held(self):
        good = "Northwind took a staged investment of up to $1.6 billion from the Government of Canada this week."

        class No(Fake):
            def complete_json(self, system, user, max_tokens=0):
                self.asked.append(user)
                return {"checks": [{"n": 1, "verdict": "not found", "why": "no"}]}
        new, res, pages = audit.check_sections(self.root, DAY, SECTIONS, [SRC], Fake(good), "sys", judge=No(),
                                               log=lambda *a: None)
        self.assertIn("CDIC", dict(new)["why_today"])
        self.assertEqual(res["fixes"], [])
        self.assertEqual(res["held"][0]["verdict"], "rewrite not confirmed")

    def test_homepages_are_never_found_sources(self):
        from pipeline import factsearch

        class Resp:
            status_code = 200
            text = ("<rss><channel><item><title>a</title><link>https://www.anthropic.com/</link></item>"
                    "<item><title>b</title><link>https://www.pm.gc.ca/en/news/news-releases/2026/10/29/x</link></item>"
                    "</channel></rss>")

        class F:
            c = object()

            def _get(self, u):
                return Resp()

            def _page(self, u):
                return "Northwind and the Government of Canada, $1.6 billion."
        got = factsearch.pages_for(F(), "Northwind took $1.6 billion from the Government of Canada.")
        self.assertEqual([g["url"] for g in got], ["https://www.pm.gc.ca/en/news/news-releases/2026/10/29/x"])

    def test_a_two_voice_script_keeps_every_turn(self):
        """10-31: the flagship repeats section ids per turn; the check returned the last turn's text for every turn
        of that section, so the episode repeated paragraphs."""
        turns = [("why_today~host", "First host turn about Northwind and the Government of Canada deal."),
                 ("why_today~sceptic", "Sceptic turn one asks what Northwind actually closed."),
                 ("why_today~host", "Second host turn says the federal deposit insurer CDIC is in the deal."),
                 ("why_today~sceptic", "Sceptic turn two wants the Government of Canada terms.")]
        good = "Second host turn says the Government of Canada is investing in the deal."
        new, res, _ = audit.check_sections(self.root, DAY, turns, [SRC], Fake(good), "sys", judge=Fake(), log=lambda *a: None)
        self.assertEqual([t for _, t in new], [turns[0][1], turns[1][1], good, turns[3][1]])
        new, _r, _p = audit.check_sections(self.root, DAY, turns, [SRC], Fake(""), "sys", log=lambda *a: None)
        self.assertEqual(new, turns)                                   # nothing fixed: exactly what came in

    def test_the_check_never_breaks_the_dive(self):
        class Boom:
            label = "boom"

            def complete_json(self, *a, **k):
                raise RuntimeError("offline")
        new, srcs, notes = deepdive._fact_check(self.root, {}, DAY, SECTIONS, [SRC], [], "sys", llm_check=Boom(),
                                                log=lambda *a: None)
        self.assertEqual(len(new), 3)


if __name__ == "__main__":
    unittest.main()


class Rebuild(unittest.TestCase):
    def test_a_topic_already_in_the_queue_is_reused(self):
        root = Path(tempfile.mkdtemp())
        deepdive.save_queue(root, [{"id": "q1", "topic": "Who's liable when a chatbot gives medical advice?",
                                    "status": "done"}])
        with mock.patch.object(deepdive, "add_manual", return_value={}):
            item = None
            if not deepdive.add_manual(root, "Who's liable when a chatbot gives medical advice?"):
                item = next((q for q in deepdive.load_queue(root)
                             if deepdive._similar(q.get("topic", ""), "Who's liable when a chatbot gives medical advice?")), None)
        self.assertEqual(item["id"], "q1")
