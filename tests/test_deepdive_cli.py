"""10-31: a subcommand that takes arguments gets every flag after it (`./np deepdive DAY --topic "..." --force`,
`./np staging run --force`). No config file needed (the public export has none)."""
import sys
import unittest
from unittest import mock

import run

CFG = {"paths": {"briefings": "briefings", "logs": "logs"}}


class SubcommandArgs(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(run, "load_config", return_value=CFG)
        p.start()
        self.addCleanup(p.stop)

    def test_topic_and_force_reach_the_deep_dive(self):
        got = {}
        argv = ["run.py", "--deepdive", "2026-10-31", "--topic", "Who's liable?", "--force"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(run, "cmd_deepdive", side_effect=lambda cfg, a: got.setdefault("a", a) and 0):
            run.main()
        self.assertEqual(got["a"], ["2026-10-31", "--topic", "Who's liable?", "--force"])

    def test_staging_run_force_reaches_staging(self):
        got = {}
        with mock.patch.object(sys, "argv", ["run.py", "--staging", "run", "--force"]), \
                mock.patch.object(run, "cmd_staging", side_effect=lambda cfg, a: got.setdefault("a", a) and 0):
            run.main()
        self.assertEqual(got["a"], ["run", "--force"])


if __name__ == "__main__":
    unittest.main()
