"""Claude picks the stories (pipeline/selection.py, selection review 2026-11-13): candidates with flags, the picks
through the code guards, the beat slot, the mechanical fallback, and the record for the Selection page."""
import unittest

from pipeline import selection, editorial

CFG = {"analysis": {"max_must_read": 3, "max_worth_knowing": 3, "max_in_brief": 4, "max_money": 2,
                    "max_stories_per_source": 2, "max_items_per_source": 3, "filter_keep_flags": ["PORTFOLIO"],
                    "filter_keep_sources": ["Artificial Lawyer"]},
       "editorial": {"audience": "an early-stage AI investor"}}


def st(key, title, imp=3, ids=("1",), person="TechCrunch AI", kind="feed", url="https://t.example/a", flags=(),
       grounded=True, wire=False, linked=None, tag="FULL READ", so_what="so"):
    lead = {"id": ids[0], "title": title, "importance": imp, "person": person, "source_kind": kind, "url": url,
            "flags": list(flags), "tag": tag, "so_what": so_what, "claim": title}
    if linked:
        lead["linked_url"] = linked
    return {"key": key, "headline": title, "ids": list(ids), "names": [person], "score": 3.0 + imp / 10, "lead": lead,
            "records": [lead] + [{"id": i, "url": url, "person": person} for i in ids[1:]],
            "evidence": {"primary": 1 if grounded else 0, "reports": 0, "tested": 0, "commentary": 0 if grounded else 1,
                         "grounded": grounded, "stances": {}}, "wire_only": wire}


STORIES = [
    st("k1", "Anthropic IPO prices at the top of the range", 4, ids=("1", "2", "3")),
    st("k2", "The Information: OpenAI weighs a new round", 4, person="Techmeme", kind="bluesky", url="https://bsky.app/p/1"),  # post-only
    st("k3", "Copilot for Legal Won't Cannibalize Us – Litera", 3, person="Artificial Lawyer"),                # beat
    st("k4", "Gemini 4 Hydrogen released", 4, ids=("4", "5")),
    st("k5", "Oura acquires Counsel Health for $625M", 3, person="TechCrunch AI"),
    st("k6", "A commentary on agents", 3, person="Ed Zitron", kind="bluesky", url="https://bsky.app/p/2", grounded=False),
    st("k7", "Minor model update", 2, person="The Neuron"),
]


class Fake:
    label = "claude"
    def __init__(self, out=None, raise_=None):
        self.out, self.raise_, self.user = out, raise_, ""
    def complete_json(self, system, user, max_tokens=0, **k):
        self.user = user
        if self.raise_:
            raise self.raise_
        return self.out


class _Log:
    def __init__(self): self.lines = []
    def info(self, m, *a): self.lines.append(m % a if a else m)
    def warning(self, m, *a): self.lines.append("W " + (m % a if a else m))


class Candidates(unittest.TestCase):
    def test_flags_and_blocks(self):
        f = selection.flags_for(STORIES[1], CFG["analysis"])
        self.assertIn("single-source", f); self.assertIn("post-only lead", f)
        self.assertIn("beat source", selection.flags_for(STORIES[2], CFG["analysis"]))
        self.assertIn("not grounded (commentary only)", selection.flags_for(STORIES[5], CFG["analysis"]))
        b = selection.candidate_block(2, STORIES[1], CFG["analysis"])
        self.assertIn("[2] The Information", b); self.assertIn("flags: single-source; post-only lead", b)

    def test_beat_story_below_the_cut_is_still_a_candidate(self):
        many = [st(f"x{i}", f"Story {i}", 4) for i in range(30)] + [STORIES[2]]
        c = selection.candidates(many, CFG["analysis"], n=25)
        self.assertEqual(len(c), 26)
        self.assertIs(c[-1], STORIES[2])


