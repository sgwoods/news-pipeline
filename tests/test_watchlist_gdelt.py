"""GDELT failures say why (status + message) and rate limits are retried."""
import unittest
from unittest import mock

from pipeline import watchlist as wl


def setUpModule():                      # tests never write to the real request log
    global _lp
    _lp = mock.patch("pipeline.watchlist._logreq", lambda *a, **k: None)
    _lp.start()


def tearDownModule():
    _lp.stop()


class R:
    def __init__(self, code, text="", js=None):
        self.status_code, self.text, self._js = code, text, js

    def json(self):
        if self._js is None:
            raise ValueError
        return self._js


class C:
    def __init__(self, seq):
        self.seq, self.n = list(seq), 0

    def get(self, url):
        self.n += 1
        return self.seq.pop(0)


class Gdelt(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch("time.sleep", lambda s: None)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_retries_a_rate_limit(self):
        c = C([R(429, "Please limit requests"), R(200, js={"articles": [{"url": "https://n.example/a", "title": "t"}]})])
        self.assertEqual(len(wl.gdelt({"name": "X", "query": '"X"'}, c)), 1)
        self.assertEqual(c.n, 2)

    def test_errors_carry_status_and_message(self):
        c = C([R(429, "Please limit requests to one every 5 seconds")] * 3)
        with self.assertRaises(wl.GdeltError) as e:
            wl.gdelt({"name": "X", "query": '"X"'}, c)
        self.assertIn("HTTP 429", str(e.exception))
        c2 = C([R(200, "The specified phrase is too short.")])
        with self.assertRaises(wl.GdeltError) as e2:
            wl.gdelt({"name": "X", "query": '"X"'}, c2)
        self.assertIn("too short", str(e2.exception))


class GdeltAll(unittest.TestCase):
    def test_one_request_filed_by_company(self):
        seen = []

        class One:
            def get(self, url):
                seen.append(url)
                return R(200, js={"articles": [
                    {"url": "https://n.example/a", "title": "Corvane signs AISLE deal"},
                    {"url": "https://n.example/b", "title": "Quillery raises a round"},
                    {"url": "https://n.example/c", "title": "Unrelated story"}]})
        rows = wl.gdelt_all([{"name": "Corvane", "aliases": ["Corvane Labs"]}, {"name": "Quillery", "aliases": []}], One())
        self.assertEqual(len(seen), 1)
        self.assertIn("%22Corvane%22%20OR%20%22Corvane%20Labs%22%20OR%20%22Quillery%22", seen[0])
        self.assertEqual(sorted((r["company"], r["url"][-1]) for r in rows), [("Corvane", "a"), ("Quillery", "b")])


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Corvane signs AISLE deal - Reuters</title><link>https://news.google.com/rss/articles/abc</link>
<pubDate>Sun, 18 Oct 2026 10:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
<item><title>Coherent laser maker beats estimates - CNBC</title><link>https://news.google.com/rss/articles/def</link>
<pubDate>Sun, 18 Oct 2026 09:00:00 GMT</pubDate><source url="https://www.cnbc.com">CNBC</source></item>
</channel></rss>"""


class GoogleNews(unittest.TestCase):
    def test_parses_and_requires_the_name_in_the_headline(self):
        class G:
            def get(self, url):
                self.url = url
                r = R(200, RSS)
                r.content = RSS.encode()
                return r
        g = G()
        with mock.patch("pipeline.watchlist._logreq", lambda *a, **k: None):
            rows = wl.gnews({"name": "Corvane", "aliases": []}, g)
        self.assertEqual([(r["title"], r["via"]) for r in rows], [("Corvane signs AISLE deal", "Reuters")])
        self.assertIn("when%3A2d", g.url)

    def test_duplicates_across_providers_dropped(self):
        rows = [{"company": "Corvane", "title": "Corvane signs AISLE deal"}, {"company": "Corvane", "title": "Corvane signs AISLE deal!"}]
        self.assertEqual(len(wl._dedupe_titles(rows)), 1)


if __name__ == "__main__":
    unittest.main()
