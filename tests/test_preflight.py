"""A held-back morning: later scheduled runs send what the release gate blocked; the evening check warns first."""
import unittest
from pathlib import Path
from unittest import mock

import run
from pipeline import service

CFG = {"email": {"enabled": True, "editor_note": True}, "publish": {"auto": True},
       "email_sources": {"enabled": True, "day_labels": True}, "paths": {"runs": "data/runs.jsonl"}}


def setUpModule():                      # the commands print progress; keep the test output (and the release gate's) clean
    global _p
    _p = mock.patch("builtins.print", lambda *a, **k: None)
    _p.start()


def tearDownModule():
    _p.stop()


class Retry(unittest.TestCase):
    def test_sends_once_the_gate_passes(self):
        calls = []
        with mock.patch("pipeline.mailer.sent_days", lambda root: set()), \
                mock.patch("pipeline.release.require", lambda *a, **k: None), \
                mock.patch.object(run, "cmd_publish", lambda cfg: calls.append("publish")), \
                mock.patch.object(run, "cmd_email", lambda cfg, a: calls.append(tuple(a))), \
                mock.patch.object(run, "cmd_newsletters", lambda cfg, a: calls.append(tuple(a))), \
                mock.patch("pipeline.editor_note.send", lambda *a: calls.append("note") or {"skipped": "x"}), \
                mock.patch.object(run, "_notify", lambda *a: None):
            run._retry_outbound(CFG, "2026-10-17")
        self.assertEqual(calls, ["publish", ("send", "2026-10-17"), "note", ("label", "2026-10-17")])

    def test_nothing_when_already_sent_or_still_blocked(self):
        calls = []
        with mock.patch("pipeline.mailer.sent_days", lambda root: {"2026-10-17"}), \
                mock.patch.object(run, "cmd_email", lambda cfg, a: calls.append(a)):
            run._retry_outbound(CFG, "2026-10-17")
        with mock.patch("pipeline.mailer.sent_days", lambda root: set()), \
                mock.patch("pipeline.release.require", side_effect=RuntimeError("blocked")), \
                mock.patch.object(run, "cmd_email", lambda cfg, a: calls.append(a)), \
                mock.patch.object(run, "_notify", lambda *a: calls.append("notified")):
            run._retry_outbound(CFG, "2026-10-17")
        self.assertEqual(calls, ["notified"])


class Preflight(unittest.TestCase):
    def test_evening_job_and_notice(self):
        pl = service.build_plist("preflight", Path("/x"), {"schedule": {"preflight": "21:15"}})
        self.assertEqual(pl["ProgramArguments"][-1], "preflight")
        self.assertEqual(pl["StartCalendarInterval"], [{"Hour": 21, "Minute": 15}])
        seen = []
        with mock.patch("pipeline.release.check_approval", lambda root: (False, "changed")), \
                mock.patch("pipeline.release.changed_sensitive", lambda root: ["pipeline/site.py"]), \
                mock.patch.object(run, "_notify", lambda t, m: seen.append(m)):
            self.assertEqual(run.cmd_preflight({}), 1)
        self.assertIn("pipeline/site.py", seen[0])


if __name__ == "__main__":
    unittest.main()
