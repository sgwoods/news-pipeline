import unittest
from pathlib import Path

from pipeline import hub


class HubBrandTest(unittest.TestCase):
    def test_style_uses_brand_teal(self):
        css = hub.brand_style(Path(__file__).resolve().parent.parent)
        self.assertIn("#3e7e8a", css)
        self.assertIn("prefers-color-scheme: dark", css)


if __name__ == "__main__":
    unittest.main()
