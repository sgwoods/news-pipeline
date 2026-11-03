"""Revisions are driven from the chat, the dashboard and notifications, not Terminal (Steven, 2026-11-03)."""
import unittest
from pathlib import Path

from pipeline import alerts

ROOT = Path(__file__).resolve().parents[1]


class AlertsChatFirst(unittest.TestCase):
    def test_steps_lead_with_chat_or_dashboard(self):
        for kind in alerts.KINDS:
            m = alerts.build(kind, "2026-11-03")
            steps = m["text"].split("What to do", 1)[1]
            first = steps.strip().splitlines()[0]
            self.assertNotIn("./np", first, kind)
            self.assertNotIn("cd ~/", first, kind)
            self.assertNotIn("(in Terminal)", m["text"])

    def test_terminal_only_as_fallback(self):
        m = alerts.build("approval", "2026-11-03")
        self.assertIn("Only if the chat and dashboard are unavailable", m["text"])
        self.assertIn("127.0.0.1:8775", m["text"])


@unittest.skipUnless((ROOT / "config.yaml").exists(), "needs a checkout with config.yaml")
class DashboardButtons(unittest.TestCase):
    def setUp(self):
        from dashboard.app import create_app
        from pipeline import runner
        self.app = create_app(ROOT)
        self.c = self.app.test_client()
        self.calls = []
        self.orig = runner.enqueue
        runner.enqueue = lambda root, recipe, args=None, chat_approval="", queued_by="": (
            self.calls.append((recipe, args, chat_approval, queued_by)) or Path(f"/tmp/x-{recipe}.json"))

    def tearDown(self):
        from pipeline import runner
        runner.enqueue = self.orig

    def post(self, url, **data):
        return self.c.post(url, data={"csrf": self.app.config["CSRF"], **data}, headers={"Host": "127.0.0.1:8775"})

    def test_send_held_queues_with_approval_stamp(self):
        r = self.post("/api/queue/send-held")
        self.assertEqual(r.status_code, 302)
        recipe, args, stamp, who = self.calls[0]
        self.assertEqual(recipe, "send-held")
        self.assertIn("dashboard button", stamp)

    def test_approve_gets_a_reviewed_note_and_no_chat_stamp(self):
        self.post("/api/queue/approve", note="checked the newsletters.yaml diff")
        recipe, args, stamp, _ = self.calls[0]
        self.assertTrue(args["note"].startswith("reviewed:"))
        self.assertEqual(stamp, "")                     # the Mac dialog or phone still asks

    def test_unknown_job_and_missing_csrf_refused(self):
        self.assertEqual(self.post("/api/queue/ship").status_code, 404)
        r = self.c.post("/api/queue/send-held", headers={"Host": "127.0.0.1:8775"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
