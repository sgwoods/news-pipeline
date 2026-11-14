"""The 08:00 check during the hold (selection review 2026-11-13, R4): rebuild only when Claude says news broke."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import morning, schedule, takes


class Morning(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "data" / "stories").mkdir(parents=True)
        (self.root / "data" / "summaries").mkdir(parents=True)
        self.day = "2026-11-12"
        rec = {"day": self.day, "stories": [{"n": 1, "section": "must", "headline": "OpenAI ships GPT-6"},
                                            {"n": 2, "section": "must", "headline": "Maplewave raises"},
                                            {"n": 7, "section": "worth", "headline": "x"}]}
        (self.root / "data" / "stories" / f"{self.day}.jsonl").write_text(json.dumps(rec) + "\n")

    def test_new_items_are_the_strong_ones_created_since_the_check_started(self):
        since = dt.datetime(2026, 11, 12, 8, 0)
        rows = [{"id": "a", "keep": True, "importance": 5, "created": "2026-11-12T08:04:00-05:00", "headline": "Huang resigns"},
                {"id": "b", "keep": True, "importance": 5, "created": "2026-11-12T05:10:00-05:00", "headline": "old"},
                {"id": "c", "keep": True, "importance": 3, "created": "2026-11-12T08:05:00-05:00", "headline": "meh"},
                {"id": "d", "keep": False, "importance": 5, "created": "2026-11-12T08:05:00-05:00", "headline": "dropped"}]
        (self.root / "data" / "summaries" / f"{self.day}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        got = morning.new_items(self.root, {"summaries": self.root / "data" / "summaries"}, self.day, since, 4)
        self.assertEqual([r["headline"] for r in got], ["Huang resigns"])
        self.assertEqual(morning.current_must(self.root, self.day), [(1, "OpenAI ships GPT-6"), (2, "Maplewave raises")])

    def test_judge_parses_and_fails_closed(self):
        class LLM:
            def complete_json(self, system, user, max_tokens=None):
                assert "1. OpenAI ships GPT-6" in user and "Huang resigns" in user
                return {"rebuild": True, "headline": "Huang resigns", "why": "Nvidia CEO change"}
        v = morning.judge(LLM(), "sys", [(1, "OpenAI ships GPT-6")], [{"headline": "Huang resigns", "importance": 5}])
        self.assertTrue(v["rebuild"]); self.assertEqual(v["headline"], "Huang resigns")

        class Down:
            def complete_json(self, *a, **k):
                raise RuntimeError("no backend")
        self.assertFalse(morning.judge(Down(), "sys", [], [{"headline": "x"}])["rebuild"])

    def test_cutoff_extends_mid_hold(self):
        cfg = {"takes": {"enabled": True, "cutoff": "09:15", "poll_minutes": 0.01}}
        base = takes._cutoff(cfg, self.day, self.root)
        self.assertEqual(base.strftime("%H:%M"), "09:15")
        takes.extend_cutoff(self.root, self.day, 20, why="rebuilding for: Huang resigns")
        self.assertEqual(takes._cutoff(cfg, self.day, self.root).strftime("%H:%M"), "09:35")
        self.assertEqual(takes.state(self.root, self.day)["cutoff_extend_minutes"], 20)
        self.assertEqual(morning.mcfg({})["extend_minutes"], 20)

    def test_morning_is_a_scheduled_kind_on_the_tick(self):
        self.assertEqual(schedule.times({}, "morning"), ["08:00"])
        self.assertEqual(schedule.due({}, "morning", dt.datetime(2026, 11, 14, 8, 1)), "08:00")
        self.assertEqual(schedule.due({}, "morning", dt.datetime(2026, 11, 14, 8, 31)), "")
        self.assertEqual(schedule.check({"schedule": {"morning": ["08:10"]}}), ["08:10"])
