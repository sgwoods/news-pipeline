"""A publish that fails on the network is retried for a while (11-17/18: hotel Wi-Fi dropped DNS at the push)."""
import unittest
from unittest import mock

import run


class PublishRetry(unittest.TestCase):
    def test_retries_until_the_network_is_back(self):
        calls = {"publish": 0, "net": 0}
        slept = []

        def net(minutes=10, host=""):
            calls["net"] += 1
            return calls["net"] >= 2                 # down on the first look, back on the second (no sleep: minutes elapse inside)

        def publish(cfg, sub="run"):
            calls["publish"] += 1
            return 0 if calls["publish"] >= 2 else 1  # the first push fails, the second lands
        cfg = {"publish": {"retry_every_minutes": 10, "retry_minutes": 120}}
        with mock.patch.object(run, "wait_for_network", net), mock.patch.object(run, "cmd_publish", publish), \
             mock.patch("builtins.print", lambda *a, **k: None):
            code = run._publish_with_retry(cfg, sleep=slept.append)
        self.assertEqual(code, 0)
        self.assertEqual(calls["publish"], 2)
        self.assertEqual(slept, [600])               # one failed push, one wait (the network wait is separate)

    def test_gives_up_after_the_budget(self):
        cfg = {"publish": {"retry_every_minutes": 10, "retry_minutes": 0}}
        with mock.patch.object(run, "wait_for_network", lambda **k: True), mock.patch.object(run, "cmd_publish", lambda c, sub="run": 1), \
             mock.patch("builtins.print", lambda *a, **k: None):
            self.assertEqual(run._publish_with_retry(cfg, sleep=lambda s: None), 1)
