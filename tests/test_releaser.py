"""Release and rollback (pipeline/releaser.py) on a throwaway repository with a dev worktree."""
import datetime as dt
import os
import subprocess
import tempfile
import unittest

for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):   # GIT_LOCATION: a leaked GIT_DIR once
    os.environ.pop(_k, None)                                                        # pointed temp-repo git at production
from pathlib import Path
from unittest import mock

from pipeline import devenv, release, releaser

NOON = dt.datetime(2026, 10, 22, 12, 0)


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True)


def commit(cwd, msg):
    git(cwd, "add", "-A")
    return git(cwd, "-c", "core.hooksPath=/dev/null", "commit", "-q", "--no-verify", "-m", msg)


class Releases(unittest.TestCase):
    def setUp(self):
        os.environ.pop("NP_ENV", None)
        for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            os.environ.setdefault(k, "t")
        for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            os.environ.setdefault(k, "t@t")
        self.prod = Path(tempfile.mkdtemp()) / "news-pipeline"
        (self.prod / "pipeline").mkdir(parents=True)
        (self.prod / "data" / "state").mkdir(parents=True)
        (self.prod / ".gitignore").write_text(".staging\n.venv\n")
        (self.prod / "VERSION").write_text("0.1.0-beta\n")
        (self.prod / "CHANGELOG.md").write_text("# Changelog\n\n## v0.1.0-beta\n- first\n")
        (self.prod / "pipeline" / "code.py").write_text("x = 1\n")
        git(self.prod, "init", "-q", "-b", "main")
        commit(self.prod, "init")
        git(self.prod, "tag", "-a", "v0.1.0-beta", "-m", "x")
        with mock.patch.object(release, "install_hooks", lambda root: []):
            devenv.setup(self.prod, {}, log=lambda *_: None)
        self.dev = devenv.dev_path(self.prod, {})
        (self.dev / "pipeline" / "code.py").write_text("x = 2\n")
        (self.dev / "VERSION").write_text("0.2.0-beta\n")
        (self.dev / "CHANGELOG.md").write_text("# Changelog\n\n## v0.2.0-beta\n- second\n\n## v0.1.0-beta\n- first\n")
        commit(self.dev, "feature")
        self.ok = mock.patch.object(release, "approve", lambda *a, **k: {"passed": True})
        self.nocommit = mock.patch("pipeline.archive.Archive.git_commit", lambda *a, **k: "ok")

    def test_promote_then_rollback(self):
        with self.ok, self.nocommit:
            r = releaser.promote(self.prod, {}, "0.2.0-beta", "reviewed: feature", now=NOON)
            self.assertEqual((r["version"], r["previous"]), ("0.2.0-beta", "0.1.0-beta"))
            self.assertEqual((self.prod / "pipeline" / "code.py").read_text(), "x = 2\n")
            self.assertEqual(git(self.prod, "tag", "-l", "v0.2.0-beta").stdout.strip(), "v0.2.0-beta")
            with self.assertRaises(releaser.ReleaseError):
                releaser.promote(self.prod, {}, "0.2.0-beta", "reviewed: again", now=NOON)
            b = releaser.rollback(self.prod, {}, "reviewed: canary failed")
        self.assertEqual(b["version"], "0.1.0-beta")
        self.assertEqual((self.prod / "pipeline" / "code.py").read_text(), "x = 1\n")
        self.assertEqual((self.prod / "VERSION").read_text().strip(), "0.1.0-beta")
        self.assertEqual([h["kind"] for h in releaser.history(self.prod)], ["release", "rollback"])

    def test_refusals(self):
        with self.ok, self.nocommit:
            with self.assertRaises(releaser.ReleaseError):            # outside 08:30-20:00
                releaser.promote(self.prod, {}, "0.2.0-beta", "reviewed: x", now=dt.datetime(2026, 10, 22, 22, 0))
            with self.assertRaises(releaser.ReleaseError):            # dev is at a different version
                releaser.promote(self.prod, {}, "0.3.0", "reviewed: x", now=NOON)
            with self.assertRaises(releaser.ReleaseError):            # a note is required
                releaser.promote(self.prod, {}, "0.2.0-beta", "ok", now=NOON)
            (self.dev / "x").write_text("")
            git(self.dev, "add", "-f", ".staging")
            commit(self.dev, "oops: staging marker")
            with self.assertRaises(releaser.ReleaseError) as cm:      # a committed staging marker never reaches main
                releaser.promote(self.prod, {}, "0.2.0-beta", "reviewed: x", now=NOON)
            self.assertIn(".staging", str(cm.exception))
            with self.assertRaises(releaser.ReleaseError):            # never from dev
                releaser.promote(self.dev, {}, "0.2.0-beta", "reviewed: x", now=NOON)
            (self.prod / "pipeline" / "code.py").write_text("x = 9\n")
            with self.assertRaises(releaser.ReleaseError):            # production has stray code changes
                releaser.promote(self.prod, {}, "0.2.0-beta", "reviewed: x", now=NOON)

    def test_a_failed_gate_leaves_production_unchanged(self):
        pre = git(self.prod, "rev-parse", "HEAD").stdout.strip()
        with mock.patch.object(release, "approve", lambda *a, **k: {"passed": False}), self.nocommit:
            with self.assertRaises(releaser.ReleaseError):
                releaser.promote(self.prod, {}, "0.2.0-beta", "reviewed: x", now=NOON)
        self.assertEqual(git(self.prod, "rev-parse", "HEAD").stdout.strip(), pre)
        self.assertEqual((self.prod / "pipeline" / "code.py").read_text(), "x = 1\n")


if __name__ == "__main__":
    unittest.main()
