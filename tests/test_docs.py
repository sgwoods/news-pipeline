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

    def test_every_public_module_is_described_in_a_hand_written_doc(self):
        missing = [m for m, where in docs.described(ROOT).items() if not where]
        self.assertEqual(missing, [], "describe these modules in docs/ARCHITECTURE.md (or another doc)")

    def test_every_diagram_exists_and_is_used(self):
        text = " ".join(p.read_text("utf-8") for p in (ROOT / "docs").glob("*.md"))
        used = set(re.findall(r"img/([\w-]+\.svg)", text))
        have = {p.name for p in (ROOT / "docs" / "img").glob("*.svg")}
        self.assertEqual(used - have, set(), "a doc shows a diagram that doesn't exist")
        self.assertEqual(have - used, set(), "a diagram no doc shows")

    def test_impact_lists_changed_modules_whose_docs_did_not_change(self):
        import os
        import subprocess
        d = Path(tempfile.mkdtemp())
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        git = lambda *a: subprocess.run(["git", *a], cwd=d, env=env, capture_output=True, check=True)  # noqa: E731
        (d / "pipeline").mkdir()
        (d / "docs").mkdir()
        (d / "owner.example.yaml").write_text("export_exclude: []\n", "utf-8")
        (d / "pipeline" / "alpha.py").write_text('"""Alpha."""\n', "utf-8")
        (d / "pipeline" / "beta.py").write_text('"""Beta."""\n', "utf-8")
        (d / "pipeline" / "gamma.py").write_text('"""Gamma."""\n', "utf-8")
        (d / "docs" / "A.md").write_text("`alpha.py` does a.\n", "utf-8")
        (d / "docs" / "B.md").write_text("`beta.py` does b.\n", "utf-8")
        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "x", "--allow-empty")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        git("tag", "base")
        for m in ("alpha", "beta", "gamma"):
            (d / "pipeline" / f"{m}.py").write_text(f'"""{m}, changed."""\n', "utf-8")
        (d / "docs" / "B.md").write_text("`beta.py` does b, now better.\n", "utf-8")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")
        rep = docs.impact(d, "base", "HEAD")
        self.assertEqual([s["module"] for s in rep["stale"]], ["alpha.py"])
        self.assertEqual(rep["undocumented"], ["gamma.py"])
        self.assertIn("alpha.py", docs.impact_line(rep))

    def test_critic_section_from_the_latest_run(self):
        import json
        from pipeline import critic
        d = Path(tempfile.mkdtemp())
        keys = [k for k, _, _ in critic.DIMS]
        critic.save(d, {"date": "2026-10-24", "shows": [{"name": "Alpha Show", "episode": "Ep 1", "date": "2026-10-23",
                                                        "scores": {k: 8 for k in keys}}],
                        "ours": {"scores": {k: 6 for k in keys}}})
        out = docs.expand("<!-- GENERATED: critic -->", d, {})
        self.assertIn("| 1 | Alpha Show | 80.0 |", out)
        self.assertIn("| 2 | **AI Briefing (us)** | **60.0** |", out)
        self.assertIn("| Content selection (18) | 6 | 8.0 | 8 (Alpha Show) |", out)
        self.assertIn("No critic results yet", docs.expand("<!-- GENERATED: critic -->", Path(tempfile.mkdtemp()), {}))
        page = (ROOT / "docs" / "CRITIC.md").read_text("utf-8")    # the public export has it expanded already
        self.assertTrue("GENERATED: critic" in page or "| Characteristic (weight) | Us |" in page or
                        "No critic results yet" in page)


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
