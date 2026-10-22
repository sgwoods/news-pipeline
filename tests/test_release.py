import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline import release


class Gate(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=self.root)
        (self.root / ".gitignore").write_text(".env\ndata/inbox/\n")

    def test_secret_scan(self):
        (self.root / "ok.py").write_text("token = os.environ.get('SLACK_USER_TOKEN')\n")
        fake = "xo" + "xp-" + "1234567890" + "-abcdefghijkl"            # built at runtime so this file passes the scan
        (self.root / "bad.txt").write_text(f"SLACK_USER_TOKEN={fake}\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root)
        ok, d = release.check_secrets(self.root)
        self.assertFalse(ok)
        self.assertIn("bad.txt", d)
        self.assertNotIn("ok.py", d)

    def test_require_blocks_when_gate_fails(self):
        (self.root / "data/state").mkdir(parents=True)
        (self.root / release.STATE).write_text(json.dumps({"passed": False}))
        orig = release.run
        release.run = lambda root, cfg, **k: {"passed": False, "checks": {"secrets": {"ok": False, "detail": "leak"}}}
        try:
            with self.assertRaises(release.ReleaseBlocked) as e:
                release.require(self.root, {}, "site publish", log=lambda *a: None)
            self.assertIn("site publish blocked", str(e.exception))
        finally:
            release.run = orig

    def test_require_passes_for_recorded_code(self):
        (self.root / "data/state").mkdir(parents=True)
        (self.root / release.STATE).write_text(json.dumps({"passed": True, "fingerprint": release.fingerprint(release.CODE, self.root),
                                                           "sensitive": release.fingerprint(release.SENSITIVE, self.root)}))
        release.require(self.root, {}, "email send", log=lambda *a: None)       # no exception, no re-run

    def test_approval_needed_for_sensitive_change(self):
        (self.root / "pipeline").mkdir()
        (self.root / "pipeline/mailsource.py").write_text("x = 1\n")
        self.assertFalse(release.check_approval(self.root)[0])
        (self.root / "docs/security").mkdir(parents=True)
        (self.root / release.APPROVALS).write_text(json.dumps([{"sensitive": release.fingerprint(release.SENSITIVE, self.root)}]))
        self.assertTrue(release.check_approval(self.root)[0])
        (self.root / "pipeline/mailsource.py").write_text("x = 2\n")
        self.assertFalse(release.check_approval(self.root)[0])

    def test_invariants_hold_in_this_repo(self):
        ok, d = release.check_invariants(release.ROOT)
        self.assertTrue(ok, d)


if __name__ == "__main__":
    unittest.main()


class Approval(unittest.TestCase):
    def test_needs_a_terminal(self):
        with self.assertRaises(release.ReleaseBlocked) as e:
            release.approve(Path(tempfile.mkdtemp()), {}, "looked at it", interactive=False)
        self.assertIn("person at a terminal", str(e.exception))
