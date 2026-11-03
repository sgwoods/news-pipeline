"""New senders under the sources label become sources as they arrive (Steven, 2026-11-03), in a code-written file;
newsletters.yaml stays hand-edited. Notices, people on mail providers and Steven himself are never added."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import mailsource as ms

M = {"forwarders": ["owner@example.com"], "label": "AI-Briefing/Sources", "max_chars": 20000, "account": "x@example.com"}


def raw(frm, subject, body="<p>Issue text about GPUs.</p>"):
    return (f"From: {frm}\r\nSubject: {subject}\r\nDate: Tue, 03 Nov 2026 07:00:00 +0000\r\n"
            f"Message-ID: <m1@example>\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{body}").encode()


class AutoAdd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "newsletters.yaml").write_text("- name: Known\n  from: [known@news.example]\n  tier: follow\n")

    def test_new_sender_added_and_read_as_listed(self):
        e = ms.auto_add(self.root, "lspace@mail.beehiiv.com", "Latent Space", "[AINews] weights", "2026-11-03", M)
        self.assertEqual(e["name"], "Latent Space")
        self.assertTrue(e["scrutiny"])
        self.assertIn("AUTO-ADDED", e["flags"])
        nl = ms.load_newsletters(self.root)
        it = ms.parse_message(raw("Latent Space <lspace@mail.beehiiv.com>", "[AINews] weights"), nl, M, "r", ms.dt.datetime.now(ms.UTC))
        self.assertFalse(it["unlisted"])
        self.assertEqual(it["person"], "Latent Space")
        self.assertTrue(it["scrutiny"])
        self.assertIn("unreviewed", it["source_note"])

    def test_hand_file_untouched_and_wins(self):
        before = (self.root / "newsletters.yaml").read_text()
        self.assertIsNone(ms.auto_add(self.root, "known@news.example", "Known", "s", "2026-11-03", M))
        ms.auto_add(self.root, "new@letter.example", "Known", "s", "2026-11-03", M)       # name clash -> suffixed
        self.assertEqual((self.root / "newsletters.yaml").read_text(), before)
        names = [n["name"] for n in ms.load_newsletters(self.root)]
        self.assertEqual(names.count("Known"), 1)
        self.assertIn("Known (new@letter.example)", names)

    def test_added_once(self):
        ms.auto_add(self.root, "a@futurism.example", "Futurism", "s", "2026-11-03", M)
        self.assertIsNone(ms.auto_add(self.root, "a@futurism.example", "Futurism", "s2", "2026-11-04", M))
        self.assertEqual(sum(n["name"] == "Futurism" for n in ms.load_newsletters(self.root)), 1)

    def test_never_notices_people_or_owner(self):
        for a in ("no-reply@substack.com", "notification@slack-mail.com", "forwarding-noreply@google.com",
                  "friend@gmail.com", "owner@example.com", "feedback@slack.com"):
            self.assertIsNone(ms.auto_add(self.root, a, "X", "s", "2026-11-03", M), a)
        self.assertFalse((self.root / ms.AUTO).exists())

    def test_waiting_unlisted_adopted(self):
        st = self.root / "data" / "state"
        st.mkdir(parents=True)
        (st / "email-unlisted.json").write_text(json.dumps({
            "aidailybrief@mail.beehiiv.com": {"name": "AI Daily Brief", "subject": "Deslopify", "date": "2026-11-03"},
            "no-reply@slack.com": {"name": "Slack", "subject": "Set up Slack", "date": "2026-10-19"}}))
        added = ms.adopt_unlisted(self.root, M)
        self.assertEqual([e["from"][0] for e in added], ["aidailybrief@mail.beehiiv.com"])


if __name__ == "__main__":
    unittest.main()
