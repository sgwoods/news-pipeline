import unittest

from pipeline import pages

SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://corvane.com/blog/command-x</loc><lastmod>2026-10-03</lastmod></url>
<url><loc>https://corvane.com/blog</loc></url>
<url><loc>https://corvane.com/pricing</loc></url>
<url><loc>https://corvane.com/blog/tag/news</loc></url>
</urlset>"""
INDEX = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://x.com/sitemap-pages.xml</loc></sitemap></sitemapindex>"""


class R:
    def __init__(self, url, body, code=200):
        self.url, self.status_code, self.content, self.text = url, code, body.encode(), body


class C:
    def __init__(self, pages_):
        self.p = pages_

    def get(self, url):
        return R(url, self.p[url]) if url in self.p else R(url, "", 404)


class TestPages(unittest.TestCase):
    def test_parse_sitemap(self):
        kind, entries = pages.parse_sitemap(SITEMAP)
        self.assertEqual(kind, "urlset")
        self.assertEqual(entries[0], ("https://corvane.com/blog/command-x", "2026-10-03"))
        self.assertEqual(pages.parse_sitemap(INDEX), ("index", ["https://x.com/sitemap-pages.xml"]))

    def test_matches(self):
        base = "https://corvane.com/sitemap.xml"
        self.assertTrue(pages.matches("https://corvane.com/blog/command-x", base, ["/blog/"]))
        self.assertFalse(pages.matches("https://corvane.com/blog", base, ["/blog/"]))      # index page
        self.assertFalse(pages.matches("https://corvane.com/blog/tag/news", base, ["/blog/"]))
        self.assertFalse(pages.matches("https://other.com/blog/x", base, ["/blog/"]))
        self.assertTrue(pages.matches("https://www.darioamodei.com/essay/x", "https://darioamodei.com/", ["/"]))
        self.assertFalse(pages.matches("https://darioamodei.com/", "https://darioamodei.com/", ["/"]))

    def test_discover_sitemap_and_listing(self):
        c = C({"https://corvane.com/sitemap.xml": SITEMAP,
               "https://corvane.com/blog": '<a href="/blog/a">a</a><a href="/blog/a">dup</a><a href="/about">x</a>'})
        got = pages.discover(c, {"method": "sitemap", "url": "https://corvane.com/sitemap.xml",
                                 "include": ["/blog/"]})
        self.assertEqual(got, [("https://corvane.com/blog/command-x", "2026-10-03")])
        got = pages.discover(c, {"method": "listing", "url": "https://corvane.com/blog", "include": ["/blog/"]})
        self.assertEqual(got, [("https://corvane.com/blog/a", "")])


if __name__ == "__main__":
    unittest.main()
