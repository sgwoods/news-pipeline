"""Scheduled jobs run by the local clock (pipeline/schedule.py), not by launchd's idea of local time."""
import datetime as dt
import unittest
from pathlib import Path

from pipeline import schedule, service

CFG = {"schedule": {"times": ["05:00", "06:30", "07:30"], "preflight": "20:30"}}


def at(h, m):
    return dt.datetime(2026, 10, 23, h, m, 5)


class Schedule(unittest.TestCase):
    def test_exactly_one_half_hour_tick_matches_each_time(self):
        ticks = [at(h, m) for h in range(24) for m in schedule.TICK_MINUTES]
        daily = [t for t in ticks if schedule.due(CFG, "daily", t)]
        self.assertEqual([t.strftime("%H:%M") for t in daily], ["05:00", "06:30", "07:30"])
        pre = [t for t in ticks if schedule.due(CFG, "preflight", t)]
        self.assertEqual([t.strftime("%H:%M") for t in pre], ["20:30"])

    def test_the_old_one_hour_early_fire_is_not_due(self):
        self.assertEqual(schedule.due(CFG, "daily", at(4, 0)), "")
        self.assertEqual(schedule.due(CFG, "preflight", at(19, 30)), "")

    def test_a_late_tick_after_sleep_still_counts_within_the_half_hour(self):
        self.assertEqual(schedule.due(CFG, "daily", at(5, 25)), "05:00")
        self.assertEqual(schedule.due(CFG, "daily", at(5, 31)), "")

    def test_plist_ticks_every_half_hour_and_calls_scheduled(self):
        p = service.build_plist("daily", Path("/x"), CFG)
        self.assertEqual(p["StartCalendarInterval"], [{"Minute": 0}, {"Minute": 30}])
        self.assertEqual(p["ProgramArguments"][-2:], ["scheduled", "daily"])
        self.assertNotIn("Hour", str(p))
        q = service.build_plist("preflight", Path("/x"), CFG)
        self.assertEqual(q["ProgramArguments"][-2:], ["scheduled", "preflight"])

    def test_times_must_be_on_the_tick(self):
        self.assertEqual(schedule.check(CFG), [])
        self.assertEqual(schedule.check({"schedule": {"times": ["05:15"]}}), ["05:15"])


class Rebrief(unittest.TestCase):
    def test_rebrief_keeps_the_critique_model_for_verify(self):      # staging run 2026-10-22: KeyError 'critique'
        import run
        self.assertIn("critique", run.llm_stage_names({}, rebrief=True))
        self.assertNotIn("filter", run.llm_stage_names({}, rebrief=True))
        self.assertEqual(run.llm_stage_names({}), ["filter", "rank", "critique", "cluster", "merge", "editorial", "write"])


if __name__ == "__main__":
    unittest.main()
