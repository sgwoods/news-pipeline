import unittest

from pipeline import links

CFG = {"email_sources": {"account": "you@example.com"}}


class PersonalLinks(unittest.TestCase):
    def test_output_never_carries_personal_links(self):
        md = ("See [Rundown](https://link.mail.beehiiv.com/ss/c/u001.x) and [Verge](https://www.theverge.com/ai?utm_source=x&_bhlid=1) "
              "[manage](https://zvi.substack.com/account/settings) [open](https://a.com/p?email=sgwoods%2Bbriefing%40gmail.com) "
              "[deal](https://www.reuters.com/openai-confirms-deal) sent to you+briefing@example.com")
        out, gone = links.scrub_output(md, CFG)
        self.assertNotIn("beehiiv", out)
        self.assertNotIn("account/settings", out)
        self.assertNotIn("%40", out)
        self.assertNotIn("sgwoods", out)
        self.assertIn("[Verge](https://www.theverge.com/ai)", out)
        self.assertIn("[deal](https://www.reuters.com/openai-confirms-deal)", out)
        self.assertEqual(len(gone), 4)

    def test_inbound_keeps_content_drops_footer(self):
        body = ("Meta released Muse Wonder.\nGPT-6.1 parity claims are unverified.\n"
                "You are receiving this because you subscribed as you+briefing@example.com\nUnsubscribe | Manage preferences")
        out = links.scrub_inbound(body, CFG)
        self.assertIn("Muse Wonder", out)
        self.assertNotIn("sgwoods", out)
        self.assertNotIn("Unsubscribe", out)

    def test_account_links_never_followed(self):
        class C:
            def get(self, *a, **k):
                raise AssertionError("must not be requested")
        self.assertEqual(links.better_url(C(), "https://x.substack.com/action/disable_email?token=abc"), "")


if __name__ == "__main__":
    unittest.main()
