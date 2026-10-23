"""The morning never re-runs the tests on code that already passed the full gate (2026-10-23: a test that looks
for a running daily run failed during the daily run and blocked the edition)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import release, releaser


class FastGate(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "pipeline").mkdir()
        (self.root / "pipeline" / "x.py").write_text("x = 1\n")
        (self.root / "data" / "state").mkdir(parents=True)
        self._env = os.environ.get("NP_ENV")
        os.environ["NP_ENV"] = "production"
        self.addCleanup(lambda: os.environ.__setitem__("NP_ENV", self._env) if self._env else os.environ.pop("NP_ENV", None))

    def fps(self):
        return release.fingerprint(release.CODE, self.root), release.fingerprint(release.SENSITIVE, self.root)

    def test_passed_and_approved_code_is_not_re_tested(self):
        fp, sfp = self.fps()
        (self.root / release.PASSED).write_text(json.dumps({"fingerprint": fp, "sensitive": sfp}) + "\n")
        boom = mock.Mock(side_effect=AssertionError("the gate re-ran"))
        with mock.patch.object(release, "run", boom), mock.patch.object(release, "check_approval", lambda r: (True, "")):
            release.require(self.root, {}, "today's publish and email")
        boom.assert_not_called()

    def test_changed_code_is_still_checked(self):
        fp, sfp = self.fps()
        (self.root / release.PASSED).write_text(json.dumps({"fingerprint": fp, "sensitive": sfp}) + "\n")
        (self.root / "pipeline" / "x.py").write_text("x = 2\n")
        rec = {"passed": False, "checks": {"tests": {"ok": False, "detail": "1 failed"}}}
        with mock.patch.object(release, "run", lambda *a, **k: rec), \
                mock.patch.object(release, "check_approval", lambda r: (True, "")):
            with self.assertRaises(release.ReleaseBlocked):
                release.require(self.root, {}, "today's publish and email")

    def test_unapproved_code_is_not_waved_through(self):
        fp, sfp = self.fps()
        (self.root / release.PASSED).write_text(json.dumps({"fingerprint": fp, "sensitive": sfp}) + "\n")
        rec = {"passed": False, "checks": {"approval": {"ok": False, "detail": "not approved"}}}
        with mock.patch.object(release, "run", lambda *a, **k: rec), \
                mock.patch.object(release, "check_approval", lambda r: (False, "not approved")):
            with self.assertRaises(release.ReleaseBlocked):
                release.require(self.root, {}, "today's publish and email")

    def test_tests_never_see_live_runs(self):
        with mock.patch.dict(os.environ, {"NP_TESTING": "1"}), mock.patch("subprocess.run") as sp:
            self.assertFalse(releaser.run_in_progress(self.root))
            sp.assert_not_called()

    def test_pre_push_hook_uses_the_fast_check(self):
        self.assertIn("run.py --release-check require", release.HOOKS["pre-push"])


if __name__ == "__main__":
    unittest.main()
