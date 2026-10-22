import logging
import unittest

from pipeline import editorial

LOG = logging.getLogger("t")


def rec(i, person="P", imp=4, **kw):
    return {"id": f"{i:016x}", "url": f"https://x.com/{i}", "person": person, "importance": imp,
            "headline": f"Headline {i}", "claim": f"claim {i}", "so_what": "sw", "agenda_flag": "No clear conflict",
            "published": f"2026-10-0{1 + i % 5}", **kw}


class Fake:
    def __init__(self, out):
        self.out = out

    def complete_json(self, system, user, retries=1, max_tokens=None):
        return self.out


class TestEditorial(unittest.TestCase):
    def test_cluster_validates_numbers(self):
        recs = [rec(i) for i in range(1, 6)]
        out = {"stories": [{"items": [1, 2, 2, 99], "headline": "Same story"}, {"items": [2, 3], "headline": "reuse"}]}
        stories, _, errs = editorial.run_cluster(Fake(out), recs, "sys", {}, LOG)
        multi = [s for s in stories if len(s["ids"]) > 1]
        self.assertEqual(len(multi), 1)                          # [2,3] rejected: 2 already used
        self.assertEqual(len(multi[0]["ids"]), 2)
        self.assertEqual(sum(len(s["ids"]) for s in stories), 5)  # nothing lost

    def test_editor_ranking_orders_stories(self):
        recs = [rec(1, imp=5), rec(2, imp=4), rec(3, imp=4)]
        out = {"stories": [], "top": [3, 1]}
        stories, _, _ = editorial.run_cluster(Fake(out), recs, "sys", {}, LOG)
        built = editorial.build_stories(stories, {r["id"]: r for r in recs})
        self.assertEqual([s["lead"]["id"] for s in built], [recs[2]["id"], recs[0]["id"], recs[1]["id"]])

    def test_cluster_failure_falls_back_to_singles(self):
        class Boom:
            def complete_json(self, *a, **k):
                raise RuntimeError("down")
        stories, _, errs = editorial.run_cluster(Boom(), [rec(1), rec(2)], "sys", {}, LOG)
        self.assertEqual(len(stories), 2)
        self.assertTrue(errs)

    def test_select_balances_sources_and_ranks_clusters(self):
        recs = [rec(i, person="Zitron", imp=5) for i in range(1, 6)] + [rec(10, "A", 3), rec(11, "B", 3), rec(12, "C", 3)]
        by_id = {r["id"]: r for r in recs}
        raw = [{"ids": [r["id"]], "headline": None} for r in recs[:5]]
        raw.append({"ids": [recs[5]["id"], recs[6]["id"], recs[7]["id"]], "headline": "Cluster"})
        stories = editorial.build_stories(raw, by_id)
        cluster = next(s for s in stories if s["headline"] == "Cluster")
        self.assertEqual(cluster["score"], 4.0)                   # importance 3 + 1 for a 3-source story
        sel = editorial.select(stories, {"max_stories_per_source": 2})
        zitron_top = [s for s in sel["must"] + sel["worth"] if s["names"] == ["Zitron"]]
        self.assertEqual(len(zitron_top), 2)

    def test_render_has_links_and_no_trivial_agenda(self):
        recs = [rec(1, imp=5), rec(2, imp=3)]
        by_id = {r["id"]: r for r in recs}
        stories = editorial.build_stories([{"ids": [r["id"]], "headline": None} for r in recs], by_id)
        sel = editorial.select(stories, {})
        ed = {"day_in_brief": "Brief.", "top_of_mind": [{"lead": "Lead", "text": "Text.", "refs": [1, 9]}]}
        md, order = editorial.render("2026-10-05", sel, ed, {"models": "m"})
        self.assertIn("# AI Briefing · Monday, October 5, 2026", md)
        self.assertIn("- **Lead.** Text. [1](https://x.com/1)", md)
        self.assertNotIn("[9]", md)
        self.assertNotIn("Agenda", md)
        for r in recs:
            self.assertIn(r["url"], md)


if __name__ == "__main__":
    unittest.main()
