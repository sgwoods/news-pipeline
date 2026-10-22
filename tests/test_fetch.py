import datetime as dt
import logging
import tempfile
import unittest
from pathlib import Path

from pipeline import fetch
from pipeline.archive import Archive

NOW = dt.datetime.now(dt.timezone.utc)
SINCE = NOW - dt.timedelta(hours=36)


class R:
    def __init__(self, url, body, code=200):
        self.url, self.status_code, self.text, self.content = url, code, body, body.encode()


class Client:
    def __init__(self, urls):
        self.urls, self.hits = urls, []

    def get(self, url):
        self.hits.append(url)
        if url.endswith("sitemap.xml"):
            locs = "".join(f"<url><loc>{u}</loc></url>" for u in self.urls)
            return R(url, f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>')
        return R(url, f'<meta property="og:title" content="{url}"><article><p>body</p></article>')


SRC = {"person": "P", "kind": "pages", "method": "sitemap", "url": "https://x.com/sitemap.xml",
       "include": ["/blog/"], "exclude": []}


class TestFetchPages(unittest.TestCase):
    def test_baseline_then_new_then_deferred_picked_up(self):
        a = Archive(Path(tempfile.mkdtemp()), {})
        log = logging.getLogger("t")
        cfg = {"max_pages_per_source": 2}
        c = Client([f"https://x.com/blog/{i}" for i in range(3)])
        items, st = fetch.fetch_pages(c, SRC, SINCE, NOW, cfg, "r1", a, set(), log)
        self.assertEqual(items, [])                       # no lastmod -> baseline only
        self.assertIn("baseline", st["note"])
        c.urls += [f"https://x.com/blog/new{i}" for i in range(3)]   # 3 new posts, cap 2
        items, st = fetch.fetch_pages(c, SRC, SINCE, NOW, cfg, "r2", a, set(), log)
        self.assertEqual(len(items), 2)
        self.assertEqual(st["deferred"], 1)
        a.add_items(items, "d")
        items, st = fetch.fetch_pages(c, SRC, SINCE, NOW, cfg, "r3", a, a.known_ids(), log)
        self.assertEqual([i["url"] for i in items], ["https://x.com/blog/new2"])   # deferred one
        self.assertNotIn("deferred", st)


if __name__ == "__main__":
    unittest.main()
