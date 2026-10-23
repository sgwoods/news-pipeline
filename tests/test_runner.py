"""Run queue (pipeline/runner.py): only allowlisted recipes, validated arguments, three approval tiers."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import presence, release, runner

NOON = dt.datetime(2026, 10, 23, 12, 0)


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.dev = Path(tempfile.mkdtemp())
        self.calls = []
        self.seen_presence = []

        def fake_np(root, argv, log, timeout=0):
            self.calls.append(("dev" if root == self.dev else "prod", list(argv)))
            return self.np_code.get(argv[0], 0)
        self.np_code = {}
        p = mock.patch.object(runner, "run_np", side_effect=fake_np)
        p.start()
        self.addCleanup(p.stop)

        def local(name):
            def fn(argv):
                self.calls.append(("local", [name, *argv]))
                self.seen_presence.append((name, presence.confirmed()))
                return 0
            return fn
        self.local = {k: local(k) for k in ("verify", "release", "rollback", "approve", "install-hooks", "push-code")}

    def make(self, ask=lambda job, s: "approve", now=NOON, busy=False):
        return runner.Runner(self.root, self.dev, self.local, now=lambda: now, ask=ask, notify=None,
                             busy=lambda: busy)

    def queue(self, recipe, args=None, chat="", jid=None, raw=None):
        job = raw or {"id": jid or f"j-{recipe}", "recipe": recipe, "args": args or {}, "queued_by": "Claude"}
        if chat:
            job["chat_approval"] = chat
        p = runner.qdir(self.root, "pending") / f"{job.get('id', 'x')}.json"
        p.write_text(json.dumps(job), "utf-8")
        return p

    def done(self, jid):
        return json.loads((self.root / runner.QUEUE / "done" / f"{jid}.json").read_text("utf-8"))


class Validation(unittest.TestCase):
    def test_recipes_put_every_approval_behind_the_click(self):
        self.assertEqual(runner.recipe_problems(), [])

    def test_a_recipe_that_skips_approve_is_caught(self):
        bad = {"sneaky": {"tier": "chat", "args": {}, "steps": [("local", ["release", "0.1.0"])]}}
        self.assertTrue(runner.recipe_problems(bad))
        bad = {"sneaky": {"tier": "auto", "args": {}, "steps": [("prod", ["release", "0.1.0", "reviewed: x"])]}}
        self.assertTrue(runner.recipe_problems(bad))

    def test_unknown_recipe_and_extra_args_refused(self):
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "rm", "args": {}})
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "tests", "args": {"cmd": "x"}})

    def test_argument_shapes(self):
        ok = runner.validate({"id": "a", "recipe": "ship", "args": {"version": "v0.1.12-beta", "note": "reviewed: x"}})
        self.assertEqual(ok["args"]["version"], "0.1.12-beta")
        for args in ({"version": "0.1.12; rm -rf /", "note": "reviewed: x"},
                     {"version": "0.1.12-beta", "note": "looks fine"},
                     {"version": "0.1.12-beta", "note": "reviewed: x\n$(touch y)"}):
            with self.assertRaises(runner.JobError):
                runner.validate({"id": "a", "recipe": "ship", "args": args})
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "correct", "args": {"day": "2026-13-40", "note": "x"},
                             "chat_approval": "yes"})

    def test_chat_tier_needs_steven_quoted(self):
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "publish", "args": {}})
        self.assertIn("chat_approval", runner.validate({"id": "a", "recipe": "publish", "args": {},
                                                        "chat_approval": "yes, publish"}))

    def test_id_and_file_name(self):
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "../x", "recipe": "tests"})
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "tests"}, "b.json")

    def test_optional_day_is_dropped_when_empty(self):
        self.assertEqual(runner.argv_for(["staging", "run", "{day}"], {"day": ""}), ["staging", "run"])


class Tiers(Base):
    def test_auto_runs_in_dev(self):
        self.queue("tests")
        self.assertEqual(self.make().run_job(runner.qdir(self.root, "pending") / "j-tests.json"), "ok")
        self.assertEqual(self.calls, [("dev", ["tests"])])
        self.assertEqual(self.done("j-tests")["status"], "ok")
        self.assertFalse((self.root / runner.QUEUE / "pending" / "j-tests.json").exists())

    def test_chat_tier_runs_with_the_quote(self):
        p = self.queue("correct", {"day": "2026-10-22", "note": "fixed the Agenda line"}, chat="yes, correct it")
        self.assertEqual(self.make().run_job(p), "ok")
        self.assertEqual(self.calls[0], ("prod", ["correct", "2026-10-22", "fixed the Agenda line"]))
        self.assertEqual(self.calls[1], ("prod", ["publish"]))

    def test_chat_tier_without_the_quote_is_invalid(self):
        p = self.queue("publish")
        self.assertEqual(self.make().run_job(p), "invalid")
        self.assertEqual(self.calls, [])

    def test_ship_asks_after_tests_and_runs_release_with_presence(self):
        asked = []
        p = self.queue("ship", {"version": "0.1.12-beta", "note": "reviewed: run queue"})
        st = self.make(ask=lambda job, s: asked.append(job["recipe"]) or "approve").run_job(p)
        self.assertEqual(st, "ok")
        self.assertEqual(asked, ["ship"])
        self.assertEqual(self.calls[:2], [("dev", ["staging", "sync"]), ("dev", ["tests"])])
        self.assertIn(("local", ["release", "0.1.12-beta", "reviewed: run queue"]), self.calls)
        self.assertIn(("release", True), self.seen_presence)
        self.assertFalse(presence._granted, "presence ends with the job")
        self.assertEqual(self.done("j-ship")["approved"]["how"], "dialog")

    def test_failed_tests_never_ask(self):
        self.np_code["tests"] = 1
        asked = []
        p = self.queue("ship", {"version": "0.1.12-beta", "note": "reviewed: x"})
        self.assertEqual(self.make(ask=lambda j, s: asked.append(1) or "approve").run_job(p), "failed")
        self.assertEqual(asked, [])
        self.assertNotIn("release", [c[1][0] for c in self.calls])

    def test_reject_runs_nothing_more(self):
        p = self.queue("release", {"version": "0.1.12-beta", "note": "reviewed: x"})
        self.assertEqual(self.make(ask=lambda j, s: "reject").run_job(p), "rejected")
        self.assertEqual(self.calls, [])

    def test_no_answer_waits_then_reprompts_later(self):
        p = self.queue("release", {"version": "0.1.12-beta", "note": "reviewed: x"})
        self.assertEqual(self.make(ask=lambda j, s: "timeout").run_job(p), "waiting")
        w = runner.qdir(self.root, "waiting") / "j-release.json"
        self.assertTrue(w.exists())
        self.assertEqual(self.make(ask=lambda j, s: "approve", now=NOON + dt.timedelta(minutes=5)).run_job(w), "waiting")
        self.assertEqual(self.make(ask=lambda j, s: "approve", now=NOON + dt.timedelta(minutes=25)).run_job(w), "ok")
        self.assertIn(("local", ["release", "0.1.12-beta", "reviewed: x"]), self.calls)

    def test_waiting_jobs_expire_at_eight(self):
        p = self.queue("release", {"version": "0.1.12-beta", "note": "reviewed: x"})
        self.make(ask=lambda j, s: "timeout").run_job(p)
        self.make(now=dt.datetime(2026, 10, 23, 20, 5)).expire()
        self.assertEqual(self.done("j-release")["status"], "expired")

    def test_production_jobs_wait_out_the_morning_run(self):
        p = self.queue("publish", chat="yes")
        self.assertEqual(self.make(now=dt.datetime(2026, 10, 23, 5, 0)).run_job(p), "deferred")
        self.assertEqual(self.make(busy=True).run_job(p), "deferred")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.make().run_job(p), "ok")

    def test_releases_only_in_the_window(self):
        p = self.queue("release", {"version": "0.1.12-beta", "note": "reviewed: x"})
        self.assertEqual(self.make(now=dt.datetime(2026, 10, 23, 21, 0)).run_job(p), "deferred")

    def test_terminal_approve_skips_the_dialog(self):
        p = self.queue("rollback", {"note": "reviewed: canary failed"})
        self.make(ask=lambda j, s: "timeout").run_job(p)
        w = runner.qdir(self.root, "waiting") / "j-rollback.json"
        self.assertEqual(self.make(ask=lambda j, s: self.fail("no dialog")).run_job(w, terminal=True), "ok")
        self.assertEqual(self.done("j-rollback")["approved"]["how"], "terminal")

    def test_tick_refuses_when_production_code_changed(self):
        self.queue("tests")
        with mock.patch.object(runner, "code_changes", return_value=" M pipeline/x.py"), \
                mock.patch("pipeline.env.staging", return_value=False):
            out = self.make().tick()
        self.assertIn("refused", out[0])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.done("j-tests")["status"], "refused")

    def test_tick_runs_the_queue(self):
        self.queue("tests", jid="a1")
        self.queue("verify", jid="a2")
        with mock.patch.object(runner, "code_changes", return_value=""), \
                mock.patch("pipeline.env.staging", return_value=False):
            out = self.make().tick()
        self.assertEqual([x.split(": ")[1] for x in out], ["ok", "ok"])
        st = json.loads((self.root / runner.QUEUE / "status.json").read_text("utf-8"))
        self.assertEqual(st["pending"], [])

    def test_staging_never_runs_the_queue(self):
        self.queue("tests")
        with mock.patch("pipeline.env.staging", return_value=True):
            self.assertIn("production", self.make().tick()[0])
        self.assertEqual(self.calls, [])


class NpTick(unittest.TestCase):
    """The launchd tick goes through ./np runner tick: it must reach run.py whenever any job is queued."""
    def _tick(self, files):
        import shutil
        import subprocess
        d = Path(tempfile.mkdtemp())
        shutil.copy(Path(__file__).resolve().parent.parent / "np", d / "np")
        (d / "run.py").write_text("import sys\nopen('ran', 'w').write(' '.join(sys.argv[1:]))\n", "utf-8")
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("{}", "utf-8")
        subprocess.run(["/bin/bash", str(d / "np"), "runner", "tick"], cwd=d, capture_output=True, timeout=30)
        return (d / "ran").read_text("utf-8") if (d / "ran").exists() else ""

    def test_tick_runs_with_only_pending_jobs(self):
        self.assertEqual(self._tick(["data/queue/pending/a.json"]), "--runner tick")

    def test_tick_runs_with_only_waiting_jobs(self):
        self.assertEqual(self._tick(["data/queue/waiting/a.json"]), "--runner tick")

    def test_tick_is_quiet_when_idle(self):
        self.assertEqual(self._tick(["data/queue/done/a.json"]), "")


class Presence(unittest.TestCase):
    def test_nothing_on_disk_grants_presence(self):
        with mock.patch("sys.stdin") as s:
            s.isatty.return_value = False
            self.assertFalse(presence.confirmed())
            with presence.granted("job"):
                self.assertTrue(presence.confirmed())
            self.assertFalse(presence.confirmed())

    def test_invariant_10_holds(self):
        ok, detail = release.check_invariants()
        self.assertNotIn("run queue", detail)
        self.assertNotIn("presence", detail)


if __name__ == "__main__":
    unittest.main()
