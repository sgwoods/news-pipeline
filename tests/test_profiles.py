import unittest

from pipeline import editorial, profiles, stages


def r(i, person, url, kind="bluesky", linked="", imp=5):
    return {"id": i, "person": person, "url": url, "linked_url": linked, "source_kind": kind, "tier": "follow closely",
            "importance": imp, "claim": "c", "headline": "h"}


class Profiles(unittest.TestCase):
    def test_cited_site_decides(self):
        p = profiles.profile(r("1", "Techmeme", "https://bsky.app/x", linked="https://www.reuters.com/a"))
        self.assertEqual((p["kind"], p["site"]), ("reporting", "reuters.com"))
        self.assertEqual(profiles.profile(r("2", "Gary Marcus", "https://garymarcus.substack.com/p/x", "site"))["kind"], "opinion")
        self.assertEqual(profiles.profile(r("3", "Someone", "https://bsky.app/y"))["kind"], "social")
        self.assertEqual(profiles.profile(r("4", "X", "https://bsky.app/z", linked="https://blog.character.ai/u"))["kind"], "primary")
        self.assertEqual(profiles.profile(r("5", "X", "https://www.justice.gov/opa/pr/x", "site"))["kind"], "primary")

    def test_repeats_count_once_and_label(self):
        recs = [r("1", "Techmeme", "https://bsky.app/a", linked="https://www.reuters.com/x"),
                r("2", "TLDR AI", "https://www.reuters.com/x?utm=1", "email"),
                r("3", "Ed Zitron", "https://www.wheresyoured.at/x", "site"),
                r("4", "Pundit", "https://bsky.app/b")]
        ev = profiles.evidence(recs)
        self.assertEqual((ev["primary"], ev["reports"], ev["commentary"]), (0, 1, 2))
        self.assertEqual(profiles.evidence_label(ev), "1 report + 2 commentaries")
        self.assertIn("AI-realist", ev["stances"])

    def test_commentary_only_story_cannot_be_must_read(self):
        recs = [r("a", "Ed Zitron", "https://www.wheresyoured.at/x", "site"), r("b", "Gary Marcus", "https://garymarcus.substack.com/p/y", "site"),
                r("c", "Techmeme", "https://bsky.app/q", linked="https://www.ft.com/content/z")]
        by_id = {x["id"]: x for x in recs}
        st = editorial.build_stories([{"ids": ["a", "b"], "headline": "opinion pair"}, {"ids": ["c"], "headline": "FT scoop"}], by_id)
        sel = editorial.select(st, {})
        self.assertEqual([s["lead"]["id"] for s in sel["must"]], ["c"])
        self.assertIn("a", [s["lead"]["id"] for s in sel["worth"]])
        self.assertEqual(editorial.evidence_byline(sel["must"][0]), " · report")
        line = editorial.evidence_prompt_line(sel["worth"][0])
        self.assertIn("no primary source, report or hands-on test", line)
        self.assertIn("AI-realist", line)

    def test_hands_on_test_counts(self):
        recs = [r("m", "The Rundown AI", "https://www.therundown.ai/p/x", "email"),
                r("w", "Simon Willison", "https://simonwillison.net/2026/Oct/12/x/", "site")]
        ev = profiles.evidence(recs)
        self.assertTrue(ev["grounded"])
        self.assertEqual(profiles.evidence_label(ev), "1 hands-on test + 1 commentary")

    def test_prompts_carry_evidence_type(self):
        it = {"id": "1", "person": "a16z (Substack)", "url": "https://a16z.news/p/x", "source_kind": "email", "title": "t", "text": "x"}
        b = stages.item_block(it, 100)
        self.assertIn("kind=opinion", b)
        self.assertIn("invested across AI", b)


if __name__ == "__main__":
    unittest.main()
