import tempfile
import unittest
from pathlib import Path

from pipeline import watchlist as wl



def setUpModule():                      # tests never write to the real request log
    global _lp
    from unittest import mock as _m
    _lp = _m.patch("pipeline.watchlist._logreq", lambda *a, **k: None)
    _lp.start()


def tearDownModule():
    _lp.stop()

class Watchlist(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        wl.save(self.root, [{"name": "Corvane", "relation": "board", "aliases": ["Corvane Labs"], "site": "corvane.com"}])

    def test_edit(self):
        wl.add(self.root, "Kinetiq.ai", "board", ["Kinetiq"])
        with self.assertRaises(ValueError):
            wl.add(self.root, "corvane")
        self.assertEqual([c["name"] for c in wl.load(self.root)], ["Corvane", "Kinetiq.ai"])
        self.assertTrue(wl.remove(self.root, "Kinetiq.ai"))
        self.assertIn("dashboard Watchlist page", (self.root / wl.FILE).read_text())

    def test_scan_and_dedupe(self):
        items = [{"title": "Corvane Labs releases Aya", "text": "...", "url": "https://x.com/a", "published": "2026-10-14"},
                 {"title": "A coherent plan", "text": "corvane-like", "url": "https://x.com/b"},
                 {"title": "North GA", "text": "", "url": "https://corvane.com/blog/north"},
                 {"title": "Corvane tracker", "text": "Corvane", "url": "https://link.mail.beehiiv.com/ss/c/u1"}]
        rows = wl.scan_items(wl.load(self.root), items)
        self.assertEqual([r["url"] for r in rows], ["https://x.com/a", "https://corvane.com/blog/north"])
        self.assertEqual(rows[1]["source"], "company site")
        self.assertEqual(len(wl.add_mentions(self.root, rows)), 2)
        self.assertEqual(len(wl.add_mentions(self.root, rows)), 0)
        self.assertEqual(len(wl.mentions(self.root, 3650)), 2)

    def test_gdelt_parse(self):
        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"articles": [{"url": "https://www.corvane.com/x", "title": "T", "domain": "corvane.com",
                                      "seendate": "20261014T120000Z", "language": "English"}]}

        class C:
            def get(self, url):
                assert "mode=ArtList" in url and "Corvane" in url
                return R()
        rows = wl.gdelt(wl.load(self.root)[0], C())
        self.assertEqual((rows[0]["published"], rows[0]["own_site"], rows[0]["source"]), ("2026-10-14T12:00:00+00:00", True, "news"))


if __name__ == "__main__":
    unittest.main()


class PeopleAndCompetitors(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        wl.save(self.root, [{"name": "Corvane", "relation": "board", "aliases": [], "site": "corvane.com"}])

    def test_edit_people_and_competitors(self):
        people = wl.parse_people("Dana Reyes | co-founder & CEO | | danareyes\nSam Okafor | co-founder | samokafor.bsky.social\n | bad")
        c = wl.update(self.root, "Corvane", people=people, competitors=["Mistral", "Writer", "Mistral"], site="https://www.Corvane.com/")
        self.assertEqual(c["people"][0], {"name": "Dana Reyes", "role": "co-founder & CEO", "x": "danareyes"})
        self.assertEqual(c["people"][1]["bluesky"], "samokafor.bsky.social")
        self.assertEqual((c["competitors"], c["site"]), (["Mistral", "Writer"], "corvane.com"))
        self.assertIn("Sam Okafor | co-founder | samokafor.bsky.social", wl.people_text(c))

    def test_scan_people_and_competitors(self):
        wl.update(self.root, "Corvane", people=[{"name": "Dana Reyes"}], competitors=["Mistral"])
        rows = wl.scan_items(wl.load(self.root), [
            {"title": "Dana Reyes on enterprise agents", "text": "", "url": "https://pod.example/1"},
            {"title": "Mistral raises", "text": "Mistral AI raised", "url": "https://news.example/2"}])
        self.assertEqual([(r["source"], r.get("person"), r.get("competitor")) for r in rows],
                         [("person", "Dana Reyes", None), ("competitor", None, "Mistral")])

    def test_board_competitors_feed_the_conflict_labels(self):
        from pipeline import stages
        wl.update(self.root, "Corvane", competitors=["Writer", "Sakana AI"])
        (self.root / "conflicts.yaml").write_text("board:\n  Corvane:\n    competitors: [Writer]\n")
        block = stages.conflicts_block(self.root / "conflicts.yaml")
        self.assertIn("Named direct competitors: Writer, Sakana AI.", block)
