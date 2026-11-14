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


@unittest.skipUnless((ROOT / "config.yaml").exists(), "needs a checkout with config.yaml")
class QueueForm(DashboardButtons):
    """The Queue page (v0.2.62): any recipe with its arguments and a typed yes; ends the Terminal pastes."""
    def test_page_lists_recipes_and_jobs(self):
        r = self.c.get("/queue", headers={"Host": "127.0.0.1:8775"})
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        for name in ("ship", "release", "send-held", "rescue-item", "morning-check"):
            self.assertIn(f'value="{name}"', body)
        self.assertIn("arg_version", body)

    def test_ship_with_typed_yes_queues_with_the_stamp(self):
        r = self.post("/api/queue-form", recipe="ship", arg_version="0.2.62-beta", arg_lane="fix",
                      arg_note="reviewed: queue form", arg_accept="", **{"yes": "yes"})
        self.assertEqual(r.status_code, 302)
        recipe, args, stamp, who = self.calls[0]
        self.assertEqual((recipe, args["version"], args["lane"]), ("ship", "0.2.62-beta", "fix"))
        self.assertIn("typed yes", stamp)
        self.assertEqual(who, "Steven (dashboard)")

    def test_without_yes_nothing_is_queued(self):
        r = self.post("/api/queue-form", recipe="publish", **{"yes": ""})
        self.assertEqual(r.status_code, 302)
        self.assertIn("type+yes", r.headers["Location"].replace("%20", "+"))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.post("/api/queue-form", recipe="phone-setup", **{"yes": "yes"}).status_code, 400)

    def test_approve_from_the_form_keeps_the_mac_dialog(self):
        self.post("/api/queue-form", recipe="approve", arg_note="checked the diff", **{"yes": "yes"})
        recipe, args, stamp, _ = self.calls[0]
        self.assertEqual(recipe, "approve")
        self.assertTrue(args["note"].startswith("reviewed:"))
        self.assertEqual(stamp, "")
