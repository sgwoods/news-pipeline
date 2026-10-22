"""Public docs (pipeline/docs.py): built on the site at every publish, with generated sections and drift checks."""
import re
import tempfile
import unittest
from pathlib import Path

from pipeline import docs, site, version

ROOT = Path(__file__).resolve().parent.parent
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text("utf-8")


class DocsDrift(unittest.TestCase):
    def test_architecture_names_the_running_version(self):
        self.assertIn(version.short(), ARCH, "update docs/ARCHITECTURE.md's 'as of' line for this release")

    def test_every_module_it_names_exists(self):
        names = set(re.findall(r"`(\w+\.py)`", ARCH))
        missing = [n for n in names if not (ROOT / "pipeline" / n).exists() and not (ROOT / "dashboard" / n).exists()]
        self.assertEqual(missing, [], "docs/ARCHITECTURE.md names modules that no longer exist")

    def test_generated_sections_cover_every_public_module(self):
        out = docs.expand(ARCH, ROOT, {"schedule": {"times": ["05:00"]}})
        self.assertNotIn("<!-- GENERATED", out)
        for m, _ in docs.public_modules(ROOT):
            self.assertIn(f"`{m}`", out)
        self.assertNotIn("`company.py`", out)
        self.assertIn("v" + version.full(), out)


class DocsSite(unittest.TestCase):
    def test_build_pages_with_diagrams_and_no_private_terms(self):
        out = Path(tempfile.mkdtemp())
        n = docs.build(ROOT, {"code_repo": "someone/code"}, out, site._page)
        self.assertGreaterEqual(n, 1)
        pg = (out / "docs" / "architecture.html").read_text("utf-8")
        self.assertIn('src="img/system-overview.svg"', pg)
        self.assertTrue((out / "docs" / "img" / "system-overview.svg").exists())
        self.assertIn("this page last changed", pg)
        self.assertIn('href="architecture.html"', (out / "docs" / "index.html").read_text("utf-8"))
        try:
            from pipeline import export                       # the private repo: scan with the private terms
        except ImportError:
            return
        from pipeline.owner import get
        self.assertEqual(export.scan(out, export.private_terms(ROOT, get(ROOT))), [])


if __name__ == "__main__":
    unittest.main()
