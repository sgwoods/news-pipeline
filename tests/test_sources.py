import unittest

from pipeline import perspective, sources

TABLE = """## Tracked people
| Name | Tier | Where | Notes |
|---|---|---|---|
| Ed Zitron | follow closely | newsletter (wheresyoured.at), Bluesky (edzitron.com) | |
| Elon Musk | SCRUTINY | X | |
| Jack Clark | follow closely | Import AI (importai.substack.com) | |
"""


class TestCandidates(unittest.TestCase):
    def setUp(self):
        self.by = {p.name: p for p in perspective.parse(TABLE).people}

    def test_site_and_bluesky_groups(self):
        gs = sources.build_groups(self.by["Ed Zitron"], None)
        kinds = [g.kind for g in gs]
        self.assertEqual(kinds, ["site", "bluesky"])
        self.assertIn("https://wheresyoured.at/rss/", gs[0].urls)
        self.assertEqual(gs[0].discover, "https://wheresyoured.at")
        self.assertEqual(gs[1].urls, ["https://bsky.app/profile/edzitron.com/rss"])

    def test_no_candidates_for_x_only(self):
        self.assertEqual(sources.build_groups(self.by["Elon Musk"], None), [])

    def test_hint_alternatives_and_site(self):
        hints = {"feeds": [["https://a.example/feed", "https://b.example/feed"],
                           "site:https://c.example/blog"],
                 "bluesky": ["jack.bsky.social"]}
        gs = sources.build_groups(self.by["Jack Clark"], hints)
        self.assertEqual([g.kind for g in gs], ["site", "bluesky", "feed", "site"])
        self.assertEqual(gs[2].urls, ["https://a.example/feed", "https://b.example/feed"])
        self.assertEqual(gs[3].discover, "https://c.example/blog")

    def test_find_feed_links(self):
        html = ('<head><link rel="alternate" type="application/rss+xml" href="/feed.xml">'
                '<link rel="stylesheet" href="/x.css">'
                "<link type='application/atom+xml' rel='alternate' href='https://x.example/atom'></head>")
        self.assertEqual(sources.find_feed_links(html, "https://site.example/blog"),
                         ["https://site.example/feed.xml", "https://x.example/atom"])



class TestPageGroups(unittest.TestCase):
    def test_pages_hint_builds_group(self):
        p = perspective.parse(TABLE).people[1]  # Elon Musk: no sites of his own
        gs = sources.build_groups(p, {"pages": [{"include": ["/blog/"],
                                                 "try": ["sitemap:https://x.com/sitemap.xml",
                                                         "listing:https://x.com/blog"]}]})
        self.assertEqual(len(gs), 1)
        self.assertEqual(gs[0].kind, "pages")
        self.assertEqual(gs[0].options, {"include": ["/blog/"], "exclude": []})
        self.assertEqual(sources.split_page_candidate(gs[0].urls[0]),
                         ("sitemap", "https://x.com/sitemap.xml"))


if __name__ == "__main__":
    unittest.main()
