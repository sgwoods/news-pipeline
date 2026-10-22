import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from pipeline import suggest

PERSPECTIVE = """# Perspective
## Tracked people
| Name | Tier | Where | Notes |
|---|---|---|---|
| Ed Zitron | follow closely | newsletter (wheresyoured.at) | |
| Elon Musk | SCRUTINY | X | |
"""
CFG = {"paths": {"perspective": "perspective.md", "sources": "sources.yaml", "summaries": "data/summaries"},
       "fetch": {}}


class FakeLLM:
    def __init__(self, out):
        self.out, self.calls = out, []

    def complete_json(self, system, user, retries=1, max_tokens=None):
        self.calls.append((system, user))
        return self.out


def fake_verify(c, cfg, client=None, log=print):
    live = [u for u in (c.get("feeds") or []) if "dead" not in u]
    return {"verified": [{"kind": "bluesky" if "bsky.app" in u else "feed", "url": u, "title": "T",
                          "entries": 5, "latest": "2026-10-01"} for u in live],
            "failed": [{"label": u, "reason": "HTTP 404"} for u in (c.get("feeds") or []) if "dead" in u]}


class TestSuggest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "perspective.md").write_text(PERSPECTIVE, "utf-8")
        (self.root / "sources.yaml").write_text(
            "# GENERATED header\n" + yaml.safe_dump({"verified_at": "x", "sources": [
                {"person": "Ed Zitron", "tier": "follow closely", "flags": [], "scrutiny": False,
                 "kind": "site", "url": "https://wheresyoured.at/rss/"}]}), "utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def queue(self, cands, origin="auto"):
        store = suggest.load_store(self.root)
        added = suggest.enqueue(self.root, CFG, cands, origin, store, log=lambda *a: None, verify=fake_verify)
        suggest.save_store(self.root, store)
        return added

    def test_suggestions_prompt_and_dedupe(self):
        llm = FakeLLM({"suggestions": [
            {"name": "Ed Zitron", "why": "already tracked"},
            {"name": "Dylan Patel", "kind": "person", "why": "SemiAnalysis: compute supply chain",
             "feeds": ["https://semianalysis.com/feed/"], "x": ["@dylan522p"]},
            {"name": "Nobody Online", "why": "X only", "x": ["nobody"], "feeds": ["https://dead.example/feed"]},
        ]})
        store = suggest.load_store(self.root)
        cands = suggest.ask_suggestions(self.root, CFG, 2, store, llm=llm)
        self.assertIn("Ed Zitron", llm.calls[0][1])           # tracked names go into the prompt
        self.assertIn("Tracked people", llm.calls[0][0])      # the perspective is the system prompt
        added = self.queue(cands)
        self.assertEqual([a["name"] for a in added], ["Dylan Patel", "Nobody Online"])
        self.assertTrue(added[0]["reachable"])
        self.assertEqual(added[0]["x"], ["dylan522p"])
        self.assertFalse(added[1]["reachable"])               # kept in the queue even with no live source
        self.assertEqual(added[1]["failed"][0]["reason"], "HTTP 404")
        self.assertEqual(self.queue(cands), [])               # already queued: not added twice

    def test_accept_wires_live_sources(self):
        [row] = self.queue([{"name": "Dylan Patel", "why": "w", "feeds": ["https://semianalysis.com/feed/",
                                                                          "https://bsky.app/profile/dp.bsky.social/rss"],
                             "x": ["dylan522p"]}])
        with mock.patch.object(suggest, "verify_candidate", fake_verify):
            s = suggest.accept(self.root, CFG, row["id"], log=lambda *a: None)
        self.assertEqual(s["status"], "accepted")
        rows = yaml.safe_load((self.root / "sources.yaml").read_text())["sources"]
        self.assertEqual([r["url"] for r in rows][1:], ["https://semianalysis.com/feed/",
                                                         "https://bsky.app/profile/dp.bsky.social/rss"])
        self.assertTrue((self.root / "sources.yaml").read_text().startswith("# GENERATED header"))
        m = suggest.load_managed(self.root)
        e = m["people"]["Dylan Patel"]
        self.assertEqual(e["feeds"], ["https://semianalysis.com/feed/"])
        self.assertEqual(e["bluesky"], ["dp.bsky.social"])
        self.assertEqual(e["other_platforms"], ["X @dylan522p"])
        people, hints = suggest.managed_people(m)              # re-verify sees the managed person
        self.assertEqual(people[0].name, "Dylan Patel")
        self.assertEqual(hints["Dylan Patel"]["feeds"], ["https://semianalysis.com/feed/"])

    def test_accept_without_live_source_goes_to_watch(self):
        [row] = self.queue([{"name": "X Only", "why": "w", "x": ["xonly"]}])
        s = suggest.accept(self.root, CFG, row["id"], log=lambda *a: None)
        self.assertEqual(s["status"], "watch")
        self.assertEqual(len(yaml.safe_load((self.root / "sources.yaml").read_text())["sources"]), 1)
        self.assertEqual(suggest.load_managed(self.root)["people"]["X Only"]["other_platforms"], ["X @xonly"])

    def test_deny_is_remembered_and_fed_back(self):
        [row] = self.queue([{"name": "Hype Guy", "why": "w"}])
        suggest.deny(self.root, row["id"], "pure hype")
        store = suggest.load_store(self.root)
        self.assertEqual(self.queue([{"name": "hype guy", "why": "again"}]), [])
        llm = FakeLLM({"suggestions": []})
        suggest.ask_suggestions(self.root, CFG, 3, store, llm=llm)
        self.assertIn("Hype Guy — pure hype", llm.calls[0][1])
        suggest.reconsider(self.root, row["id"])
        self.assertEqual(suggest.load_store(self.root)[0]["status"], "pending")

    def test_manual_add_requeues_existing(self):
        [row] = self.queue([{"name": "Some One", "why": "w"}])
        again = self.queue([{"name": "Some One", "why": "Added by Steven", "feeds": ["https://s.example/feed"]}],
                           origin="manual")
        self.assertEqual(again[0]["id"], row["id"])
        self.assertTrue(again[0]["reachable"])
        self.assertEqual(len(suggest.load_store(self.root)), 1)

    def test_already_wired_urls_are_not_offered_again(self):
        [row] = self.queue([{"name": "Ed Z Alias", "why": "w", "feeds": ["https://wheresyoured.at/rss/"]}])
        self.assertEqual(row["verified"], [])

    def test_remove_and_restore(self):
        r = suggest.remove_source(self.root, CFG, "https://wheresyoured.at/rss/", "too noisy")
        self.assertEqual(r["person"], "Ed Zitron")
        self.assertEqual(yaml.safe_load((self.root / "sources.yaml").read_text())["sources"], [])
        m = suggest.load_managed(self.root)
        self.assertEqual(suggest.removed_urls(m), {"https://wheresyoured.at/rss/"})
        self.assertEqual(m["removed"][0]["reason"], "too noisy")
        with self.assertRaises(KeyError):
            suggest.remove_source(self.root, CFG, "https://not-wired.example/feed")
        suggest.restore_source(self.root, "https://wheresyoured.at/rss/")
        self.assertEqual(suggest.removed_urls(suggest.load_managed(self.root)), set())

    def test_candidate_groups_skip_social_sites(self):
        gs = suggest.candidate_groups({"name": "A", "sites": ["https://x.com/a", "a.example"],
                                       "feeds": ["https://a.example/feed", "javascript:alert(1)"],
                                       "bluesky": ["@a.bsky.social"]})
        self.assertEqual([g.kind for g in gs], ["site", "bluesky", "feed"])
        self.assertEqual(gs[1].urls, ["https://bsky.app/profile/a.bsky.social/rss"])


    def test_channels_parsed_and_labelled(self):
        c = suggest._normalize({"name": "A", "feeds": [{"url": "https://a.substack.com/feed", "channel": "weekly essays"}],
                                "bluesky": [{"handle": "@a.bsky.social", "channel": "quick takes"}],
                                "sites": ["https://a.example"]})
        self.assertEqual(c["feeds"], ["https://a.substack.com/feed"])
        self.assertEqual(c["bluesky"], ["@a.bsky.social"])
        gs = suggest.candidate_groups(c)
        by_kind = {g.kind: g for g in gs}
        self.assertEqual(suggest.channel_of(c, by_kind["feed"], "https://a.substack.com/feed"), "weekly essays")
        self.assertEqual(suggest.channel_of(c, by_kind["bluesky"], "https://bsky.app/profile/a.bsky.social/rss"),
                         "quick takes")
        self.assertEqual(suggest.channel_of(c, by_kind["site"], "https://a.example/rss"), "a.example")

    def test_stale_channels_not_selected_by_default(self):
        import datetime as dt
        self.assertTrue(suggest.is_stale({"latest": "2025-09-16"}, 120, today=dt.date(2026, 10, 7)))
        self.assertFalse(suggest.is_stale({"latest": "2026-10-05"}, 120, today=dt.date(2026, 10, 7)))
        self.assertFalse(suggest.is_stale({"latest": ""}, 120))
        s = {"verified": [{"url": "https://old/feed", "latest": "2020-01-01"}, {"url": "https://new/feed", "latest": ""}]}
        self.assertEqual(suggest.default_selection(s, CFG), ["https://new/feed"])

    def test_accept_only_chosen_channels(self):
        [row] = self.queue([{"name": "Two Places", "why": "w",
                             "feeds": ["https://blog.example/feed", "https://bsky.app/profile/tp.bsky.social/rss"]}])
        with mock.patch.object(suggest, "verify_candidate", fake_verify):
            s = suggest.accept(self.root, CFG, row["id"], log=lambda *a: None, urls=["https://blog.example/feed"])
        self.assertEqual(s["wired"], ["https://blog.example/feed"])
        self.assertEqual(s["not_wired"], ["https://bsky.app/profile/tp.bsky.social/rss"])
        self.assertNotIn("bluesky", suggest.load_managed(self.root)["people"]["Two Places"])


if __name__ == "__main__":
    unittest.main()
