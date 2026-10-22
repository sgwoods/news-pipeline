"""Slack (pipeline/slacksource.py): links any member posts count with links_from: anyone; text and posters never."""
import logging
import time
import unittest
from unittest import mock

from pipeline import slacksource

MSGS = [{"user": "U_STEVEN", "ts": str(time.time()), "text": "my view: big deal <https://example.org/steven-link>"},
        {"user": "U_ROB", "ts": str(time.time()), "text": "Deepseek open-sourced its engine <https://x.com/deepseek_ai/status/1>"},
        {"bot_id": "B1", "ts": str(time.time()), "text": "<https://example.org/bot>"}]


class R:
    def __init__(self, d):
        self.d = d

    def raise_for_status(self):
        pass

    def json(self):
        return self.d


class Client:
    def get(self, url, params=None, headers=None):
        if url.endswith("conversations.list"):
            return R({"ok": True, "channels": [{"name": "cto-musings", "id": "C1"}]})
        return R({"ok": True, "messages": MSGS})

    def close(self):
        pass


def run(links_from):
    cfg = {"slack": {"enabled": True, "channel": "cto-musings", "authors": ["U_STEVEN"], "links_from": links_from}}
    with mock.patch.object(slacksource, "token", lambda: "xoxp-test"), \
            mock.patch("pipeline.linkedin.is_own_post", lambda it, cfg: False):
        return slacksource.fetch(None, cfg, "r", logging.getLogger("t"), client=Client())


class SlackLinks(unittest.TestCase):
    def test_only_mine_by_default(self):
        items = run("authors")["items"]
        self.assertEqual([i["url"] for i in items], ["https://example.org/steven-link"])

    def test_anyone_adds_others_links_without_their_text_or_name(self):
        items = run("anyone")["items"]
        self.assertEqual(sorted(i["url"] for i in items), ["https://example.org/steven-link", "https://x.com/deepseek_ai/status/1"])
        rob = next(i for i in items if "deepseek" in i["url"])
        self.assertEqual(rob["person"], "Shared in Steven's team channel")
        blob = str(items)
        for bad in ("U_ROB", "Deepseek open-sourced its engine", "my view: big deal", "cto-musings", "U_STEVEN"):
            self.assertNotIn(bad, blob)


if __name__ == "__main__":
    unittest.main()
