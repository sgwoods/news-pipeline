"""v0.2.13 (Steven 2026-10-27: "when I have reviewed things in the am, get everything moving as soon as I am done"):
approve while a job waits for the morning, the window opens once the edition is out, one Approve covers the
release's follow-through, and an approval file can't be forged without the Keychain key."""
import datetime as dt
import json

from pipeline import presence, runner

from tests.test_runner import Base

EARLY = dt.datetime(2026, 10, 27, 7, 40)
KEY = lambda: b"k" * 32  # noqa: E731


class Early(Base):
    def setUp(self):
        super().setUp()
        self.local["follow-through"] = lambda a: self.calls.append(("local", ["follow-through", *a])) or 0

    def make2(self, now, ask=lambda j, s: "approve", sent=False, busy=False, key=KEY):
        return runner.Runner(self.root, self.dev, self.local, now=lambda: now, ask=ask, notify=None,
                             busy=lambda: busy, sent_today=lambda: sent, key=key)

    def test_approve_early_then_it_runs_when_the_window_opens_without_asking_again(self):
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"})
        asked = []
        st = self.make2(EARLY, ask=lambda j, s: asked.append(j.get("early")) or "approve").run_job(p)
        self.assertEqual(st, "deferred (approved)")
        self.assertEqual(asked, [True])
        self.assertEqual(self.calls, [])                                    # nothing ran yet
        st = self.make2(EARLY.replace(hour=8, minute=31), ask=lambda j, s: self.fail("asked twice")).run_job(p)
        self.assertEqual(st, "ok")
        self.assertIn(("local", ["release", "0.2.13-beta", "reviewed: x"]), self.calls)
        self.assertIn(("local", ["follow-through", "reviewed: x"]), self.calls)     # same Approve
        self.assertEqual(self.done("j-ship")["approved"]["how"], "dialog (early)")
        self.assertFalse(presence._granted)
        self.assertFalse(list((self.root / runner.APPROVED).glob("*.json")))     # used once

    def test_the_window_opens_once_the_edition_is_out(self):
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"})
        self.assertEqual(self.make2(EARLY, sent=True).run_job(p), "ok")
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"}, jid="j-ship2")
        self.assertTrue(self.make2(EARLY, sent=True, busy=True, ask=lambda j, s: "timeout").run_job(p).startswith("deferred"))
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"}, jid="j-ship3")
        self.assertTrue(self.make2(EARLY.replace(hour=4), sent=True, ask=lambda j, s: "timeout").run_job(p).startswith("deferred"))

    def test_a_written_approval_needs_the_key(self):
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"})
        job = json.loads(p.read_text())
        d = self.root / runner.APPROVED
        d.mkdir(parents=True)
        (d / "j-ship.json").write_text(json.dumps({"id": "j-ship", "day": "2026-10-27", "sig": "0" * 64}))
        r = self.make2(EARLY.replace(hour=9), ask=lambda j, s: "timeout")
        self.assertFalse(r.approved_early(runner.validate(job)))
        self.assertEqual(r.run_job(p), "waiting")                            # forged: it asks instead
        good = self.make2(EARLY.replace(hour=9))
        good.approve_early(runner.validate(job))
        changed = dict(runner.validate(job), args={"version": "9.9.9-beta", "note": "reviewed: x"})
        self.assertFalse(good.approved_early(changed))                     # bound to this job's content
        self.assertFalse(self.make2(EARLY.replace(day=28, hour=9)).approved_early(runner.validate(job)))  # today only

    def test_no_key_means_no_early_dialog(self):
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"})
        self.assertEqual(self.make2(EARLY, key=None, ask=lambda j, s: self.fail("no early dialog")).run_job(p), "deferred")

    def test_follow_through_is_optional_where_it_doesnt_exist(self):
        del self.local["follow-through"]
        p = self.queue("ship", {"version": "0.2.13-beta", "note": "reviewed: x"})
        self.assertEqual(self.make2(EARLY.replace(hour=12)).run_job(p), "ok")
        self.assertEqual(runner.recipe_problems(), [])
