"""Steven 2026-10-31: the subscriber list shows each person's channels (email, Slack, ...)."""
import unittest

from pipeline import audience


class Resp:
    def __init__(self, d):
        self.d = d

    def json(self):
        return self.d


class Client:
    def get(self, url, headers=None, params=None):
        if url.endswith("conversations.members"):
            return Resp({"ok": True, "members": ["U1", "U2", "B1"]})
        uid = params["user"]
        if uid == "B1":
            return Resp({"ok": True, "user": {"id": "B1", "is_bot": True}})
        return Resp({"ok": True, "user": {"id": uid, "profile": {"real_name": f"Person {uid}",
                                                                 "email": "a@x.com" if uid == "U1" else ""}}})


class Audience(unittest.TestCase):
    def test_rows_merge_email_and_slack_by_email(self):
        email = [{"email": "A@x.com", "status": "active"}, {"email": "b@x.com", "status": "pending"}]
        slack = [{"id": "U1", "name": "Ann", "email": "a@x.com"}, {"id": "U2", "name": "Bo", "email": ""}]
        r = {x["email"] or x["name"]: x for x in audience.rows(email, slack)}
        self.assertEqual(r["a@x.com"]["channels"], ["email", "slack"])
        self.assertEqual(r["a@x.com"]["name"], "Ann")
        self.assertEqual(r["b@x.com"]["channels"], [])
        self.assertEqual(r["Bo"]["channels"], ["slack"])

    def test_slack_members_leave_out_bots(self):
        from unittest import mock
        cfg = {"slack": {"post": {"enabled": True, "channel": "c", "channel_id": "C1"}}}
        with mock.patch("pipeline.slackpost.token", return_value="xoxb"):
            m = audience.slack_members(cfg, client=Client())
        self.assertEqual([x["id"] for x in m["members"]], ["U1", "U2"])


if __name__ == "__main__":
    unittest.main()
