"""The development checkout (pipeline/devenv.py): a staging worktree that never writes production."""
import datetime as dt
import os
import subprocess
import tempfile
import unittest

for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):   # GIT_LOCATION: a leaked GIT_DIR once
    os.environ.pop(_k, None)                                                        # pointed temp-repo git at production
from pathlib import Path

from pipeline import archive, devenv, env


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True,
                          text=True)


class DevCheckout(unittest.TestCase):
    def setUp(self):
        os.environ.pop("NP_ENV", None)
        base = Path(tempfile.mkdtemp())
        self.prod = base / "news-pipeline"
        (self.prod / "briefings").mkdir(parents=True)
        (self.prod / "data").mkdir()
        (self.prod / "pipeline").mkdir()
        (self.prod / "briefings" / "2026-10-21.md").write_text("# a\n")
        (self.prod / "data" / "x.jsonl").write_text("1\n")
        (self.prod / "pipeline" / "code.py").write_text("x = 1\n")
        git(self.prod, "init", "-q", "-b", "main")
        git(self.prod, "add", "-A")
        git(self.prod, "commit", "-q", "-m", "init")
        self.dev = devenv.dev_path(self.prod, {})
        devenv.setup(self.prod, {}, log=lambda *_: None)

    def test_setup_makes_a_staging_worktree_on_dev(self):
        self.assertEqual(self.dev.name, "news-pipeline-dev")
        self.assertTrue(env.staging(self.dev))
        self.assertFalse(env.staging(self.prod))
        self.assertEqual(git(self.dev, "branch", "--show-current").stdout.strip(), "dev")
        self.assertEqual(devenv.production_root(self.dev).resolve(), self.prod.resolve())
        with self.assertRaises(devenv.DevError):
            devenv.setup(self.dev, {})                   # never from dev

    def test_sync_brings_production_data_and_reset_discards_staging_outputs(self):
        (self.prod / "briefings" / "2026-10-22.md").write_text("# b\n")
        git(self.prod, "add", "-A")
        git(self.prod, "commit", "-q", "--no-verify", "-m", "data")
        devenv.sync(self.dev, {}, log=lambda *_: None)
        self.assertTrue((self.dev / "briefings" / "2026-10-22.md").exists())
        self.assertEqual(devenv.latest_day(self.dev), "2026-10-22")
        (self.dev / "briefings" / "2026-10-22.md").write_text("# staging rewrite\n")
        (self.dev / "data" / "new.jsonl").write_text("x\n")
        devenv.reset(self.dev)
        self.assertEqual((self.dev / "briefings" / "2026-10-22.md").read_text(), "# b\n")
        self.assertFalse((self.dev / "data" / "new.jsonl").exists())
        self.assertEqual((self.prod / "briefings" / "2026-10-22.md").read_text(), "# b\n")   # production untouched
        with self.assertRaises(devenv.DevError):
            devenv.reset(self.prod)

    def test_hook_refuses_data_commits_in_staging_but_not_code(self):
        (self.dev / "data" / "x.jsonl").write_text("2\n")
        git(self.dev, "add", "data/x.jsonl")
        self.assertNotEqual(git(self.dev, "commit", "-q", "-m", "data").returncode, 0)
        git(self.dev, "reset", "-q")
        git(self.dev, "checkout", "--", "data")
        (self.dev / "pipeline" / "code.py").write_text("x = 2\n")
        git(self.dev, "add", "pipeline/code.py")
        r = git(self.dev, "commit", "-q", "-m", "code")
        self.assertNotIn("staging: data paths", r.stdout + r.stderr)

    def test_archive_never_commits_in_staging(self):
        self.assertEqual(archive.Archive.git_commit(type("A", (), {"root": self.dev})(), "x"), "not committed (staging)")

    def test_production_window(self):
        with self.assertRaises(devenv.DevError):
            devenv.check_window(now=dt.datetime(2026, 10, 22, 5, 0))
        devenv.check_window(now=dt.datetime(2026, 10, 22, 14, 0))
        devenv.check_window(force=True, now=dt.datetime(2026, 10, 22, 5, 0))


if __name__ == "__main__":
    unittest.main()
