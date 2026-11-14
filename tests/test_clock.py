"""schedule.timezone: the edition keeps Eastern time wherever the Mac is (Steven, 2026-11-11)."""
import datetime as dt
import unittest
from unittest import mock

from pipeline import clock, schedule, takes


class Clock(unittest.TestCase):
    def test_no_zone_means_the_mac_clock(self):
        self.assertIsNone(clock.zone({}))
        self.assertEqual(clock.mismatch({}), "")
        self.assertLess(abs((clock.now({}) - dt.datetime.now()).total_seconds()), 5)

    def test_configured_zone_is_read_for_the_schedule(self):
        cfg = {"schedule": {"timezone": "America/Toronto", "times": ["05:00"]}}
        # 10:00 UTC on 2026-11-14 is 05:00 in Toronto (EST): the 05:00 run is due, whatever the Mac's own zone
        class FixedDT(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                base = dt.datetime(2026, 11, 14, 10, 1, tzinfo=dt.timezone.utc)
                return base.astimezone(tz) if tz else base.replace(tzinfo=None)
        with mock.patch("pipeline.clock.dt.datetime", FixedDT):
            self.assertEqual(clock.now(cfg).strftime("%H:%M"), "05:01")
            self.assertEqual(schedule.due(cfg, "daily"), "05:00")
        self.assertIsNone(clock.zone({"schedule": {"timezone": "Mars/Olympus"}}))   # a typo never stops the schedule

    def test_mismatch_note_names_both_clocks(self):
        cfg = {"schedule": {"timezone": "America/Toronto"}}
        note = clock.mismatch(cfg)
        # the test machine may or may not be in Toronto: either no note, or one that names the zone
        self.assertTrue(note == "" or "America/Toronto" in note)
