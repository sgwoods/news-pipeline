"""The development preview (staging site) and the staging-vs-production comparison."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
    os.environ.pop(_k, None)

from pipeline import audio, compare, publish, site  # noqa: E402

MD = ("# AI Briefing · x\n\n**The day in brief.** y\n\n## Top of mind\n- a [1](https://a.example/1)\n- b\n\n"
      "## Must read\n### 1. One\ntext [2](https://b.example/2)\n### 2. Two\nt\n\n## Open questions\n- q\n")


class Preview(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.get("NP_ENV")

    def tearDown(self):
        os.environ.pop("NP_ENV", None)
        if self._env is not None:
            os.environ["NP_ENV"] = self._env

    def test_banner_noindex_only_in_staging(self):
        cfg = {"publish": {"site_url": "https://prod.example/b/"}}
        os.environ["NP_ENV"] = "production"
        self.assertNotIn("Development preview", site._page("t", "<p>x</p>", "", cfg))
        os.environ["NP_ENV"] = "staging"
        pg = site._page("t", "<p>x</p>", "", cfg)
        self.assertIn("Development preview", pg)
        self.assertIn('content="noindex,nofollow"', pg)
        self.assertIn('href="https://prod.example/b/">Go to the published site', pg)
        self.assertEqual(site.staging_cfg({"email": {"script_url": "https://script.google.com/x"}})["email"]["script_url"], "")

    def test_staging_publishes_only_the_preview_repo(self):
        root = Path(tempfile.mkdtemp())
        os.environ["NP_ENV"] = "staging"
        cfg = {"publish": {"repo": "me/site", "staging_repo": "me/site-staging"}}
        for repo, flag in (("me/site", False), ("me/site", True), ("me/other", True)):
            with self.assertRaises(RuntimeError):
                publish.push(root, root, repo, "m", cfg, staging_site=flag)
        os.environ["NP_ENV"] = "production"
        with self.assertRaises(RuntimeError):
            publish.push(root, root, "me/site-staging", "m", cfg, staging_site=True)

    def test_no_icloud_delivery_in_staging(self):
        os.environ["NP_ENV"] = "staging"
        self.assertEqual(audio.deliver({"audio": {"icloud_dir": "/tmp"}}, Path("/nope.mp3"), None), "staging: not delivered")


class Compare(unittest.TestCase):
    def _root(self, md):
        r = Path(tempfile.mkdtemp())
        (r / "briefings").mkdir()
        (r / "briefings" / "2026-10-22.md").write_text(md)
        return r

    def test_same_shape_is_ok_and_missing_sections_are_flagged(self):
        prod, dev = self._root(MD), self._root(MD.replace("text", "other text"))
        with mock.patch("pipeline.version.full", lambda root=None: "0.1.6-beta"):
            r = compare.write(dev, prod, "2026-10-22")
        self.assertEqual(r["review"], [])
        self.assertTrue((dev / r["file"]).exists())
        self.assertIn("other text", (dev / r["file"]).read_text())
        bad = self._root(MD.split("## Must read")[0])
        r2 = compare.write(bad, prod, "2026-10-22")
        self.assertTrue(any("sections missing" in x for x in r2["review"]))
        self.assertTrue(any("must read" in x for x in r2["review"]))


if __name__ == "__main__":
    unittest.main()
