import datetime as dt
import unittest
from email.message import EmailMessage

from pipeline import mailsource

NL = [{"name": "Lenny's Newsletter", "from": ["lenny@substack.com"], "tier": "follow", "bias": "b"}]
CFG = mailsource.mcfg({})


def fwd(orig_from, body):
    m = EmailMessage()
    m["From"], m["To"] = "Steven <you@example.com>", "you+briefing@example.com"
    m["Subject"], m["Date"], m["Message-ID"] = "Fwd: Q4 plan", "Wed, 14 Oct 2026 09:00:00 -0400", "<f1@x>"
    m.set_content(f"---------- Forwarded message ---------\nFrom: {orig_from}\nDate: Tue\nSubject: Q4 plan\nTo: team\n\n{body}")
    return m.as_bytes()


class ForwardPrivacy(unittest.TestCase):
    def test_internal_forward_keeps_only_public_links(self):
        raw = fwd("Partner <partner@example-firm.com>",
                  "Confidential: fund numbers are 42. See https://www.reuters.com/a and https://docs.google.com/x")
        it = mailsource.parse_message(raw, NL, CFG, "r", dt.datetime.now(dt.timezone.utc))
        self.assertNotIn("Confidential", it["text"])
        self.assertNotIn("42", it["text"])
        self.assertIn("https://www.reuters.com/a", it["text"])
        self.assertNotIn("docs.google.com", it["text"])

    def test_newsletter_forward_keeps_body(self):
        raw = fwd("Lenny <lenny@substack.com>", "This week: how Meta designed Muse.")
        it = mailsource.parse_message(raw, NL, CFG, "r", dt.datetime.now(dt.timezone.utc))
        self.assertIn("how Meta designed Muse", it["text"])


if __name__ == "__main__":
    unittest.main()
