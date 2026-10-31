"""Steven 2026-10-31: approvals up front in chat. A ship carrying his quoted yes runs on its own after tests and the
soak, with presence granted for its release step; nothing asks him later. Rollback still needs the tap."""
import datetime as dt

from pipeline import runner

from tests.test_runner import Base

NOON = dt.datetime(2026, 10, 29, 13, 30)


class ChatApproval(Base):
    def r(self, ask):
        return runner.Runner(self.root, self.dev, self.local, now=lambda: NOON, ask=ask, notify=None,
                             busy=lambda: False, sent_today=lambda: True)

    def test_a_ship_with_steven_s_yes_in_chat_runs_without_asking(self):
        p = self.queue("ship", {"version": "0.2.37-beta", "note": "reviewed: x"}, chat="Steven: yes ship it")
        st = self.r(lambda j, s: self.fail("asked")).run_job(p)
        self.assertEqual(st, "ok")
        self.assertIn(("release", True), self.seen_presence)
        self.assertTrue(self.done("j-ship")["approved"]["how"].startswith("chat: Steven"))

    def test_failed_checks_still_stop_it(self):
        self.np_code["tests"] = 1
        p = self.queue("ship", {"version": "0.2.37-beta", "note": "reviewed: x"}, chat="Steven: yes")
        self.assertEqual(self.r(lambda j, s: self.fail("asked")).run_job(p), "failed")
        self.assertNotIn(("local", ["release", "0.2.37-beta", "reviewed: x"]), self.calls)

    def test_rollback_still_needs_the_tap(self):
        asked = []
        p = self.queue("rollback", {"note": "reviewed: x"}, chat="Steven: yes")
        self.r(lambda j, s: asked.append(j["recipe"]) or "approve").run_job(p)
        self.assertEqual(asked, ["rollback"])

    def test_rebuilds_and_rerecords_need_no_chat_quote(self):
        self.assertEqual(runner.RECIPES["remaster"]["tier"], "auto")
        self.assertEqual(runner.RECIPES["deepdive-rebuild"]["tier"], "auto")