class Picks(unittest.TestCase):
    def test_picks_go_through_the_guards(self):
        out = {"must": [{"n": 2, "why": "OpenAI round"}, {"n": 1, "why": "IPO priced"}, {"n": 6, "why": "sharp"}],
               "worth": [{"n": 4, "why": "release"}], "money": [{"n": 5, "why": "health AI M&A"}],
               "left_out": [{"n": 7, "why": "minor"}], "lead_note": "IPO leads: priced, three sources."}
        llm, log = Fake(out), _Log()
        sel, rec, errs = selection.run_select(llm, STORIES, "sys", CFG, log, earlier=[{"day": "2026-11-13", "headline": "IPO roadshow", "key": "e", "thread": "e"}])
        self.assertEqual(errs, [])
        self.assertEqual([s["key"] for s in sel["must"]], ["k1", "k4", "k3"])       # post-only and ungrounded held back; capability slot k4; beat slot k3
        self.assertEqual([s["key"] for s in sel["worth"]], ["k2", "k6"])
        self.assertIn("held at Worth knowing: post-only lead", sel["worth"][0]["pick_reason"])
        self.assertIn("not grounded", sel["worth"][1]["pick_reason"])
        self.assertEqual([s["key"] for s in sel["money"]], ["k5"])
        self.assertTrue(sel["must"][2].get("beat_slot"))
        self.assertEqual(rec["lead_note"], "IPO leads: priced, three sources.")
        self.assertEqual(rec["left_out"][0]["headline"], "Minor model update")
        fates = {c["headline"]: c["fate"] for c in rec["candidates"]}
        self.assertEqual(fates["Anthropic IPO prices at the top of the range"], "must")
        self.assertEqual(fates["Minor model update"], "brief")
        self.assertIn("YESTERDAY AND BEFORE", llm.user); self.assertIn("IPO roadshow", llm.user)
        self.assertIn("up to 3 stories for Must read", llm.user)

    def test_fallback_to_the_mechanical_selector(self):
        sel, rec, errs = selection.run_select(Fake(raise_=RuntimeError("down")), STORIES, "sys", CFG, _Log())
        self.assertTrue(rec.get("fallback"))
        self.assertEqual(sel.keys(), editorial.select(STORIES, CFG["analysis"]).keys())
        self.assertEqual(len(errs), 1)
        sel2, rec2, _ = selection.run_select(Fake({"must": []}), STORIES, "sys", CFG, _Log())
        self.assertTrue(rec2.get("fallback"))

    def test_source_caps_hold(self):
        many = [st(f"n{i}", f"Neuron item {i}", 4, ids=(f"n{i}",), person="The Neuron") for i in range(4)]
        out = {"must": [{"n": i + 1, "why": "x"} for i in range(4)], "worth": [], "money": [], "left_out": []}
        sel, _, _ = selection.run_select(Fake(out), many, "sys", CFG, _Log())
        self.assertEqual(len(sel["must"]), 2)                                      # max_stories_per_source for single-source


if __name__ == "__main__":
    unittest.main()


class DayView(unittest.TestCase):
    def test_page_view_and_left_out_lines(self):
        import json, tempfile
        from pathlib import Path
        from pipeline import takes
        root = Path(tempfile.mkdtemp())
        (root / "data" / "stories").mkdir(parents=True); (root / "data" / "summaries").mkdir(parents=True)
        rec = {"day": "2026-11-13", "stories": [], "selection": {"model": "claude", "lead_note": "IPO leads.",
               "candidates": [{"n": 1, "headline": "A", "fate": "must", "why": "big", "flags": [], "sources": 3, "importance": 4}],
               "left_out": [{"n": 7, "headline": "Minor model update", "why": "no new fact"}]}}
        (root / "data" / "stories" / "2026-11-13.jsonl").write_text(json.dumps(rec) + "\n")
        rows = [{"id": "a1", "person": "Artificial Lawyer", "title": "Vetta bids for Weil lawyers", "url": "https://al/1",
                 "keep": True, "filter_reason": "kept without the model filter: a beat the briefing covers (filter_keep_sources)"},
                {"id": "a2", "person": "TechCrunch AI", "title": "Democrats launch Nvidia investigation", "url": "https://tc/2",
                 "keep": True, "filter_reason": "rescued by the second look: AI supplier policy"},
                {"id": "a3", "person": "Techmeme", "title": "Lyft Q3", "url": "https://bsky/3", "keep": False, "filter_reason": "not AI"},
                {"id": "a4", "person": "TechCrunch", "title": "dup", "url": "https://tc/4", "keep": False, "filter_reason": "announces an article already archived: duplicate"}]
        (root / "data" / "summaries" / "2026-11-13.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        v = selection.day_view(root, {"summaries": root / "data" / "summaries"}, "2026-11-13")
        self.assertEqual(v["sel"]["lead_note"], "IPO leads.")
        self.assertEqual([r["title"] for r in v["protected"]], ["Vetta bids for Weil lawyers"])
        self.assertEqual(v["protected"][0]["reason"], "a beat the briefing covers (filter_keep_sources)")
        self.assertEqual([r["title"] for r in v["rescued"]], ["Democrats launch Nvidia investigation"])
        self.assertEqual((v["model_drops"], v["rule_drops"]), (1, 1))
        self.assertTrue(v["dropped"][1]["rule"])
        self.assertEqual(takes.left_out_lines(root, "2026-11-13"), ["Minor model update · no new fact"])
        self.assertEqual(takes.left_out_lines(root, "2026-11-12"), [])
