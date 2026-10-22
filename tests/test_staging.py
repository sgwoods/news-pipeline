"""Staging mode (pipeline/env.py): a development checkout can't reach readers or change shared state."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import env, mailer, release


class StagingMode(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self._old = os.environ.pop("NP_ENV", None)

    def tearDown(self):
        os.environ.pop("NP_ENV", None)
        if self._old is not None:
            os.environ["NP_ENV"] = self._old

    def test_mode_from_marker_or_env(self):
        self.assertEqual(env.mode(self.root), "production")
        (self.root / ".staging").write_text("")
        self.assertEqual(env.mode(self.root), "staging")
        os.environ["NP_ENV"] = "production"
        self.assertEqual(env.mode(self.root), "production")

    def test_subject_mark_keeps_the_script_prefix(self):
        self.assertEqual(env.mark_subject("AI Briefing · Thu Oct 22: x"), "AI Briefing · [STAGING] Thu Oct 22: x")
        self.assertEqual(env.mark_subject("AI Briefing · [STAGING] x"), "AI Briefing · [STAGING] x")
        self.assertEqual(env.mark_subject("Other"), "[STAGING] Other")

    def test_require_refuses_every_outbound_action_in_staging(self):
        os.environ["NP_ENV"] = "staging"
        for action in ("site publish", "backup push", "Gmail label writes", "hub push", "public code push",
                       "email send", "today's publish and email"):
            with self.assertRaises(release.ReleaseBlocked) as cm:
                release.require(self.root, {}, action)
            self.assertIn("staging", str(cm.exception))

    def test_mailer_allows_only_reads_and_owner_review_sends(self):
        os.environ["NP_ENV"] = "staging"
        cfg = {"email": {"script_url": "https://script.example/x", "test_to": "me@example.com"}}
        sent = []

        class R:
            status_code = 200

            def json(self):
                return {"ok": True}

        def post(url, data=None, **kw):
            sent.append(data)
            return R()
        with mock.patch.object(mailer, "ready", lambda c: ""), mock.patch.object(mailer, "key", lambda: "k" * 30), \
                mock.patch("httpx.post", post), mock.patch.object(release, "require", lambda *a, **k: None):
            for action, params in (("send", {"subject": "AI Briefing · x"}), ("add", {"email": "a@b.c"}),
                                   ("remove", {"email": "a@b.c"}), ("company", {"subject": "x"}),
                                   ("setqueue", {"items": "[]"}), ("send", {"subject": "AI Briefing · x", "to": "x@y.z"})):
                with self.assertRaises(mailer.MailError):
                    mailer.call(cfg, action, **params)
            self.assertEqual(sent, [])
            mailer.call(cfg, "list")
            mailer.call(cfg, "send", subject="AI Briefing · Thu: x", to="me@example.com", html="h", text="t")
        self.assertEqual(sent[-1]["subject"], "AI Briefing · [STAGING] Thu: x")
        self.assertEqual(len(sent), 2)

    def test_preview_needs_every_check_but_the_production_approval(self):
        os.environ["NP_ENV"] = "staging"
        rec = {"passed": False, "checks": {"tests": {"ok": True, "detail": ""}, "approval": {"ok": False, "detail": "x"}}}
        with mock.patch.object(release, "run", lambda *a, **k: rec):
            release.require(self.root, {}, "site publish", staging_ok=True)      # approval alone doesn't block it
            rec["checks"]["tests"] = {"ok": False, "detail": "1 failed"}
            with self.assertRaises(release.ReleaseBlocked):
                release.require(self.root, {}, "site publish", staging_ok=True)

    def test_production_is_unchanged(self):
        os.environ["NP_ENV"] = "production"
        self.assertEqual(env.label(self.root), "")


if __name__ == "__main__":
    unittest.main()
