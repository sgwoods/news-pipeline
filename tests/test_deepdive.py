import json
import tempfile
import unittest
from pathlib import Path

from pipeline import deepdive, dive, record

STORY = {"key": "k1", "section": "must", "headline": "OpenAI says model proved an open problem", "names": ["OpenAI"],
         "ids": ["i1"], "what_happened": "OpenAI says its model proved a conjecture.", "critical_pass": "Overstated. Self-reported.",
         "editor_view": "We would wait for referees."}


class Fake:
    label = "fake"

    def __init__(self, out):
        self.out, self.prompts = out, []

    def complete_json(self, system, user, max_tokens=None, retries=1):
        self.prompts.append(user)
        return self.out


WRITE = {"title": "How AI proofs get checked", "summary": "What was proved and how we know.",
         "sections": [{"id": "why_today", "text": "Today OpenAI said its model proved a conjecture."},
                      {"id": "plainly", "text": "A proof is a chain of steps anyone can check. It cost $5B to build, they say."},
                      {"id": "evidence", "text": "The lab calls it \"a genuine first\" in its post. Referees have not reported."},
                      {"id": "readings", "text": "The AGI-forward reading is that this compounds."},
                      {"id": "so_what", "text": "We would ask whether a proof checker was used."},
                      {"id": "watch", "text": "Watch for a formal verification."}],
         "sources": [{"n": 1, "url": "https://openai.com/index/proof", "title": "OpenAI post", "what": "the claim"},
                     {"n": 2, "url": "https://www.nature.com/x", "title": "Nature news", "what": "reaction"},
                     {"n": 3, "url": "https://dead.example/x", "title": "dead"}]}


