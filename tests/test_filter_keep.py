"""Filter fail-open and the second look (selection review, 2026-11-13): publications from the briefing's own beats and
deals with amounts never go through the model filter; Claude gets one look at what the model dropped."""
import unittest

from pipeline import stages

CFG = {"filter_keep_flags": ["PORTFOLIO"], "filter_keep_tiers": ["follow closely", "scrutiny"],
       "filter_keep_sources": ["Artificial Lawyer", "The Robot Report"], "filter_batch": 5, "filter_chars": 1200,
       "filter_skip_kinds": ["site", "feed", "pages"], "filter_skip_min_chars": 800}


def item(i, person, kind, title, text="A short post.", tier="added", flags=()):
    return {"id": f"i{i}", "person": person, "source_kind": kind, "title": title, "text": text, "tier": tier,
            "flags": list(flags), "url": f"https://x.example/{i}", "published": "2026-11-13"}


class Protected(unittest.TestCase):
    def test_portfolio_and_beat_publications_skip_the_model(self):
        self.assertIn("portfolio", stages.protected_from_model_drop(item(1, "Lexgrove blog", "site", "Pricing update", flags=["PORTFOLIO"]), CFG))
        self.assertIn("beat", stages.protected_from_model_drop(item(2, "Artificial Lawyer", "feed", "Copilot for Legal Won't Cannibalize Us – Litera"), CFG))
        self.assertIn("follow closely", stages.protected_from_model_drop(item(3, "Import AI", "email", "Issue 400", tier="follow closely"), CFG))

    def test_social_posts_from_the_same_people_still_go_to_the_model(self):
        self.assertEqual(stages.protected_from_model_drop(item(4, "Gary Marcus", "bluesky", "I got to meet the Pope!", tier="scrutiny"), CFG), "")
        self.assertEqual(stages.protected_from_model_drop(item(5, "Artificial Lawyer", "x", "Come see us next week", tier="added"), CFG), "")

    def test_deals_with_amounts_are_protected_from_any_source(self):
        for t in ["Oura to acquire AI-native primary care startup Counsel Health for $625M",
                  "UPDATE - Shield AI $28.8B post-money Series H announcement",
                  "Munich-based Agile Robots raised $500M at a reported $8.5B valuation",
                  "Fractile confirms £540m raise first revealed by Sifted"]:
            self.assertEqual(stages.protected_from_model_drop(item(6, "Techmeme", "bluesky", t), CFG), "a deal with an amount", t)
        self.assertEqual(stages.protected_from_model_drop(item(7, "Techmeme", "bluesky", "Cloudflare reports Q3 revenue up 39% YoY to $782.5M"), CFG), "")
        self.assertEqual(stages.protected_from_model_drop(item(8, "Sifted", "feed", "UCL spinouts looking to raise"), CFG), "")

    def test_run_filter_marks_protected_items(self):
        class NoModel:
            label = "none"
            def complete_json(self, *a, **k):
                raise AssertionError("the model must not be called for protected items")
        items = [item(1, "Artificial Lawyer", "feed", "Vetta bids for Weil lawyers")]
        d, _, errs = stages.run_filter(NoModel(), items, "sys", CFG, _Log())
        self.assertTrue(d["i1"]["keep"] and d["i1"].get("protected"))
        self.assertEqual(errs, [])


class Rescue(unittest.TestCase):
    def test_second_look_rescues_named_items_only(self):
        items = [item(1, "Artificial Lawyer", "feed", "Scissero Seeks Weil Gotshal Lawyers + Assets"),
                 item(2, "Techmeme", "bluesky", "Lyft reports Q3 revenue up 8%"),          # social: not offered
                 item(3, "TechCrunch AI", "feed", "Democrats launch Nvidia investigation"),
                 item(4, "WIRED", "feed", "Adult content creators sound the alarm over a UK law")]
        decisions = {"i1": {"keep": False, "reason": "no AI business value claim"},
                     "i2": {"keep": False, "reason": "not AI"},
                     "i3": {"keep": False, "reason": "Policy on Nvidia China sales not AI topic"},
                     "i4": {"keep": False, "reason": "not AI-related"},
                     "i5": {"keep": False, "rule": True, "reason": "translated duplicate"}}
        seen = {}
        class Claude:
            label = "claude"
            def complete_json(self, system, user, max_tokens=0, **k):
                seen["user"] = user
                return {"rescue": [{"id": "i1", "why": "legal AI, portfolio beat"}, {"id": "i3", "why": "AI supplier policy"}, {"id": "i2", "why": "no"}]}
        rescued, _v, errs = stages.run_rescue(Claude(), items, decisions, "sys", {"rescue_max_items": 40}, _Log())
        self.assertEqual(sorted(rescued), ["i1", "i3"])
        self.assertTrue(decisions["i1"]["keep"] and decisions["i1"].get("rescued"))
        self.assertFalse(decisions["i2"]["keep"])                                  # social posts are not offered
        self.assertFalse(decisions["i4"]["keep"])
        self.assertNotIn("i2", seen["user"]); self.assertNotIn("i5", seen["user"])
        self.assertIn("Scissero", seen["user"])

    def test_nothing_to_rescue_makes_no_call(self):
        class Boom:
            label = "x"
            def complete_json(self, *a, **k):
                raise AssertionError("no call expected")
        rescued, _v, errs = stages.run_rescue(Boom(), [item(1, "Techmeme", "bluesky", "x")], {"i1": {"keep": False, "reason": "chatter"}}, "sys", {}, _Log())
        self.assertEqual((rescued, errs), ({}, []))


class _Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass


if __name__ == "__main__":
    unittest.main()
