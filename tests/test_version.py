"""VERSION, release notes, and the version shown on the site footer and the releases page."""
import tempfile
import unittest
from pathlib import Path

from pipeline import site, version


class Version(unittest.TestCase):
    def test_labels(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(version.full(d), "dev")
        (d / "VERSION").write_text("0.1.0-beta\n")
        self.assertEqual((version.full(d), version.short(d), version.tag(d)), ("0.1.0-beta", "v0.1 beta", "v0.1.0-beta"))
        (d / "VERSION").write_text("1.2.3\n")
        self.assertEqual(version.short(d), "v1.2")

    def test_releases_skip_unreleased(self):
        d = Path(tempfile.mkdtemp())
        (d / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n- wip\n\n## v0.2.0 · 2026-11-01\n- b\n\n## v0.1.0-beta · 2026-10-22\n- a\n")
        self.assertEqual([h for h, _ in version.releases(d)], ["v0.2.0 · 2026-11-01", "v0.1.0-beta · 2026-10-22"])

    def test_footer_and_releases_page(self):
        cfg = {"code_repo": "someone/code"}
        page = site._page("t", "<p>x</p>", "../", cfg)
        self.assertIn('href="../releases/index.html">' + version.short() + "</a>", page)
        self.assertIn('href="https://github.com/someone/code">Code</a>', page)
        rel = site.releases_page(cfg)
        self.assertIn("Release notes", rel)
        self.assertNotIn("Unreleased", rel)

    def test_this_repo_has_a_version_and_its_notes(self):
        self.assertRegex(version.full(), r"^\d+\.\d+\.\d+")
        self.assertIn(version.tag(), [h.split(" ")[0] for h, _ in version.releases()])


if __name__ == "__main__":
    unittest.main()