class DeepDive(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for d in ("briefings", "data/stories", "data/raw/2026-10-14"):
            (self.root / d).mkdir(parents=True)
        (self.root / "perspective.md").write_text("# Perspective\n")
        (self.root / "briefings/2026-10-14.md").write_text("# AI Briefing\n\n**The day in brief.** Proofs.\n")
        (self.root / "data/stories/2026-10-14.jsonl").write_text(json.dumps({"stories": [STORY]}))
        (self.root / "data/raw/2026-10-14/items.jsonl").write_text(json.dumps(
            {"id": "i1", "person": "OpenAI (news)", "url": "https://openai.com/index/proof", "title": "Proof",
             "text": "Our model proved it. This is a genuine first."}))
        self.cfg = {"paths": {"briefings": "briefings", "perspective": "perspective.md"}, "deepdive": {"max_per_week": 2}}
        self._cl, self._pt = dive.check_links, record.page_text
        dive.check_links = lambda urls, cfg: {u: "dead" not in u for u in urls}
        record.page_text = lambda url, cfg, chars=8000: ""

    def tearDown(self):
        dive.check_links, record.page_text = self._cl, self._pt

    def test_no_go(self):
        r = deepdive.run(self.root, self.cfg, "2026-10-14", log=lambda *a: None,
                         llm_pick=Fake({"candidates": [{"topic": "Minor tweak", "strength": 2}], "best": -1}), llm_write=Fake({}), tts=False)
        self.assertEqual(r["status"], "skipped")
        self.assertEqual([x["status"] for x in deepdive.load_queue(self.root)], ["suggested"])   # kept for the UI

    def test_written_with_checks(self):
        pick = Fake({"candidates": [{"topic": "AI proofs", "kind": "breakthrough", "why_today": "OpenAI claim", "angle": "a",
                                     "story_numbers": [1], "strength": 5}], "best": 0})
        w = Fake(WRITE)
        r = deepdive.run(self.root, self.cfg, "2026-10-14", log=lambda *a: None, llm_pick=pick, llm_write=w, tts=False)
        self.assertEqual(r["status"], "written")
        self.assertIn("Our model proved it", w.prompts[0])               # archived source text is the material
        self.assertEqual(r["sources_dropped"], ["https://dead.example/x"])
        self.assertTrue(any("unsourced figure" in n for n in r["checks"]))  # the $5B sentence is cut
        script = (self.root / deepdive.DIR / "2026-10-14.script.md").read_text()
        self.assertNotIn("$5B", script)
        self.assertIn('"a genuine first"', script)                        # verbatim quote kept
        self.assertIn("This is the AI Briefing deep dive for Wednesday, October 14", script)
        self.assertEqual(deepdive.load_queue(self.root)[0]["status"], "done")
        notes = (self.root / deepdive.DIR / "2026-10-14.md").read_text()
        self.assertIn("https://www.nature.com/x", notes)
        self.assertNotIn("dead.example", notes)

    def test_queue_first_and_ordering(self):
        a = deepdive.add_manual(self.root, "Third scaling law explained", day="2026-10-13")
        b = deepdive.add_manual(self.root, "Lab economics after the IPO filings", day="2026-10-13")
        deepdive.move(self.root, b["id"], -1)
        self.assertEqual([x["topic"] for x in deepdive.queued(self.root)][0], "Lab economics after the IPO filings")
        it = deepdive.plan_today(self.root, self.cfg, "2026-10-14",
                                 llm=Fake({"candidates": [{"topic": "Something else", "strength": 5, "story_numbers": [1]}], "best": 0}),
                                 log=lambda *a: None)
        self.assertEqual(it["topic"], "Lab economics after the IPO filings")      # Steven's queue wins
        self.assertEqual(deepdive.scheduled_for(self.root, "2026-10-14")["id"], b["id"])
        deepdive.set_status(self.root, a["id"], "dismissed")
        self.assertEqual(deepdive.queued(self.root), [])
        sugg = [x for x in deepdive.load_queue(self.root) if x["status"] == "suggested"]
        self.assertEqual([x["topic"] for x in sugg], ["Something else"])
        self.assertEqual(sugg[0]["story_ids"], ["i1"])

    def test_handoff_and_opener(self):
        from pipeline import audio
        acfg = {"_handoff": "How AI proofs get checked", "deepdive_host": "Bella", "host_name": "Michael"}
        self.assertIn("Bella takes you through today's deep dive, on How AI proofs get checked", audio.outro_for(acfg))
        self.assertEqual(audio.outro_for({}), audio.OUTRO)
        op = deepdive.opener("2026-10-14", "Proofs", acfg)
        self.assertTrue(op.startswith("Thanks, Michael. This is the AI Briefing deep dive for Wednesday, October 14: Proofs. I'm Bella."))
        self.assertIn("written and read by AI", op)

    def test_weekly_cap(self):
        (self.root / deepdive.LOG).write_text("\n".join(json.dumps({"day": d, "status": "published"}) for d in ("2026-10-12", "2026-10-13")))
        r = deepdive.run(self.root, self.cfg, "2026-10-14", log=lambda *a: None, llm_pick=Fake({}), llm_write=Fake({}), tts=False)
        self.assertEqual(r["status"], "skipped")
        self.assertIn("weekly cap", r["reason"])


if __name__ == "__main__":
    unittest.main()


class FeedTest(unittest.TestCase):
    def test_bonus_episode_in_feed(self):
        import datetime as dt
        from pipeline import site
        root = Path(tempfile.mkdtemp())
        day = dt.date.today().isoformat()
        (root / "briefings" / "deepdives").mkdir(parents=True)
        (root / "briefings" / f"{day}.md").write_text(f"# AI Briefing · {day}\n\n**The day in brief.** x\n")
        (root / "briefings" / f"{day}.mp3").write_bytes(b"ID3")
        (root / deepdive.DIR / f"{day}.md").write_text("# Deep dive: Proofs\n\n*meta*\n\nWhat was proved.\n\n## Sources\n\n- [a](https://a.com)\n")
        (root / deepdive.DIR / f"{day}.mp3").write_bytes(b"ID3")
        (root / "data").mkdir()
        (root / deepdive.LOG).write_text(json.dumps({"day": day, "status": "published", "title": "Proofs"}))
        res = site.build(root, {"podcast": {}, "site": {}}, out=root / "site", base_url="https://x.github.io/b")
        xml = (root / "site" / "podcast.xml").read_text()
        self.assertIn("Deep dive: Proofs", xml)
        self.assertIn("<itunes:episodeType>bonus</itunes:episodeType>", xml)
        self.assertIn(f"ai-briefing-deepdive-{day}", xml)
        self.assertTrue((root / "site" / day / "deep-dive" / "index.html").exists())
        self.assertIn(f"deepdive:{day}", res["episode_keys"])


class Reorder(unittest.TestCase):
    def test_move_to(self):
        root = Path(tempfile.mkdtemp())
        a = deepdive.add_manual(root, "Alpha topic one")
        b = deepdive.add_manual(root, "Beta topic two")
        c = deepdive.add_suggestions(root, "2026-10-15", [{"topic": "Gamma topic three", "strength": 4}], [])[0]
        deepdive.move_to(root, c["id"], 1)                       # a suggestion goes straight to "air next"
        self.assertEqual([x["topic"] for x in deepdive.queued(root)], ["Gamma topic three", "Alpha topic one", "Beta topic two"])
        deepdive.move_to(root, a["id"], 99)
        self.assertEqual(deepdive.queued(root)[-1]["id"], a["id"])
        deepdive.move_to(root, a["id"], 2)
        self.assertEqual([x["id"] for x in deepdive.queued(root)], [c["id"], a["id"], b["id"]])
