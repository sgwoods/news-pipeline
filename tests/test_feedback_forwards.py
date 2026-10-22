"""Editor-forwarded reader emails and copies of the edition in the Feedback label."""
import unittest
from email.message import EmailMessage

from pipeline import feedback as fb

CFG = {}


def msg(body, frm="Steven Woods <you@example.com>", subject="Fwd: Re: AI Briefing · Mon Oct 19: Three threads",
        reply_to=None):
    m = EmailMessage()
    m["From"], m["Subject"], m["Date"] = frm, subject, "Tue, 20 Oct 2026 08:50:00 -0400"
    m["Message-ID"] = f"<{abs(hash(body + subject))}@example.com>"
    if reply_to:
        m["In-Reply-To"] = reply_to
    m.set_content(body)
    return m.as_bytes()


GMAIL_FWD = ("FYI, useful\n\nSteven Woods\n<https://about.me/sgw>\n\n"
             "---------- Forwarded message ---------\n"
             "From: Rob Reader <rob@example.org>\n"
             "Date: Mon, Oct 19, 2026 at 9:10 AM\n"
             "Subject: Re: AI Briefing · Mon Oct 19: Three threads\n"
             "To: Steven Woods <you@example.com>\n\n\n"
             "Two thoughts: shorter top section, and more on Canadian startups.\n\n"
             "On Mon, Oct 19, 2026 at 6:45 AM AI Briefing <you@example.com> wrote:\n> the edition\n")

OUTLOOK_FWD = ("________________________________\n"
               "From: Rob Reader [mailto:rob@example.org]\n"
               "Sent: Monday, October 19, 2026 9:10 AM\n"
               "To: Steven Woods\n"
               "Subject: RE: AI Briefing · Mon Oct 19: Three threads\n\n"
               "The deep dive was the best part.\n")


class ForwardTests(unittest.TestCase):
    def test_gmail_forward_credits_reader(self):
        it = fb.parse_reply(msg(GMAIL_FWD), CFG)
        self.assertEqual(it["name"], "Rob")
        self.assertFalse(it["from_editor"])
        self.assertTrue(it["forwarded_by_editor"])
        self.assertIn("Canadian startups", it["text"])
        self.assertNotIn("the edition", it["text"])
        self.assertNotIn("Forwarded message", it["text"])
        self.assertNotIn("example.org", str(it))
        self.assertIn("FYI, useful", it.get("editor_note", ""))
        self.assertEqual(it["day"], "2026-10-19")
        self.assertEqual(it["subject"], "AI Briefing · Mon Oct 19: Three threads")

    def test_outlook_forward(self):
        it = fb.parse_reply(msg(OUTLOOK_FWD, frm="Steven Woods <you@example.com>"), CFG)
        self.assertEqual(it["name"], "Rob")
        self.assertEqual(it["text"], "The deep dive was the best part.")

    def test_reader_unsubscribe_inside_forward_still_flagged(self):
        body = GMAIL_FWD.replace("Two thoughts", "Please unsubscribe me. Two thoughts")
        self.assertEqual(fb.parse_reply(msg(body), CFG)["triage"]["category"], "unsubscribe")

    def test_edition_copy_is_not_feedback(self):
        edition = "AI Briefing · Monday, October 19, 2026\n\nThree threads.\n\nUnsubscribe: reply 'unsubscribe'."
        self.assertIsNone(fb.parse_reply(msg(edition, frm="AI Briefing <briefing@example.com>",
                                             subject="AI Briefing · Mon Oct 19: Three threads"), CFG))

    def test_plain_editor_reply_unchanged(self):
        it = fb.parse_reply(msg("agree on all", subject="Re: AI Briefing · Mon Oct 19: x", reply_to="<a@b>"), CFG)
        self.assertTrue(it["from_editor"])
        self.assertNotIn("forwarded_by_editor", it)


if __name__ == "__main__":
    unittest.main()
