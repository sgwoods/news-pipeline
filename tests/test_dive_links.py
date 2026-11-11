"""Deep-dive link checks (pipeline/dive.py, 2026-11-09): browser User-Agent, archive.org fallback on a bot wall,
paywalled outlets kept and labelled, and the two-live-one-open rule."""
import unittest
from contextlib import contextmanager
from unittest import mock

from pipeline import dive


class R:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}

    def json(self):
        return self._body


class FakeClient:
    """status by URL; archive.org answers from `archived`."""
    def __init__(self, codes: dict, archived: set = ()):
        self.codes, self.archived, self.headers, self.calls = codes, set(archived), {}, []

    def head(self, u):
        self.calls.append(("HEAD", u))
        return R(self.codes.get(u, 404))

    def get(self, u, timeout=None):
        self.calls.append(("GET", u))
        if u.startswith(dive.WAYBACK):
            target = u[len(dive.WAYBACK):]
            return R(200, {"archived_snapshots": {"closest": {"available": True}} if target in self.archived else {}})
        return R(self.codes.get(u, 404))


def _patched(fake):
    seen = {}

    @contextmanager
    def client(**kw):
        seen.update(kw)
        yield fake
    return client, seen


class CheckLinks(unittest.TestCase):
    def run_check(self, codes, archived=(), headless=""):
        fake = FakeClient(codes, archived)
        client, seen = _patched(fake)
        with mock.patch("pipeline.netguard.client", client), \
             mock.patch("pipeline.headless.fetch", lambda u, cfg: headless), \
             mock.patch("time.sleep", lambda s: None):
            out = dive.check_links(list(codes), {"fetch": {"user_agent": "news-pipeline/0.1"}})
        return out, fake, seen

    def test_browser_user_agent(self):
        _, _, seen = self.run_check({"https://en.wikipedia.org/wiki/X": 200})
        self.assertIn("Mozilla/5.0", seen["headers"]["User-Agent"])          # not the feed reader's name

    def test_open_live_and_dead(self):
        out, _, _ = self.run_check({"https://a.example/ok": 200, "https://a.example/gone": 404})
        self.assertIs(out["https://a.example/ok"], True)
        self.assertIs(out["https://a.example/gone"], False)

    def test_bot_wall_with_archive_snapshot_is_live(self):
        u = "https://en.wikipedia.org/wiki/Transformer"
        out, _, _ = self.run_check({u: 403}, archived={u})
        self.assertIs(out[u], True)
        out, _, _ = self.run_check({u: 403})                                  # no snapshot, headless empty -> dead
        self.assertIs(out[u], False)

    def test_paywalled_outlet_is_kept_and_labelled(self):
        u = "https://www.ft.com/content/abc"
        out, _, _ = self.run_check({u: 403})
        self.assertEqual(out[u], "paywalled")
        self.assertTrue(out[u])                                                # truthy: the citation is kept
        out, _, _ = self.run_check({"https://www.wsj.com/articles/x": 200})
        self.assertEqual(out["https://www.wsj.com/articles/x"], "paywalled")
        out, _, _ = self.run_check({"https://www.reuters.com/x": 404})         # a paywalled outlet can still be dead
        self.assertIs(out["https://www.reuters.com/x"], False)

    def test_paywalled_hosts(self):
        self.assertTrue(dive.paywalled("https://www.theinformation.com/articles/x"))
        self.assertTrue(dive.paywalled("https://ft.com/x"))
        self.assertFalse(dive.paywalled("https://techcrunch.com/x"))
        self.assertFalse(dive.paywalled("https://notft.com/x"))


if __name__ == "__main__":
    unittest.main()
