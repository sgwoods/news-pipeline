import unittest

from pipeline import stages


class TestLabelsAndSocialDupes(unittest.TestCase):
    def test_social_post_announcing_archived_article_is_dropped(self):
        post = {"id": "p", "url": "https://bsky.app/profile/x/post/1", "source_kind": "bluesky", "title": "t",
                "text": "Free newsletter: lots of words here. | www.wheresyoured.at/dead-money/ | more"}
        trunc = {"id": "q", "url": "https://bsky.app/profile/x/post/2", "source_kind": "bluesky", "title": "t",
                 "text": "Premium: long words here please. | https://www.wheresyoured.at/premium-how-has-ai-"}
        own = {"id": "r", "url": "https://bsky.app/profile/x/post/3", "source_kind": "bluesky", "title": "t",
               "text": "An original thought with a link to example.com/ only and enough words to keep."}
        known = {"https://www.wheresyoured.at/dead-money/",
                 "https://www.wheresyoured.at/premium-how-has-ai-changed-the-economy/"}
        rest, d = stages.prefilter([post, trunc, own], known, 25)
        self.assertEqual([x["id"] for x in rest], ["r"])
        self.assertIn("already archived", d["p"]["reason"])
        self.assertIn("already archived", d["q"]["reason"])

    def test_labels(self):
        rows = [{"url": "https://www.anthropic.com/news/x", "person": "Dario Amodei"},
                {"url": "https://www.darioamodei.com/essay", "person": "Dario Amodei"}]
        stages.apply_labels(rows, {"anthropic.com": "Anthropic"})
        self.assertEqual([stages.display_name(r) for r in rows], ["Anthropic", "Dario Amodei"])
        block = stages.item_block({**rows[0], "id": "i", "text": "x"}, 100)
        self.assertIn("source: Anthropic (organization; filed under tracked person Dario Amodei)", block)


if __name__ == "__main__":
    unittest.main()
