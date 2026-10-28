"""Phone approvals (Steven, 2026-10-27: approve from the iOS app, not only at the Mac): a one-time link by email, a
passphrase typed on the phone, and a proof only the Mac can check. A record in the mail script alone never approves."""
import datetime as dt
import json

from pipeline import runner

from tests.test_runner import Base

NOON = dt.datetime(2026, 10, 28, 12, 0)
KEY = lambda: b"k" * 32  # noqa: E731
PHRASE = "correct horse battery"


class FakePhone:
    def __init__(self):
        self.sent, self.answers = [], {}

    def send(self, jid, nonce, title, summary):
        self.sent.append((jid, nonce, title))
        return True

    def poll(self, ids):
        return {i: self.answers[i] for i in ids if i in self.answers}

    def tap(self, jid, answer, phrase=PHRASE):
        nonce = next(n for j, n, _ in self.sent if j == jid)
        self.answers[jid] = {"answer": answer, "proof": runner.phone_proof(phrase, nonce, answer, jid), "at": "x"}


class Phone(Base):
    def make3(self, ph, now=NOON, ask=lambda j, s, *a: "timeout"):
        return runner.Runner(self.root, self.dev, self.local, now=lambda: now, ask=ask, notify=None,
                             busy=lambda: False, sent_today=lambda: True, key=KEY,
                             phone=runner.Phone(ph.send, ph.poll, lambda: PHRASE))

    def test_link_then_approve_on_the_phone(self):
        ph = FakePhone()
        p = self.queue("release", {"version": "0.2.22-beta", "note": "reviewed: x"})
        seconds = []
        st = self.make3(ph, ask=lambda j, s, *a: seconds.append(a) or "timeout").run_job(p)
        self.assertEqual(st, "waiting")
        self.assertEqual(len(ph.sent), 1)
        self.assertEqual(seconds, [(runner.PHONE_DIALOG,)])               # a short Mac dialog: the runner keeps ticking
        w = runner.qdir(self.root, "waiting") / p.name
        self.assertEqual(self.make3(ph).run_job(w), "waiting")             # nothing tapped yet; no second email
        self.assertEqual(len(ph.sent), 1)
        ph.tap("j-release", "approve")
        self.assertEqual(self.make3(ph, ask=lambda *a: self.fail("asked")).run_job(w), "ok")
        self.assertIn(("local", ["release", "0.2.22-beta", "reviewed: x"]), self.calls)
        self.assertEqual(self.done("j-release")["approved"]["how"], "phone")

    def test_wrong_passphrase_or_forged_record_never_approves(self):
        ph = FakePhone()
        p = self.queue("release", {"version": "0.2.22-beta", "note": "reviewed: x"})
        self.make3(ph).run_job(p)
        w = runner.qdir(self.root, "waiting") / p.name
        self.assertEqual(self.make3(ph).run_job(w), "waiting")
        self.assertEqual(json.loads(w.read_text())["phone_check"]["result"], "no answer yet")
        ph.tap("j-release", "approve", phrase="wrong phrase here")
        told = []
        r = runner.Runner(self.root, self.dev, self.local, now=lambda: NOON, ask=lambda *a: "timeout",
                          notify=lambda *a: told.append(a), busy=lambda: False, sent_today=lambda: True, key=KEY,
                          phone=runner.Phone(ph.send, ph.poll, lambda: PHRASE))
        self.assertEqual(r.run_job(w), "waiting")
        self.assertIn("does not match", json.loads(w.read_text())["phone_check"]["result"])
        self.assertEqual(r.run_job(w), "waiting")
        self.assertEqual(len(told), 1)                                     # told once per answer
        ph.answers["j-release"] = {"answer": "approve", "proof": "0" * 64}
        self.assertEqual(self.make3(ph).run_job(w), "waiting")
        self.assertEqual(self.calls, [])
        nonce = ph.sent[0][1]                                              # a proof for another job doesn't carry over
        ph.answers["j-release"] = {"answer": "approve", "proof": runner.phone_proof(PHRASE, nonce, "approve", "j-other")}
        self.assertEqual(self.make3(ph).run_job(w), "waiting")
        self.assertEqual(self.make3(ph, now=NOON + dt.timedelta(days=1)).approved_early(runner.validate(json.loads(w.read_text()))), False)

    def test_reject_on_the_phone(self):
        ph = FakePhone()
        p = self.queue("release", {"version": "0.2.22-beta", "note": "reviewed: x"})
        self.make3(ph).run_job(p)
        ph.tap("j-release", "reject")
        self.assertEqual(self.make3(ph).run_job(runner.qdir(self.root, "waiting") / p.name), "rejected")
        self.assertEqual(self.calls, [])

    def test_phone_approves_a_job_waiting_for_the_morning(self):
        ph = FakePhone()
        p = self.queue("release", {"version": "0.2.22-beta", "note": "reviewed: x"})
        early = NOON.replace(hour=6, minute=30)
        r = runner.Runner(self.root, self.dev, self.local, now=lambda: early, ask=lambda *a: "timeout", notify=None,
                          busy=lambda: False, sent_today=lambda: False, key=KEY,
                          phone=runner.Phone(ph.send, ph.poll, lambda: PHRASE))
        self.assertTrue(r.run_job(p).startswith("deferred"))
        ph.tap("j-release", "approve")
        self.assertEqual(r.run_job(p), "deferred (approved)")
        self.assertTrue(r.approved_early(runner.validate(json.loads(p.read_text()))))

    def test_no_key_no_phone(self):
        ph = FakePhone()
        r = runner.Runner(self.root, self.dev, self.local, now=lambda: NOON, ask=lambda *a: "timeout", notify=None,
                          key=None, phone=runner.Phone(ph.send, ph.poll, lambda: PHRASE))
        self.assertIsNone(r.phone)

    def test_browser_and_mac_agree_on_the_proof(self):
        # the same values the approve page's JavaScript (Code.gs) gives under Node's WebCrypto
        self.assertEqual(runner.phone_proof("correct horse battery", "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12",
                                            "approve", "20261028-0900-ship-0.2.22"),
                         "1e04c610aa80fa0721ab9575fee0cf0efa653b6484dc40f72efa54e9b316ab7a")

    def test_setup_needs_a_long_matching_passphrase(self):
        seq = iter(["short", "x"])
        self.assertIn("at least 10", runner.set_phone_secret(ask=lambda p: next(seq)))
        seq = iter(["long enough phrase", "different phrase!"])
        self.assertIn("didn't match", runner.set_phone_secret(ask=lambda p: next(seq)))
