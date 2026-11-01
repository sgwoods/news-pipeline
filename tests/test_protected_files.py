import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import release, runner


class ProtectedCommitTest(unittest.TestCase):
    def test_main_refuses_protected_files(self):
        self.assertEqual(release.protected_staged(["house_views.md", "data/x.json"], "main", {}), ["house_views.md"])
        self.assertEqual(release.protected_staged(["pipeline/site.py"], "main", {}), ["pipeline/site.py"])

    def test_release_dev_and_data_pass(self):
        self.assertEqual(release.protected_staged(["house_views.md"], "main", {"NP_RELEASE": "1"}), [])
        self.assertEqual(release.protected_staged(["house_views.md"], "dev", {}), [])
        self.assertEqual(release.protected_staged(["data/critic/2026-10-31.json", "briefings/x.md"], "main", {}), [])

    def test_hook_calls_the_check(self):
        self.assertIn("protected_staged", release.HOOKS["pre-commit"])


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.now = dt.datetime(2026, 11, 1, 1, 0)
        self.sent = []

    def _run(self, ok):
        with mock.patch.object(release, "approvals", return_value=[{"sensitive": "fp0"}]), \
                mock.patch.object(release, "check_approval", return_value=(ok, "")), \
                mock.patch.object(release, "fingerprint", return_value="fp1"), \
                mock.patch.object(release, "changed_sensitive", return_value=["house_views.md"]):
            return runner._watch_protected(self.root, self.now, lambda t, x: self.sent.append((t, x)))

    def test_quiet_when_approved(self):
        self.assertEqual(self._run(True), "")
        self.assertEqual(self.sent, [])

    def test_once_per_change_and_queues_an_approval(self):
        self.assertEqual(self._run(False), "approval queued")
        self.assertEqual(self._run(False), "")            # the same change: no second notice
        self.assertEqual(len(self.sent), 1)
        self.assertIn("house_views.md", self.sent[0][1])
        jobs = [json.loads(p.read_text()) for p in runner.qdir(self.root, "pending").glob("*.json")]
        self.assertEqual([j["recipe"] for j in jobs], ["approve"])
        self.assertTrue(jobs[0]["args"]["note"].startswith("reviewed:"))

    def test_no_approval_job_when_a_release_is_queued(self):
        runner.qdir(self.root, "pending").mkdir(parents=True, exist_ok=True)
        (runner.qdir(self.root, "pending") / "x-ship.json").write_text(json.dumps({"recipe": "ship"}))
        self.assertEqual(self._run(False), "noticed (a release is queued)")


if __name__ == "__main__":
    unittest.main()
