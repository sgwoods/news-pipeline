import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import episodes, mailer, site

MD = """# AI Briefing · Wednesday, October 7, 2026

**The day in brief.** Agents went rogue <script>x</script>.

## Top of mind

- **Agents are a liability question.** Wikimedia reports edits. [1](https://x.com/a)

## Must read

### 1. OpenAI agents edit Wikimedia
**Simon Willison** · [source](https://x.com/a) · 2026-10-07

*Developing story · day 2 · first in the briefing Oct 6*

- **What happened:** Agents edited pages ([Willison](https://x.com/a)).
- **Critical pass:** Mixed. Thin evidence.
- **Editor's view:** Ask for logs.

## Open questions

- **Who audits agents?** Nobody yet. *Settled by: a policy.* [1](https://x.com/a)
"""
CFG = {"email": {"script_url": "https://script.google.com/macros/s/abc/exec"},
       "publish": {"site_url": "https://u.example/b/"}}


class TestMailer(unittest.TestCase):
    def test_render(self):
        m = mailer.render("2026-10-07", MD, CFG, has_audio=True)
        self.assertEqual(m["subject"], "AI Briefing · Wed Oct 7: Agents are a liability question")
        h = m["html"]
        self.assertIn("{{UNSUBSCRIBE}}", h)
        self.assertIn("{{UNSUBSCRIBE}}", m["text"])
        self.assertNotIn("<script>", h)
        self.assertIn("https://u.example/b/2026-10-07/", h)
        self.assertIn("Developing story · day 2", h)
        self.assertIn("Editor's view", h)
        self.assertIn("Who audits agents?", h)
        self.assertIn("Written and read by AI", h)
        self.assertNotIn("[1]", h)

    def test_send_rules(self):
        root = Path(tempfile.mkdtemp())
        (root / "briefings").mkdir()
        (root / "briefings" / "2026-10-07.md").write_text(MD)
        calls = []
        def fake(cfg, action, **p):
            calls.append((action, p))
            return {"ok": True, "sent": 1 if p.get("to") else 3, "quota": 90}
        with mock.patch.object(mailer, "call", fake):
            rec = mailer.send_day(root, CFG, "2026-10-07", to="me@x.com")
            self.assertTrue(rec["test"])
            rec = mailer.send_day(root, CFG, "2026-10-07")
            self.assertEqual(rec["sent"], 3)
            self.assertIn("skipped", mailer.send_day(root, CFG, "2026-10-07"))      # once per day
            episodes.set_hidden(root, "2026-10-07", True)
            with self.assertRaises(mailer.MailError):
                mailer.send_day(root, CFG, "2026-10-07", force=True)
        self.assertEqual([a for a, _ in calls], ["send", "send"])
        log = [json.loads(x) for x in (root / mailer.LOG).read_text().splitlines()]
        self.assertNotIn("me@x.com", json.dumps(log))                                  # no addresses in the repo

    def test_ready_and_site_form(self):
        with mock.patch.object(mailer, "key", lambda: ""):
            self.assertIn("EMAIL_SCRIPT_KEY", mailer.ready(CFG))
        self.assertIn("script_url", mailer.ready({}))
        html = site.landing(CFG, None, [], "", False)
        self.assertIn('action="https://script.google.com/macros/s/abc/exec"', html)
        self.assertIn('name="website"', html)
        self.assertNotIn("Get it by email", site.landing({}, None, [], "", False))


if __name__ == "__main__":
    unittest.main()
