"""The morning Slack post with the day's card (Steven, 2026-10-28): published content only, posted by the bot,
gated like every outbound step, once per day."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import card, release, slackpost

DAY = "2026-10-28"
MD = """# AI Briefing · Wednesday, October 28, 2026

## Today in 30 seconds

- **Anthropic's S-1 locks in founder control.** A Class F share. [1](https://x.com/1)
- **Open-weight price pressure.** Kimi. [5](https://x.com/5)
- **Chatbot liability test case.** A family is suing. [3](https://x.com/3)
- **Fourth thing.** More.

## Must read

### 1. Story
"""
NOTES = {"overall": {"title": "The day overall", "text": "Liability evolution is one of the biggest issues."},
         "k1": {"title": "Story", "text": "Massive demand or bust."},
         "k3": {"title": "Family sues OpenAI", "text": "Regulated industries are regulated for a reason. Giving medical advice without a licence is a regulated activity, and courts may ask why software gets to do it."}}
CFG = {"paths": {"briefings": "briefings"}, "publish": {"site_url": "https://u.github.io/b/"},
       "slack": {"channel": "cto-musings", "post": {"enabled": True}}}


def make_root():
    root = Path(tempfile.mkdtemp())
    (root / "briefings").mkdir()
    (root / "data" / "commentary").mkdir(parents=True)
    (root / "assets" / "fonts").mkdir(parents=True)
    (root / "briefings" / f"{DAY}.md").write_text(MD)
    (root / "data" / "commentary" / f"{DAY}.json").write_text(json.dumps({"day": DAY, "notes": NOTES}))
    return root


class Card(unittest.TestCase):
    def test_leads_and_take(self):
        self.assertEqual(card.leads(MD), ["Anthropic's S-1 locks in founder control", "Open-weight price pressure", "Chatbot liability test case"])
        take, where = card.pick_take(NOTES, "")
        self.assertTrue(take.startswith("Regulated industries"))
        self.assertEqual(where, "Family sues OpenAI")
        self.assertEqual(card.pick_take({"overall": {"title": "The day overall", "text": "Short."}})[0], "")

    def test_render_makes_a_png(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed here")
        root = make_root()
        p = card.render(root, DAY, MD, NOTES, "Merging the Labs", "One line.", "")
        self.assertTrue(p.is_file())
        self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class Post(unittest.TestCase):
    def test_build_text(self):
        root = make_root()
        with mock.patch.object(card, "render", return_value=None):
            out = slackpost.build(root, CFG, DAY)
        self.assertIn("*AI Briefing · Wed Oct 28*", out["text"])
        self.assertIn("Anthropic's S-1 locks in founder control · Open-weight price pressure · Chatbot liability test case.", out["text"])
        self.assertIn("Steven's take on Family sues OpenAI", out["text"])
        self.assertIn("<https://u.github.io/b/2026-10-28/|Read>", out["text"])
        self.assertNotIn("Deep dive", out["text"])                    # none published that day

    def test_post_is_gated_once_a_day_and_never_in_staging(self):
        root = make_root()
        calls = []

        class R:
            def __init__(self, data):
                self.data, self.status_code = data, 200

            def json(self):
                return self.data

        class Client:
            def post(self, url, **kw):
                calls.append(url)
                if url.endswith("conversations.list"):
                    return R({"ok": True, "channels": [{"name": "cto-musings", "id": "C1"}]})
                if url.endswith("chat.postMessage"):
                    return R({"ok": True, "ts": "1"})
                return R({"ok": True})
        with mock.patch.object(slackpost, "token", return_value="xoxb-test"), \
             mock.patch.object(card, "render", return_value=None), \
             mock.patch.object(release, "require", side_effect=lambda *a, **k: calls.append("require")):
            r = slackpost.post(root, CFG, DAY, log=lambda *a: None, client=Client())
            self.assertTrue(r["ok"])
            self.assertEqual(calls[0], "require")
            self.assertTrue(any(c.endswith("chat.postMessage") for c in calls))
            self.assertIn("already posted", slackpost.post(root, CFG, DAY, log=lambda *a: None, client=Client())["skipped"])
        with mock.patch.object(slackpost, "token", return_value=""):
            self.assertIn("SLACK_BOT_TOKEN", slackpost.post(root, CFG, "2026-10-29", log=lambda *a: None)["skipped"])
        self.assertIn("off", slackpost.post(root, {**CFG, "slack": {"channel": "x"}}, "2026-10-29")["skipped"])

    def test_deep_dive_replies_in_the_morning_thread(self):
        root = make_root()
        (root / "briefings" / "deepdives").mkdir()
        (root / "briefings" / "deepdives" / f"{DAY}.md").write_text("# Deep dive: Merging the Labs\n\n*x*\n\nOne story.\n")
        (root / "briefings" / "deepdives" / f"{DAY}.mp3").write_bytes(b"x")
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "deepdives.jsonl").write_text(json.dumps({"day": DAY, "status": "published", "title": "Deep dive: Merging the Labs", "minutes": 10.4}) + "\n")
        calls = []

        class R:
            def __init__(self, data):
                self.data, self.status_code = data, 200

            def json(self):
                return self.data

        class Client:
            def post(self, url, **kw):
                calls.append((url, kw))
                if url.endswith("conversations.list"):
                    return R({"ok": True, "channels": [{"name": "cto-musings", "id": "C1"}]})
                if url.endswith("chat.postMessage"):
                    return R({"ok": True, "ts": "100.1" if "thread_ts" not in (kw.get("data") or {}) else "100.2"})
                return R({"ok": True})
        with mock.patch.object(slackpost, "token", return_value="xoxb-test"), \
             mock.patch.object(card, "render", return_value=None), mock.patch.object(card, "render_dd", return_value=None), \
             mock.patch.object(release, "require", side_effect=lambda *a, **k: None):
            r = slackpost.post(root, CFG, DAY, log=lambda *a: None, client=Client())
        self.assertEqual(r["ts"], "100.1")
        self.assertTrue(r["deepdive"]["ok"])
        replies = [kw["data"] for url, kw in calls if url.endswith("chat.postMessage") and "thread_ts" in (kw.get("data") or {})]
        self.assertEqual(replies[0]["thread_ts"], "100.1")
        self.assertIn("Deep dive · Merging the Labs", replies[0]["text"])
        rows = slackpost._stamps(root)
        self.assertEqual([x["kind"] for x in rows], ["main", "deepdive"])
        with mock.patch.object(slackpost, "token", return_value="xoxb-test"):
            self.assertIn("already posted", slackpost.post_dd(root, CFG, DAY, log=lambda *a: None, client=Client())["skipped"])

    def test_outbound_invariant_lists_the_post(self):
        self.assertIn(("pipeline/slackpost.py", "post"), release.OUTBOUND)

    def test_setup_wants_a_bot_token(self):
        self.assertIn("isn't a bot token", slackpost.set_token(ask=lambda p: "xoxp-user-token-not-allowed"))
