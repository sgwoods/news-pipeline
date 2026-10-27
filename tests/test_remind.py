"""Pending sign-ups (Steven, 2026-10-27): one reminder, expiry 14 days later, counts without his test copy."""
import unittest
from pathlib import Path
from unittest import mock

from pipeline import mailer, runner

ROOT = Path(__file__).resolve().parent.parent


class Remind(unittest.TestCase):
    def test_script_actions_are_key_only_and_limited(self):
        gs = (ROOT / "scripts" / "apps-script" / "Code.gs").read_text("utf-8")
        auth = gs.index("if (!authed_(p)) return json_")
        for a in ("remind", "expire"):
            self.assertGreater(gs.index(f"if (p.action === '{a}')"), auth)
        block = gs[gs.index("if (p.action === 'remind')"):gs.index("if (p.action === 'expire')")]
        self.assertIn("r.status !== 'pending'", block)                      # only people who never confirmed
        self.assertIn("7 * 86400000", block)                                # at most once a week each
        self.assertIn("14 * 86400000", gs[gs.index("if (p.action === 'expire')"):])
        self.assertIn("'reminded']", gs)

    def test_jobs_validate_addresses(self):
        ok = runner.validate({"id": "a", "recipe": "email-remove", "args": {"email": "X@Example.com"},
                              "chat_approval": "Steven: remove it"})
        self.assertEqual(ok["args"]["email"], "x@example.com")
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "email-remove", "args": {"email": "a@b.com,c@d.com"}, "chat_approval": "y"})
        ok = runner.validate({"id": "a", "recipe": "email-remind", "args": {"emails": "a@b.com, c@d.org"}, "chat_approval": "y"})
        self.assertEqual(ok["args"]["emails"], "a@b.com,c@d.org")
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "email-remind", "args": {"emails": "not an address"}, "chat_approval": "y"})
        self.assertEqual(runner.RECIPES["email-remind"]["tier"], "chat")

    def test_counts_leave_out_the_test_copy(self):
        subs = [{"email": "owner+test@example.com", "status": "active"}, {"email": "a@x.com", "status": "active"},
                {"email": "b@x.com", "status": "pending"}]
        with mock.patch.object(mailer, "ecfg", return_value={"test_to": "owner+test@example.com"}):
            self.assertEqual(mailer.counts({}, subs), {"active": 1, "pending": 1})


if __name__ == "__main__":
    unittest.main()
