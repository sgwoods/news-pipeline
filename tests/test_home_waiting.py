"""The home page says plainly whether anything is waiting on Steven (2026-11-04), what is running now, and what is
queued, so a release running in the background never reads like a decision."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import home, runner


class Waiting(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        runner.qdir(self.root, "pending").mkdir(parents=True, exist_ok=True)

    def test_running_job_is_not_listed_as_queued(self):
        job = {"id": "20261104-0731-ship-0.2.54", "recipe": "ship", "args": {"version": "0.2.54-beta"},
               "started": "2026-11-04T08:08:00", "deferred": "the morning run's window or a run in progress"}
        (runner.qdir(self.root, "pending") / f"{job['id']}.json").write_text(json.dumps(job))
        runner._running(self.root, job, 2, 8, "staging run --force --deepdive")
        r = home.now_running(self.root)
        self.assertEqual((r["name"], r["step"], r["total"]), ("release 0.2.54-beta", 3, 8))
        self.assertIn("rebuilding today's edition", r["what"])
        self.assertFalse([n for n in home.needs(self.root, {}, "2026-11-04") if "0.2.54" in n["text"]])
        runner._running(self.root, None)
        q = [n for n in home.needs(self.root, {}, "2026-11-04") if n["level"] == "queued"]
        self.assertEqual(len(q), 1)
        self.assertIn("release 0.2.54-beta", q[0]["text"])

    def test_finish_clears_running(self):
        job = {"id": "j", "recipe": "tests", "args": {}}
        runner._running(self.root, job, 0, 1, "tests")
        runner._finish(self.root, self.root / "nope.json", dict(job), "ok")
        self.assertIsNone(runner.running(self.root))


if __name__ == "__main__":
    unittest.main()
