import json
import tempfile
import unittest
from pathlib import Path

from pipeline import hub

CFG = {"publish": {"repo": "sgwoods/ai-briefing", "site_url": "https://sgwoods.github.io/ai-briefing/"}}


class HubStatus(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings" / "deepdives").mkdir(parents=True)
        for d in ("2026-10-17", "2026-10-18"):
            (self.root / "briefings" / f"{d}.md").write_text("# x\n")
        (self.root / "briefings" / "deepdives" / "2026-10-18.md").write_text("# x\n")

    def test_manifest_matches_schema_1_0_exactly(self):
        m = hub.manifest(self.root, CFG)
        self.assertEqual(tuple(m), hub.KEYS)
        self.assertEqual(m["schema_version"], "1.0")
        self.assertEqual(m["project_page_path"], "ai-briefing.html")
        self.assertEqual(m["repo_url"], "https://github.com/sgwoods/ai-briefing")
        self.assertIsNone(m["dashboard_url"])
        self.assertTrue(m["status_generated_at"].endswith("Z"))
        self.assertEqual(m["status_value"], "Edition 2026-10-18 + deep dive")

    def test_files_written_two_space_utf8_trailing_newline(self):
        site = self.root / "site"
        hub.write(self.root, CFG, site)
        for base in (self.root / "hub", site / "hub"):
            txt = (base / "data" / "projects" / "ai-briefing.json").read_text("utf-8")
            self.assertTrue(txt.endswith("}\n"))
            self.assertIn('\n  "project_id": "ai-briefing"', txt)
            json.loads(txt)
            pg = (base / "ai-briefing.html").read_text("utf-8")
            self.assertIn('href="assets/public-site.css"', pg)
            self.assertIn('class="heroHomeLink" href="https://sgwoods.github.io/public/index.html"', pg)

    def test_page_has_no_private_details(self):
        pg = hub.page(hub.manifest(self.root, CFG), CFG, self.root)
        for bad in ("@gmail", "script.google", "subscriber", "board", "127.0.0.1", "your firm"):
            self.assertNotIn(bad, pg.replace("subscribe", ""))


class Shortcut(unittest.TestCase):
    def test_np_is_executable(self):           # an edit once dropped the bit and ./np said "permission denied"
        import os
        np = Path(__file__).resolve().parent.parent / "np"
        self.assertTrue(os.access(np, os.X_OK), "run: chmod 755 np")


if __name__ == "__main__":
    unittest.main()
