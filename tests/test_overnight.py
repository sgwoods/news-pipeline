"""Overnight work (Steven, 2026-11-03): analysis runs through the night, a nightly rehearsal of the dev code lets a
ship skip its soak, the approval prompt comes the evening before, and the home page shows one edition flow."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import runner, schedule, service


def at(h, m, day=3):
    return dt.datetime(2026, 11, day, h, m)


class Schedule(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(schedule.times({}, "overnight"), ["23:30", "01:30", "03:30"])
        self.assertEqual(schedule.times({}, "rehearsal"), ["00:30"])
        self.assertEqual(schedule.times({}, "preflight"), ["21:00", "23:00"])
        self.assertEqual(schedule.times({"schedule": {"preflight": "20:30"}}, "preflight"), ["20:30"])
        self.assertEqual(schedule.check({}), [])

    def test_due_each_slot_once(self):
        ticks = [at(h, m) for h in range(24) for m in (0, 30)]
        self.assertEqual([t.strftime("%H:%M") for t in ticks if schedule.due({}, "overnight", t)],
                         ["01:30", "03:30", "23:30"])
        self.assertEqual(schedule.due({}, "rehearsal", at(0, 30)), "00:30")

    def test_plists(self):
        for kind in ("overnight", "rehearsal"):
            p = service.build_plist(kind, Path("/x"), {})
            self.assertEqual(p["ProgramArguments"][-2:], ["scheduled", kind])
            self.assertIn(kind, service.LABELS)


class Rehearsal(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.dev = Path(tempfile.mkdtemp())
        (self.dev / "pipeline").mkdir()
        (self.dev / "pipeline" / "x.py").write_text("A = 1\n")

    def make(self, now, sent=True, busy=False):
        return runner.Runner(self.root, self.dev, {}, now=lambda: now, notify=None, sent_today=lambda: sent,
                             busy=lambda: busy)

    def test_record_and_match(self):
        runner.record_rehearsal(self.root, self.dev, now=at(0, 50))
        self.assertTrue(self.make(at(9, 0)).rehearsed())
        self.assertFalse(self.make(at(21, 0)).rehearsed())                   # over 20 hours old
        (self.dev / "pipeline" / "x.py").write_text("A = 2\n")              # dev changed after the rehearsal
        self.assertFalse(self.make(at(9, 0)).rehearsed())

    def test_no_record_means_full_soak(self):
        self.assertFalse(self.make(at(9, 0)).rehearsed())

    def test_rehearse_never_in_the_morning_or_during_a_run(self):
        job = {"id": "x", "recipe": "rehearse", "args": {}}
        self.assertIn("morning run", self.make(at(4, 0))._defer(job))
        self.assertIn("morning run", self.make(at(0, 30), busy=True)._defer(job))
        self.assertEqual(self.make(at(0, 30))._defer(job), "")

    def test_ship_recipe_has_the_soak_steps_to_skip(self):
        steps = runner.RECIPES["ship"]["steps"]
        self.assertIn(("dev", ["staging", "run", "--force", "--deepdive"]), steps)
        self.assertIn(("dev", ["staging", "compare"]), steps)
        self.assertEqual(runner.RECIPES["rehearse"]["steps"][-1], ("local", ["rehearsal-record"]))


class RehearseQueue(unittest.TestCase):
    def test_queues_one_rehearsal(self):
        """11-04: the first night's 00:30 rehearsal died on a missing import; this runs the real entry point."""
        import run
        calls = []
        orig = runner.enqueue
        runner.enqueue = lambda root, recipe, args=None, **k: calls.append(recipe) or Path("/tmp/x-rehearse.json")
        try:
            run.cmd_rehearse_queue({"dev": {"path": tempfile.mkdtemp()}})
        finally:
            runner.enqueue = orig
        self.assertIn(calls, ([], ["rehearse"]))                 # queued, or skipped cleanly; never a crash


class RebriefIds(unittest.TestCase):
    def test_includes_what_the_day_considered(self):
        """11-04: items first seen the evening before (overnight runs) must still be in a rebuild of the day."""
        import run
        root = Path(tempfile.mkdtemp())
        idx = root / "index.jsonl"
        idx.write_text(json.dumps({"id": "a", "first_seen": "2026-11-04"}) + "\n"
                       + json.dumps({"id": "b", "first_seen": "2026-11-03"}) + "\n")
        log = root / "briefings.jsonl"
        log.write_text(json.dumps({"day": "2026-11-04", "item_ids": ["b"], "considered_ids": ["b", "c"]}) + "\n"
                       + json.dumps({"day": "2026-11-04", "experiment": "x", "considered_ids": ["z"]}) + "\n")
        arch = type("A", (), {"index_path": idx})()
        self.assertEqual(run._rebrief_ids(arch, log, "2026-11-04"), {"a", "b", "c"})


class HomeFlow(unittest.TestCase):
    def test_flow_and_next_step(self):
        from pipeline import home
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-11-03.md").write_text("# AI Briefing · Tuesday\n\n- **A.** b\n")
        (root / "data" / "takes").mkdir(parents=True)
        e = home.edition(root, {}, "2026-11-03")
        self.assertEqual([f["name"] for f in e["flow"]], ["Built", "Takes", "Site", "Email", "Slack"])
        self.assertTrue(e["flow"][0]["done"])
        self.assertEqual(e["next"]["recipe"], "send-held")


if __name__ == "__main__":
    unittest.main()
