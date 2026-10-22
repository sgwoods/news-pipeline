import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import hub

CFG = {"publish": {"repo": "sgwoods/ai-briefing", "site_url": "https://sgwoods.github.io/ai-briefing/"},
       "code_repo": "sgwoods/news-pipeline"}
SRC = {"source_commit": "a" * 40, "source_commit_at": "2026-10-22T13:39:29Z", "source_ref": "v0.1.0-beta",
       "source_dirty": False}


class HubExport(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings" / "deepdives").mkdir(parents=True)
        for d in ("2026-10-17", "2026-10-18"):
            (self.root / "briefings" / f"{d}.md").write_text("# x\n")
        (self.root / "briefings" / "deepdives" / "2026-10-18.md").write_text("# x\n")

    def test_manifest_19_fields_in_contract_order(self):
        m = hub.manifest(self.root, CFG, SRC)
        self.assertEqual(tuple(m), hub.BASE_KEYS + hub.SOURCE_KEYS)
        self.assertEqual(len(m), 19)
        self.assertEqual(m["repo_url"], "https://github.com/sgwoods/news-pipeline")
        self.assertEqual(m["repo_pushed_at"], SRC["source_commit_at"])     # = source_commit_at, not publish time
        self.assertIs(m["source_dirty"], False)
        self.assertIsNone(m["dashboard_url"])
        self.assertEqual(m["status_label"], "Current release")
        self.assertEqual(m["status_value"], "v0.1.0-beta · edition 2026-10-18 + deep dive")
        txt = hub.dumps(m)
        self.assertTrue(txt.endswith("}\n"))
        self.assertIn('\n  "project_id": "ai-briefing"', txt)
        self.assertIn('"source_dirty": false', txt)
        json.loads(txt)

    def test_page_template_and_freshness_panel(self):
        m = hub.manifest(self.root, CFG, SRC)
        pg = hub.page(m, CFG, self.root)
        for s in ('href="assets/public-site.css"', '<script src="assets/project-freshness.js" defer></script>',
                  'class="shell shell--narrow"', 'class="heroHomeLink" href="index.html"',
                  'data-project-freshness="ai-briefing"', f'data-source-commit="{"a" * 40}"', 'data-source-dirty="false"',
                  'aria-live="polite"', 'href="index.html#repository-activity"',
                  'href="https://sgwoods.github.io/ai-briefing/#email"'):
            self.assertIn(s, pg)
        for bad in ("@gmail", "script.google", "127.0.0.1", "your firm", "subscribers"):
            self.assertNotIn(bad, pg)

    def test_source_refuses_without_a_release(self):
        with self.assertRaises(hub.HubExportError):
            hub.source(self.root, CFG, remote_check=False)          # no VERSION, no .public
        (self.root / "VERSION").write_text("0.1.0-beta\n")
        with self.assertRaises(hub.HubExportError):
            hub.source(self.root, CFG, remote_check=False)          # no public export
        pub = self.root / ".public"
        pub.mkdir()
        g = lambda *a: subprocess.run(["git", *a], cwd=pub, capture_output=True, check=True)  # noqa: E731
        g("init", "-q")
        (pub / "f").write_text("x")
        g("add", "f")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        with self.assertRaises(hub.HubExportError) as cm:
            hub.source(self.root, CFG, remote_check=False)          # export exists but no tag
        self.assertIn("v0.1.0-beta", str(cm.exception))

    def test_unchanged_apart_from_export_time_is_no_commit(self):
        a = hub.dumps({**hub.manifest(self.root, CFG, SRC), "status_generated_at": "2026-10-22T10:00:00Z"})
        b = hub.dumps({**hub.manifest(self.root, CFG, SRC), "status_generated_at": "2026-10-23T10:00:00Z"})
        self.assertTrue(hub._same(a, b))
        self.assertFalse(hub._same(a, a.replace("v0.1.0-beta", "v0.1.1-beta")))

    def test_push_refuses_paths_outside_the_allowlist(self):
        self.assertEqual(hub.ALLOW, ("data/projects/ai-briefing.json", "ai-briefing.html"))
        self.assertEqual(hub.MESSAGE, "Update public status manifest for ai-briefing")


class Shortcut(unittest.TestCase):
    def test_np_is_executable(self):           # an edit once dropped the bit and ./np said "permission denied"
        np = Path(__file__).resolve().parent.parent / "np"
        self.assertTrue(os.access(np, os.X_OK), "run: chmod 755 np")


if __name__ == "__main__":
    unittest.main()
