"""Steven 2026-10-31: one brand template (brand/brand.yaml) that every surface reads."""
import unittest

from pipeline import brand, mailer, site


class Brand(unittest.TestCase):
    def test_tokens_and_taglines(self):
        b = brand.load()
        self.assertEqual(b["colors"]["teal"], "#3e7e8a")
        self.assertIn("pale", b["dark"])
        self.assertEqual(brand.tagline("main"), "Slowly, then fast. Every morning.")
        self.assertTrue(brand.author()["image"].endswith("author-master.png"))

    def test_site_css_is_built_from_the_brand(self):
        css = site.site_css()
        self.assertIn("--teal:#3e7e8a", css)
        self.assertIn("prefers-color-scheme:dark", css)
        self.assertNotIn("#67e6a8", css)                    # the old mint is gone

    def test_email_palette_is_the_brand(self):
        self.assertEqual(mailer.C["accent"], brand.color("teal"))
        self.assertEqual(mailer.TAGLINE, brand.tagline("main"))

    def test_pages_carry_the_masthead_and_tagline(self):
        page = site._page("x", "<p>y</p>", "", {"publish": {"site_url": "https://example.github.io/b/"}})
        self.assertIn('class="mast"', page)
        self.assertIn("steven-woods.jpg", page)
        self.assertIn(brand.tagline("main"), page)
        dd = site._page("x", "<p>y</p>", "../../", {}, kind="deepdive")
        self.assertIn('class="mast dd"', dd)
        self.assertIn(brand.tagline("deep_dive"), dd)


if __name__ == "__main__":
    unittest.main()
