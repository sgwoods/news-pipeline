"""Steven 2026-10-31: links posted in #discuss-generative-ai are ingested; only the linked content becomes the item,
the message is a private cue (no mentions, no links), the poster is never stored, and each pull is logged with its time."""
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import slacksource

CFG = {"slack": {"enabled": True, "lookback_hours": 48,
                 "channels": [{"channel": "discuss-generative-ai", "channel_id": "C123"}]}}


class Resp:
    def __init__(self, d):
        self.d = d

    def json(self):
        return self.d


class Client:
    def __init__(self, msgs):
        self.msgs, self.calls = msgs, []

    def get(self, url, headers=None, params=None):
        self.calls.append((url, params))
        return Resp({"ok": True, "messages": self.msgs})

    def close(self):
        pass


class Channels(unittest.TestCase):
    def test_links_become_items_with_a_private_cue_and_the_pull_is_logged(self):
        root = Path(tempfile.mkdtemp())
        msgs = [{"user": "U9", "ts": "1793450000.0",
                 "text": "<@U77> worth a look, big claim on agents <https://example.com/a|example>",
                 "attachments": [{"original_url": "https://example.com/a", "title": "Agents at work", "text": "Preview"}]},
                {"user": "U8", "ts": "1793450100.0", "text": "deck <https://docs.google.com/x>"},
                {"bot_id": "B1", "ts": "1793450200.0", "text": "<https://example.com/bot>"}]
        with mock.patch("pipeline.slackpost.token", return_value="xoxb"):
            r = slacksource.fetch_channels(root, CFG, "run1", logging.getLogger("t"), client=Client(msgs))
        self.assertEqual([i["url"] for i in r["items"]], ["https://example.com/a"])
        it = r["items"][0]
        self.assertEqual(it["person"], "Shared internally")
        self.assertIn("worth a look, big claim on agents", it["source_note"])
        self.assertNotIn("U77", it["source_note"])
        self.assertNotIn("U9", json.dumps(it))
        self.assertNotIn("https://", it["source_note"])
        self.assertTrue(it["pulled_at"])
        log = [json.loads(x) for x in (root / slacksource.PULLS).read_text().splitlines()]
        self.assertEqual(log[0]["channel"], "discuss-generative-ai")
        self.assertEqual(log[0]["links"][0]["url"], "https://example.com/a")
        self.assertTrue(log[0]["pulled_at"])

    def test_no_channel_id_means_nothing_is_read(self):
        cfg = {"slack": {"channels": [{"channel": "discuss-generative-ai"}]}}
        self.assertEqual(slacksource.fetch_channels(Path(tempfile.mkdtemp()), cfg, "r", logging.getLogger("t")),
                         {"items": [], "sources": []})


if __name__ == "__main__":
    unittest.main()
