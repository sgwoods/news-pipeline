"""Phone notifications through ntfy (Steven, 2026-10-28): one-tap approvals a tap on the private topic proves, and
nudges that open the owner pages. The topic names never leave the Keychain."""
import json
import unittest

from pipeline import ntfy, runner

from tests.test_runner import Base
from tests.test_runner_phone import KEY, NOON


class Ntfy(unittest.TestCase):
    def test_approval_message_has_two_http_actions(self):
        sent = []
        ok = ntfy.publish("aib-x", "Approve? ship", "summary", actions=ntfy.approval_actions("aib-r", "j1", "ab" * 10),
                          post=lambda url, payload: sent.append((url, payload)) or True)
        self.assertTrue(ok)
        url, p = sent[0]
        self.assertEqual(url, ntfy.SERVER)
        self.assertEqual(p["topic"], "aib-x")
        self.assertEqual([a["label"] for a in p["actions"]], ["Approve", "Reject"])
        self.assertEqual(p["actions"][0]["body"], "approve|j1|" + "ab" * 10)
        self.assertEqual(p["actions"][1]["url"], ntfy.SERVER + "/aib-r")

    def test_parse_answers_keeps_the_latest_valid_tap_per_job(self):
        lines = [json.dumps({"event": "open"}),
                 json.dumps({"event": "message", "time": 10, "message": "approve|job-01|" + "a" * 40}),
                 json.dumps({"event": "message", "time": 12, "message": "reject|job-01|" + "a" * 40}),
                 json.dumps({"event": "message", "time": 13, "message": "approve|job-02|short"}),
                 json.dumps({"event": "message", "time": 14, "message": "approve|../x|" + "a" * 40}),
                 "not json"]
        got = ntfy.parse_answers(lines)
        self.assertEqual(got, {"job-01": {"answer": "reject", "proof": "a" * 40, "at": "12"}})

    def test_owner_token_matches_the_mail_script(self):
        # Code.gs: 'o' + scope + yyyymmdd + base64url(HMAC-SHA256(email|scope|day, SECRET)) without padding, 32 chars
        t = ntfy.owner_token("Steven@Example.com", "t", "secret-key", "20261028")
        self.assertRegex(t, r"^ot20261028[A-Za-z0-9_-]{32}$")
        self.assertEqual(t, ntfy.owner_token("steven@example.com", "t", "secret-key", "20261028"))

    def test_setup_keeps_topics_private(self):
        import pipeline.vault as v
        saved, shown, copied = {}, [], []
        orig = v.set_keychain
        v.set_keychain = lambda k, val: saved.__setitem__(k, val) or True
        try:
            self.assertEqual(ntfy.setup(show=shown.append, copy=copied.append), "saved")
        finally:
            v.set_keychain = orig
        self.assertEqual(set(saved), {ntfy.TOPIC, ntfy.REPLY})
        self.assertEqual(copied, [saved[ntfy.TOPIC]])
        self.assertNotIn(saved[ntfy.REPLY], shown[0])             # the reply topic is never shown
        self.assertRegex(saved[ntfy.TOPIC], r"^aib-[A-Za-z0-9-]{20,}$")


class Approvals(Base):
    def test_a_tap_approves_and_a_wrong_token_does_not(self):
        sent, answers = [], {}
        ph = runner.Phone(send=lambda jid, n, t, s: sent.append((jid, n)) or True, poll=lambda ids: answers, kind="ntfy")
        mk = lambda: runner.Runner(self.root, self.dev, self.local, now=lambda: NOON, ask=lambda *a: "timeout",  # noqa: E731
                                   notify=None, busy=lambda: False, sent_today=lambda: True, key=KEY, phone=ph)
        p = self.queue("release", {"version": "0.2.24-beta", "note": "reviewed: x"})
        self.assertEqual(mk().run_job(p), "waiting")
        w = runner.qdir(self.root, "waiting") / p.name
        jid, nonce = sent[0]
        answers[jid] = {"answer": "approve", "proof": "f" * len(nonce), "at": "1"}
        self.assertEqual(mk().run_job(w), "waiting")
        self.assertIn("doesn't match", json.loads(w.read_text())["phone_check"]["result"])
        answers[jid] = {"answer": "approve", "proof": nonce, "at": "2"}
        self.assertEqual(mk().run_job(w), "ok")
        self.assertEqual(self.done("j-release")["approved"]["how"], "phone")
