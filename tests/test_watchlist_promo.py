import unittest
from pipeline import watchlist


class PromoTest(unittest.TestCase):
    def test_sales_titles(self):
        for t in ["🔥 24 hours to get 50% off Exponential View", "Last chance: 30% off annual plans",
                  "Black Friday: gift a subscription", "Subscribe now and save"]:
            self.assertTrue(watchlist.is_promo(t), t)

    def test_news_titles(self):
        for t in ["OpenAI raises $11B at $1.25T", "Import AI 477: In which I tell the IMF the Singularity has begun",
                  "Price cuts of up to 80% hit model APIs"]:
            self.assertFalse(watchlist.is_promo(t), t)

    def test_scan_skips_promo(self):
        cos = [{"name": "Acme Robotics", "competitors": ["OpenAI"]}]
        items = [{"title": "🔥 24 hours to get 50% off Exponential View", "text": "OpenAI and more",
                  "url": "https://www.exponentialview.co/p/x", "person": "Exponential View"},
                 {"title": "OpenAI ships a new model", "text": "OpenAI said", "url": "https://example.com/a"}]
        rows = watchlist.scan_items(cos, items)
        self.assertEqual([r["title"] for r in rows], ["OpenAI ships a new model"])


if __name__ == "__main__":
    unittest.main()
