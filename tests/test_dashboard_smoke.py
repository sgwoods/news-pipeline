import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["/", "/status", "/quality", "/briefings", "/control", "/sources", "/items", "/deep-dives", "/threads",
         "/questions", "/feedback", "/runs", "/schedule", "/todo", "/lens", "/tuning", "/voices", "/brand", "/watchlist"]


@unittest.skipUnless((ROOT / "config.yaml").exists(), "needs a checkout with config.yaml")
class DashboardSmoke(unittest.TestCase):
    """Every page in the menus renders (2026-11-01: the grouped menu's `groups` variable shadowed two pages' own)."""

    def test_pages_render(self):
        from dashboard.app import create_app
        c = create_app(ROOT).test_client()
        bad = [(u, r.status_code) for u in PAGES for r in [c.get(u)] if r.status_code != 200]
        self.assertEqual(bad, [])

    def test_base_template_does_not_shadow_page_variables(self):
        base = (ROOT / "dashboard" / "templates" / "base.html").read_text("utf-8")
        self.assertNotIn("{% set groups", base)


if __name__ == "__main__":
    unittest.main()
