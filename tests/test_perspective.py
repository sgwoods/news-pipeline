import unittest
from pathlib import Path

from pipeline import perspective

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = """# perspective
## Tracked people
| Name | Tier | Where | Notes |
|---|---|---|---|
| Ed Zitron | follow closely | newsletter (wheresyoured.at), Bluesky (edzitron.com), podcast Better Offline | bear |
| Jordan Blake | follow closely (PORTFOLIO) | Quillery blog, X | portfolio |
| Sam Altman | SCRUTINY | X, blog | hype |
| Corvane / Corvane Labs | follow closely (Canadian) | corvane.com/blog, corvane.com/research | sovereign |

## Topics I care about (rank higher)
- AI economics
- Agent security
"""


class TestParse(unittest.TestCase):
    def setUp(self):
        self.p = perspective.parse(SAMPLE)
        self.by = {x.name: x for x in self.p.people}

    def test_people_count(self):
        self.assertEqual(len(self.p.people), 4)

    def test_bluesky_handle_not_treated_as_site(self):
        z = self.by["Ed Zitron"]
        self.assertEqual(z.bluesky, ["edzitron.com"])
        self.assertEqual(z.sites, ["wheresyoured.at"])
        self.assertIn("podcast better offline", z.other_platforms)

    def test_tier_flags_and_scrutiny(self):
        s = self.by["Jordan Blake"]
        self.assertEqual(s.tier, "follow closely")
        self.assertEqual(s.flags, ["PORTFOLIO"])
        self.assertFalse(s.scrutiny)
        self.assertTrue(self.by["Sam Altman"].scrutiny)

    def test_site_paths(self):
        self.assertEqual(self.by["Corvane / Corvane Labs"].sites,
                         ["corvane.com/blog", "corvane.com/research"])

    def test_x_only_has_no_sites(self):
        a = self.by["Sam Altman"]
        self.assertEqual(a.sites, [])
        self.assertIn("x", a.other_platforms)

    def test_bullets(self):
        self.assertEqual(self.p.topics, ["AI economics", "Agent security"])


class TestRealFile(unittest.TestCase):
    """Smoke test against Steven's actual perspective.md (read-only)."""

    @unittest.skipUnless((ROOT / "perspective.md").is_file(), "perspective.md is private (not in the public repo)")
    def test_loads(self):
        p = perspective.load(ROOT / "perspective.md")
        self.assertGreaterEqual(len(p.people), 10)
        self.assertTrue(p.topics)
        self.assertTrue(p.skepticism)


if __name__ == "__main__":
    unittest.main()
