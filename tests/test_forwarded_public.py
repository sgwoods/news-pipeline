import datetime as dt
import email.message
import unittest

from pipeline import mailsource

NOW = dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc)
MARKET = ("Rates and equities: the Bank of Canada held at 2.25% and TSX tech rose 4% on the week. " * 12)


def fwd(body, frm="you@example.com", subject="FW: Weekly market update", to="you+briefing@example.com"):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m.set_content(body)
    return mailsource.parse_message(m.as_bytes(), [], mailsource.mcfg({}), "r", NOW)


class ForwardedPublic(unittest.TestCase):
    def test_outside_material_keeps_its_body_credited_to_the_sender(self):
        it = fwd("FYI\n\n________________________________\nFrom: CIBC Capital Markets <research@cibc.com>\n"
                 "Sent: Monday, October 19, 2026 7:00 AM\nTo: Steven\nSubject: Weekly market update\n\n" + MARKET +
                 "\n\nThis email is confidential and intended only for the recipient. Unsubscribe here.")
        self.assertIn("Bank of Canada held at 2.25%", it["text"])
        self.assertNotIn("FYI", it["text"])                      # Steven's own note is dropped
        self.assertNotIn("intended only for the recipient", it["text"])
        self.assertEqual(it["person"], "CIBC Capital Markets (forwarded)")
        self.assertNotIn("Steven", it["person"])
        self.assertTrue(it["forwarded"])

    def test_internal_or_restricted_mail_stays_links_only(self):
        inside = fwd("________________________________\nFrom: A Partner <ap@example-firm.com>\nSent: today\n\nOur IC notes "
                     "https://example.com/report " + MARKET)
        self.assertIn("only its public links are kept", inside["text"])
        restricted = fwd("________________________________\nFrom: CIBC <research@cibc.com>\nSent: today\n\n"
                         "Not for redistribution. " + MARKET)
        self.assertIn("only its public links are kept", restricted["text"])

    def test_outlook_mailto_form(self):
        it = fwd("-----Original Message-----\nFrom: RBC Research [mailto:research@rbc.com]\nSent: today\n\n" + MARKET)
        self.assertEqual(it["person"], "RBC Research (forwarded)")


    def test_shareable_route_keeps_internal_material_credited_to_the_firm(self):
        from pipeline.owner import get
        share = (get().get("share_addresses") or [""])[0]
        self.assertTrue(share, "owner.yaml share_addresses is empty")
        inside = "________________________________\nFrom: A Partner <ap@example-firm.com>\nSent: today\n\nOur view " + MARKET
        it = fwd(inside, to=share)
        self.assertIn("Bank of Canada held at 2.25%", it["text"])
        self.assertTrue(it["person"].endswith("(shared)"))
        self.assertNotIn("Partner", it["person"])
        self.assertIn("SHARED", it["flags"])
        self.assertIn("only its public links are kept", fwd(inside)["text"])   # the old route is unchanged
        restricted = fwd(inside.replace("Our view", "Not for redistribution. Our view"), to=share)
        self.assertIn("only its public links are kept", restricted["text"])    # explicit markers still win
        note = fwd("Worth a look: " + MARKET, subject="Agents in the enterprise", to=share)
        self.assertEqual(note["person"], "Shared by the editor")
        self.assertIn("Worth a look", note["text"])


if __name__ == "__main__":
    unittest.main()
