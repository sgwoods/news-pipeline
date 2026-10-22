"""Written-edition format rules from the 10-13 review: citations, dates, verdict labels, caps (no models)."""
import unittest

from pipeline import editorial as e


def rec(i, person, kind="rss", linked="", tier="follow", published="2026-10-13", importance=4):
    return {"id": i, "url": f"https://bsky.app/profile/x/post/{i}" if kind == "bluesky" else f"https://ex.com/{i}",
            "source_kind": kind, "linked_url": linked, "person": person, "tier": tier, "published": published,
            "importance": importance, "title": f"Item {i}", "claim": f"Claim {i}."}


class TestFormatSpec(unittest.TestCase):
    def test_wire_post_cites_the_article(self):
        r = rec("a", "Techmeme", "bluesky", "https://www.wired.com/story/x")
        self.assertEqual(e._cite_url(r), "https://www.wired.com/story/x")
        self.assertIn("wired.com via Techmeme", e._link(r))
        self.assertEqual(e._cite_url(rec("b", "Simon Willison")), "https://ex.com/b")

    def test_one_author_is_one_source(self):
        self.assertEqual(e.distinct_names(["Marcus on AI (Gary Marcus)", "Gary Marcus"]), ["Marcus on AI (Gary Marcus)"])

    def test_old_items_are_dated(self):
        self.assertEqual(e._age("2026-10-09", "2026-10-13"), "from Fri Oct 9")
        self.assertEqual(e._age("2026-10-12", "2026-10-13"), "")

    def test_verdict_label_and_no_pipeline_talk(self):
        self.assertTrue(e.critical_line({"critical_pass": "only one benchmark"},
                                        {"critique_detail": {"verdict": "unsupported"}}).startswith("Unsupported. "))
        self.assertEqual(e._md("Strong evidence. No critical pass was run. Check proofs."), "Strong evidence. Check proofs.")

    def test_items_per_source_cap(self):
        stories = [{"names": ["Anthropic"], "ids": [str(i)], "lead": {"importance": 4}, "score": 4.5, "rank": i,
                    "wire_only": False} for i in range(6)]
        sel = e.select(stories, {"max_must_read": 5, "max_worth_knowing": 5, "max_in_brief": 8,
                                 "max_stories_per_source": 5, "max_items_per_source": 3})
        self.assertEqual(len(sel["must"]) + len(sel["worth"]) + len(sel["brief"]), 3)


if __name__ == "__main__":
    unittest.main()


class FakeResp:
    def __init__(self, data=None, url="", status=200):
        self._d, self.url, self.status_code = data, url, status

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeClient:
    def get(self, url, params=None):
        if "resolveHandle" in url:
            return FakeResp({"did": "did:plc:techmeme"})
        if "getPosts" in url:
            assert params["uris"].startswith("at://did:")
            return FakeResp({"posts": [{"record": {"text": "Anthropic says... techmeme.com/x", "facets": [
                {"features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://www.techmeme.com/261013/p5"}]}]}}]})
        if "/api/v1/archive" in url:
            return FakeResp([{"title": "OpenAI Fires Three Safety Researchers",
                              "canonical_url": "https://thezvi.substack.com/p/openai-fires-three-safety-researchers"}])
        if "trib.al" in url:
            return FakeResp(url="https://www.technologyreview.com/2026/10/13/short-dramas/")
        return FakeResp(status=404)


class TestLinks(unittest.TestCase):
    def test_better_urls(self):
        from pipeline import links
        c = FakeClient()
        self.assertEqual(links.better_url(c, "https://trib.al/CQEj11m"),
                         "https://www.technologyreview.com/2026/10/13/short-dramas/")
        self.assertEqual(links.better_url(c, "https://thezvi.substack.com/#issue-771e6065", "OpenAI Fires Three Safety Researchers"),
                         "https://thezvi.substack.com/p/openai-fires-three-safety-researchers")
        self.assertEqual(links.better_url(c, "https://bsky.app/profile/techmeme.com/post/3mxq", "", "bluesky"),
                         "https://www.techmeme.com/261013/p5")
