"""v0.2.33 (Steven 2026-10-30: "stability day to day now as opposed to constant change"): one batched ship per
weekday from the 13:00 slot, a fix lane for broken things, and a soak (today's edition with the dev code, compared
with production) that stops a ship before Approve unless the flags are accepted."""
import datetime as dt
import json
from unittest import mock

from pipeline import runner

from tests.test_runner import Base

THU = dt.datetime(2026, 10, 29, 10, 0)       # a Thursday
SLOT = dt.time(13, 0)
SHIP = {"version": "0.2.33-beta", "note": "reviewed: x"}


class Lanes(Base):
    def r(self, now, ask=lambda j, s: "approve"):
        return runner.Runner(self.root, self.dev, self.local, now=lambda: now, ask=ask, notify=None,
                             busy=lambda: False, sent_today=lambda: True, slot=SLOT)

    def test_slot_ship_waits_for_13_then_runs_with_the_soak_before_approve(self):
        p = self.queue("ship", SHIP)
        self.assertEqual(self.r(THU).run_job(p), "deferred")
        self.assertIn("13:00", json.loads(p.read_text())["deferred"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.r(THU.replace(hour=13, minute=5)).run_job(p), "ok")
        dev = [c[1] for c in self.calls if c[0] == "dev"]
        self.assertEqual(dev, [["staging", "sync"], ["tests"], ["staging", "run"], ["staging", "compare"]])

    def test_one_slot_ship_a_day_and_none_at_weekends(self):
        self.assertEqual(self.r(THU.replace(hour=14)).run_job(self.queue("ship", SHIP)), "ok")
        self.assertEqual(self.r(THU.replace(hour=15)).run_job(self.queue("ship", SHIP, jid="j2")), "expired")
        self.assertIn("slot is used", self.done("j2")["detail"])
        sat = dt.datetime(2026, 10, 31, 14, 0)
        self.assertEqual(self.r(sat).run_job(self.queue("ship", SHIP, jid="j3")), "expired")
        self.assertIn("weekdays", self.done("j3")["detail"])

    def test_fix_lane_goes_any_time_in_the_window_and_doesnt_use_the_slot(self):
        fix = {**SHIP, "lane": "fix"}
        self.assertEqual(self.r(THU).run_job(self.queue("ship", fix, jid="f1")), "ok")
        self.assertEqual(self.r(dt.datetime(2026, 10, 31, 10, 0)).run_job(self.queue("ship", fix, jid="f2")), "ok")
        self.assertEqual(self.r(THU.replace(hour=13, minute=30)).run_job(self.queue("ship", SHIP, jid="s1")), "ok")

    def test_a_compare_that_needs_review_stops_the_ship_unless_accepted(self):
        def fake(root, argv, log, timeout=0):
            self.calls.append(("dev", list(argv)))
            return 3 if argv[:2] == ["staging", "compare"] else 0
        asked = []
        with mock.patch.object(runner, "run_np", side_effect=fake):
            st = self.r(THU.replace(hour=13, minute=5), ask=lambda j, s: asked.append(1) or "approve") \
                .run_job(self.queue("ship", SHIP, jid="c1"))
            self.assertEqual(st, "failed")
            self.assertEqual(asked, [])                                     # never asked
            self.assertNotIn(("local", ["release", "0.2.33-beta", "reviewed: x"]), self.calls)
            acc = {**SHIP, "lane": "fix", "accept": "accepted: Steven ok'd the longer edition in chat"}
            self.assertEqual(self.r(THU.replace(hour=13, minute=10)).run_job(self.queue("ship", acc, jid="c2")), "ok")

    def test_lane_and_accept_are_checked(self):
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "ship", "args": {**SHIP, "lane": "urgent"}})
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "ship", "args": {**SHIP, "accept": "fine"}})

    def test_no_slot_means_no_lane_rules(self):
        r = runner.Runner(self.root, self.dev, self.local, now=lambda: THU, ask=lambda j, s: "approve", notify=None,
                          busy=lambda: False, sent_today=lambda: True)
        self.assertEqual(r.run_job(self.queue("ship", SHIP)), "ok")
