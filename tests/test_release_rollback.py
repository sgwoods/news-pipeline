"""A failed release rolls back without wiping local, uncommitted edits (2026-11-02: reset --hard lost production's
uncommitted newsletters.yaml/config.yaml edits, and the next morning's edition was held at the approval gate)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import releaser


def git(root, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


class Rollback(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        git(self.root, "init", "-q", "-b", "main")
        (self.root / "code.py").write_text("v1\n")
        (self.root / "newsletters.yaml").write_text("committed\n")
        git(self.root, "add", "-A"); git(self.root, "commit", "-q", "-m", "base")
        git(self.root, "checkout", "-q", "-b", "dev")
        (self.root / "code.py").write_text("v2\n")
        git(self.root, "commit", "-q", "-am", "dev change")
        git(self.root, "checkout", "-q", "main")
        self.pre = git(self.root, "rev-parse", "HEAD")

    def test_local_edit_survives_rollback(self):
        (self.root / "newsletters.yaml").write_text("local edit, never committed\n")
        git(self.root, "merge", "-q", "--no-ff", "dev", "-m", "release")
        releaser._rollback(self.root, self.pre)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.pre)
        self.assertEqual((self.root / "code.py").read_text(), "v1\n")
        self.assertEqual((self.root / "newsletters.yaml").read_text(), "local edit, never committed\n")


if __name__ == "__main__":
    unittest.main()
