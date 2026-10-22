import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import record

MANIFEST = {"schema_version": "1.0", "project_id": "steven-woods-research", "sources": [
    {"source_id": "src-a", "title": "Riddick Show", "source_type": "appearance", "date": {"display": "May 1, 2023"},
     "urls": {"canonical": "https://podcasts.example/riddick?i=1", "archive_local": "x.html", "archive_web": None}},
    {"source_id": "src-b", "title": "Springboard interview", "source_type": "appearance", "date": {"display": "2013"},
     "urls": {"canonical": "https://springboard.example/steven/"}}]}
CFG = {"record": {"watch": {"self": ["Steven Woods"], "board": ["Corvane", "Quillery"], "people": ["Priya Natarajan"]}}}


class Fake:
    label = "fake"

    def __init__(self, out):
        self.out, self.prompts = out, []

    def complete_json(self, system, user, retries=1, max_tokens=None):
        self.prompts.append(user)
        return self.out


class TestRecord(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        d = self.root / record.DIR
        d.mkdir(parents=True)
        (d / "manifest-cache.json").write_text(json.dumps(MANIFEST))
        self.live = mock.patch("pipeline.dive.check_links", lambda urls, cfg: {u: "dead" not in u for u in urls})
        self.live.start()

    def tearDown(self):
        self.live.stop()
        self.tmp.cleanup()

    def test_search_dedupes_against_manifest_and_checks_links(self):
        llm = Fake({"found": [
            {"url": "https://www.springboard.example/steven", "title": "dup of archive"},
            {"url": "https://news.example/firm-ai-panel", "title": "AI panel", "type": "appearance", "date": "2026-09"},
            {"url": "https://dead.example/x", "title": "gone"},
            {"url": "ftp://bad", "title": "bad"}]})
        rows = record.search(self.root, CFG, llm=llm, log=lambda *a: None)
        self.assertIn("https://springboard.example/steven", llm.prompts[0])
        self.assertEqual([r["title"] for r in rows], ["AI panel"])
        self.assertEqual(record.search(self.root, CFG, llm=llm, log=lambda *a: None), [])   # already queued
        self.assertFalse(record.search_due(self.root, CFG))

    def test_accept_exports_manifest_format(self):
        rows = record.enqueue(self.root, CFG, [{"url": "https://news.example/a", "title": "Talk", "type": "appearance",
                                                "subtype": "talk", "date": "2026-09", "outlet": "Big Conf",
                                                "quote": "Talent is the moat."}], "web-search", refresh=False)
        record.decide(self.root, rows[0]["id"], "accepted")
        out = json.loads((self.root / record.DIR / "manifest-candidates.json").read_text())
        e = out["sources"][0]
        self.assertEqual(out["project_id"], "steven-woods-research")
        self.assertEqual(e["source_type"], "appearance")
        self.assertEqual(e["date"], {"display": "2026-09", "sort": "2026-09-01", "precision": "month"})
        self.assertEqual(e["status"], "candidate")
        self.assertEqual(e["urls"]["canonical"], "https://news.example/a")
        self.assertIn("Talent is the moat.", e["notes"])
        self.assertTrue(e["source_id"].startswith("src-steven-2026-big-conf"))

    def test_scan_and_log_mentions(self):
        items = [{"id": "1", "url": "https://n.example/1", "title": "Northbeam's Steven Woods on agents", "text": "", "person": "Noah Smith"},
                 {"id": "2", "url": "https://corvane.com/blog/x", "title": "Corvane launches", "text": "Corvane", "person": "Corvane / Corvane Labs"},
                 {"id": "3", "url": "https://n.example/3", "title": "Quillery raises", "text": "Priya Natarajan said", "person": "X"},
                 {"id": "4", "url": "https://n.example/4", "title": "Stevenson", "text": "Steven Woodson", "person": "X"}]
        hits = record.scan(items, CFG)
        self.assertEqual([(h["item_id"], h["kind"]) for h in hits], [("1", "self"), ("3", "board"), ("3", "people")])
        res = record.log_mentions(self.root, "2026-10-08", "r1", hits, CFG)
        self.assertEqual(res["queued"], 1)
        self.assertEqual(record.load_queue(self.root)[0]["origin"], "daily-feed")
        self.assertEqual(len(record.recent_mentions(self.root)), 3)

    def test_own_words_proposal_and_apply(self):
        (self.root / "author.md").write_text("# About\n\n## Voice\n- direct\n")
        llm = Fake({"views": [
            {"topic": "Talent", "view": "Universities are Canada's real advantage.", "quote": "talent is the moat",
             "source_id": "src-b"},
            {"topic": "AI", "view": "Agents need audits.", "source_id": "web", "url": "https://dead.example/t"},
            {"topic": "AI", "view": "No source", "source_id": "nope"}]})
        rec = record.own_words(self.root, CFG, llm=llm, log=lambda *a: None, fetch=lambda u, c: "TEXT " + u)
        self.assertEqual(rec["views"], 1)
        self.assertIn("TEXT https://springboard.example/steven/", llm.prompts[0])
        self.assertTrue(record.apply_own_words(self.root))
        a = (self.root / "author.md").read_text()
        self.assertIn("## In my own words", a)
        self.assertIn('"talent is the moat" ([Springboard interview, 2013](https://springboard.example/steven/))', a)
        record.apply_own_words(self.root)                       # re-applying replaces, never duplicates
        self.assertEqual((self.root / "author.md").read_text().count("## In my own words"), 1)


if __name__ == "__main__":
    unittest.main()
