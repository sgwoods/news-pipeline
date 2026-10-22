import datetime as dt
import unittest

from pipeline import textutil as T


class TestText(unittest.TestCase):
    def test_html_to_text_drops_scripts_keeps_paragraphs(self):
        html = "<p>Hello <b>world</b></p><script>evil()</script><p>Second&nbsp;para</p>"
        self.assertEqual(T.html_to_text(html), "Hello world\n\nSecond para")

    def test_item_id_ignores_tracking_and_www(self):
        a = T.item_id("https://www.example.com/post/?utm_source=x&id=3")
        b = T.item_id("https://example.com/post?id=3")
        self.assertEqual(a, b)
        self.assertNotEqual(a, T.item_id("https://example.com/post?id=4"))

    def test_clean_url_strips_tracking_only(self):
        self.assertEqual(T.clean_url("https://www.x.com/p/?utm_source=rss&id=3#frag"),
                         "https://www.x.com/p/?id=3")

    def test_parse_date_formats(self):
        want = dt.datetime(2026, 10, 4, 9, 30, tzinfo=dt.timezone.utc)
        self.assertEqual(T.parse_date("2026-10-04T09:30:00Z"), want)
        self.assertEqual(T.parse_date("Sun, 04 Oct 2026 09:30:00 +0000"), want)
        self.assertEqual(T.parse_date("2026-10-04T05:30:00-04:00"), want)
        self.assertEqual(T.parse_date("2026-10-04"), dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc))
        self.assertIsNone(T.parse_date("not a date"))

    def test_extract_page(self):
        html = ('<html><head><title>T</title><meta property="og:title" content="Real &amp; Title">'
                '<meta content="2026-10-01T12:00:00Z" property="article:published_time"></head>'
                '<body><nav>menu</nav><article><h1>Head</h1><p>Body text.</p></article></body></html>')
        p = T.extract_page(html)
        self.assertEqual(p["title"], "Real & Title")
        self.assertEqual(p["published"], "2026-10-01T12:00:00Z")
        self.assertEqual(p["text"], "Head\n\nBody text.")


if __name__ == "__main__":
    unittest.main()
