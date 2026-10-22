"""Thin items: read the article behind the post before the evidence check; never judge a headline alone."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import quality, reader, stages

ARTICLE = ("<html><head><title>Agentic commerce on Base hits 138M payments | Fortune</title></head><body>"
           "<nav><p>Home Subscribe Newsletters Sections and many more navigation words here</p></nav><article>"
           + "".join(f"<p>Chainalysis data shows agentic commerce payments on Coinbase's Base network grew from about "
                     f"1,500 transactions to 138 million in the third quarter, paragraph {i} of the report.</p>"
                     for i in range(8))
           + "</article><footer><p>Copyright notice and other boilerplate that should never be read.</p></footer></body></html>")
POST = {"id": "p1", "url": "https://bsky.app/profile/techmeme.com/post/3mxv", "source_kind": "bluesky",
        "title": "Chainalysis: agentic commerce on Coinbase's Base grew to 138M+ payments",
        "text": "Chainalysis: agentic commerce on Coinbase's Base grew from ~1,500 transactions to 138M+ (Fortune)",
        "linked_url": "https://fortune.com/2026/10/14/ai-agents-shopping-spree"}


class Resp:
    def __init__(self, text, status=200, ctype="text/html; charset=utf-8"):
        self.text, self.status_code, self.headers, self.content = text, status, {"content-type": ctype}, text.encode()


class Client:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, u, **kw):
        self.calls.append(u)
        return self.pages.get(u, Resp("", 404))

    def close(self):
        pass


class Reader(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def run_with(self, items, pages):
        cl = Client(pages)
        with mock.patch("pipeline.netguard.client", lambda **kw: cl):
            return reader.read_thin(self.root, items, {}, None), cl

    def test_extract_prefers_article_and_skips_boilerplate(self):
        title, text = reader.extract(ARTICLE)
        self.assertIn("Fortune", title)
        self.assertIn("138 million", text)
        self.assertNotIn("Copyright", text)
        self.assertNotIn("navigation", text)

    def test_reads_the_linked_article_and_cites_it(self):
        it = dict(POST)
        stats, cl = self.run_with([it], {POST["linked_url"]: Resp(ARTICLE)})
        self.assertEqual((stats["read"], stats["unreadable"]), (1, 0))
        self.assertIn("138 million", it["read_text"])
        block = stages.item_block(it, 6000)
        self.assertIn("linked article (fetched from https://fortune.com", block)
        # cached: a second run does not fetch again
        it2 = dict(POST)
        stats2, cl2 = self.run_with([it2], {})
        self.assertEqual((stats2["read"], cl2.calls), (1, []))

    def test_unrelated_or_paywalled_page_is_not_evidence(self):
        other = "<html><title>Sign in</title><body><article>" + "<p>Please sign in to read our journalism. " * 40 + "</p></article></body></html>"
        it = dict(POST)
        stats, _ = self.run_with([it], {POST["linked_url"]: Resp(other)})
        self.assertTrue(it.get("thin"))
        self.assertNotIn("read_text", it)

    def test_never_fetches_social_account_or_tracker_links(self):
        it = {"id": "x", "url": "https://x.com/someone/status/1", "title": "t", "source_kind": "x",
              "text": "see https://example.com/unsubscribe?u=1 and https://bsky.app/profile/a/post/b"}
        self.assertEqual(reader.candidates(it), [])

    def test_network_errors_are_retried_next_run(self):
        class Down(Client):
            def get(self, u, **kw):
                self.calls.append(u)
                raise OSError("no route")
        cl = Down({})
        with mock.patch("pipeline.netguard.client", lambda **kw: cl):
            reader.read_thin(self.root, [dict(POST)], {}, None)
        self.assertEqual(json.loads((self.root / reader.CACHE).read_text()), {})

    def test_a_post_with_no_link_is_judged_as_a_post(self):
        it = {"id": "z", "url": "https://bsky.app/profile/someone/post/1", "source_kind": "bluesky",
              "title": "Lab X is a dog of a company", "text": "Lab X is a dog of a company. Losses are growing."}
        stats, _ = self.run_with([it], {})
        self.assertEqual(stats["no_link"], 1)
        self.assertFalse(it.get("thin"))

    def test_long_items_untouched(self):
        it = {"id": "l", "url": "https://example.com/a", "title": "t", "text": "word " * 400}
        stats, cl = self.run_with([it], {})
        self.assertEqual((stats["thin"], cl.calls), (0, []))

    def test_headline_only_is_unverified_not_judged(self):
        it = dict(POST, thin=True)
        llm = mock.Mock(side_effect=AssertionError("the model must not be asked"))
        out, _, errs = stages.run_critique(llm, [it], {"p1": {"claim": "c", "so_what": "s", "agenda_flag": ""}},
                                           "sys", {}, mock.Mock())
        self.assertEqual(out["p1"]["verdict"], "unverified")
        self.assertEqual(errs, [])

    def test_unverified_is_outside_the_critical_share(self):
        (self.root / "briefings").mkdir()
        (self.root / "data").mkdir()
        (self.root / "briefings/2026-10-16.md").write_text("# T\n\n" + " word" * 900)
        (self.root / "data/runs.jsonl").write_text(json.dumps({"day": "2026-10-16", "stages": {"critique": {
            "verdicts": {"holds": 3, "overstated": 1, "unsupported": 1, "unverified": 5}}}}))
        v = quality.score_day(self.root, {}, "2026-10-16")["values"]
        self.assertAlmostEqual(v["critical_share"], 0.4)
        self.assertEqual(v["headline_only"], 5)


class DeepDiveWritten(unittest.TestCase):
    def test_script_becomes_an_article(self):
        from pipeline import deepdive
        root = Path(tempfile.mkdtemp())
        (root / deepdive.DIR).mkdir(parents=True)
        (root / deepdive.DIR / "2026-10-17.script.md").write_text(
            "# Spoken script\n\n## Opener\n\nThanks, Michael. I'm Bella.\n\n## why_today\n\nTwo filings.\n\n"
            "## plainly\n\nGross versus net.\n\n## Outro\n\nThat's the deep dive.\n")
        md = deepdive.written_md(root, "2026-10-17")
        self.assertIn("## Why today\n\nTwo filings.", md)
        self.assertIn("## Plainly", md)
        self.assertNotIn("Bella", md)
        self.assertNotIn("That's the deep dive", md)


if __name__ == "__main__":
    unittest.main()
