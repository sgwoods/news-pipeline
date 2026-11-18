"""The system status board (Steven, 2026-11-11): one tile per link in the chain, from what the Mac already records."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import health

CFG = {"schedule": {"times": ["05:00", "06:30"]}, "takes": {"enabled": True, "cutoff": "09:15"}}


def _w(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")


class Board(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.now = dt.datetime(2026, 11, 14, 9, 40)
        self.day = "2026-11-14"
        _w(self.root / "data" / "runs.jsonl", json.dumps({
            "run_id": "r1", "day": self.day, "started": "2026-11-14T05:00:10", "ended": "2026-11-14T05:40:00", "status": "ok",
            "stages": {"fetch": {"items_new": 120, "per_source": [{"person": "A", "status": "ok"}, {"person": "B", "status": "ok"},
                                                                  {"person": "C", "status": "error"}]}}}) + "\n")
        _w(self.root / "briefings" / f"{self.day}.md", "# Edition\n")
        _w(self.root / "briefings" / f"{self.day}.mp3", "x" * 10)
        _w(self.root / "data" / "state" / "shipped.json", json.dumps({self.day: {"at": "2026-11-14T09:20:00"}}))
        _w(self.root / "data" / "email-log.jsonl", json.dumps({"day": self.day, "ok": True, "sent": 9, "at": "2026-11-14T09:22:00"}) + "\n")
        _w(self.root / "data" / "state" / "slack-posts.jsonl", json.dumps({"day": self.day, "kind": "main", "at": "2026-11-14T09:23:00"}) + "\n")
        _w(self.root / "data" / "queue" / "status.json", json.dumps({"at": "2026-11-14T09:39:30", "pending": [], "last": [{"recipe": "x", "status": "ok"}]}))
        _w(self.root / "data" / "state" / "releases.jsonl", json.dumps({"version": "0.2.61-beta", "at": "2026-11-14T11:30:00"}) + "\n")
        _w(self.root / "data" / "state" / "morning.jsonl", json.dumps({"day": self.day, "at": "2026-11-14T08:03:00", "new_strong": 0, "rebuild": False}) + "\n")

    def test_a_good_morning_is_all_well(self):
        b = health.board(self.root, CFG, self.now)
        by = {t["name"]: t for t in b["tiles"]}
        self.assertEqual(b["problems"], 0, health.text(b))
        self.assertTrue(b["headline"].startswith("All well as of 09:40"), b["headline"])
        self.assertEqual(by["Edition"]["state"], "ok"); self.assertIn("emailed to 9", by["Edition"]["note"])
        self.assertEqual(by["Runner"]["state"], "ok"); self.assertEqual(by["Podcast"]["state"], "ok")
        _w(self.root / "data" / "queue" / "status.json", json.dumps({"at": "2026-11-14T09:15:00", "pending": [], "last": []}))   # 25 min idle: fine
        self.assertEqual({t["name"]: t for t in health.board(self.root, CFG, self.now)["tiles"]}["Runner"]["state"], "ok")
        self.assertEqual(by["Ingestion"]["note"], "120 new item(s), 1 source(s) failing")
        self.assertIn("v0.2.61-beta in production", by["Release gate"]["note"])

    def test_problems_are_named_with_a_button(self):
        _w(self.root / "data" / "queue" / "status.json", json.dumps({"at": "2026-11-14T08:10:00", "pending": []}))   # 90 min: stuck
        _w(self.root / "data" / "email-log.jsonl", "")
        _w(self.root / "data" / "state" / "shipped.json", "{}")
        _w(self.root / "data" / "takes" / f"{self.day}.json", json.dumps({"day": self.day, "released_at": "2026-11-14T09:15:00"}))
        b = health.board(self.root, CFG, self.now)
        by = {t["name"]: t for t in b["tiles"]}
        self.assertEqual(by["Runner"]["state"], "bad"); self.assertEqual(by["Runner"]["action"]["href"], "/control")
        self.assertEqual(by["Edition"]["state"], "bad"); self.assertEqual(by["Edition"]["action"]["recipe"], "send-held")
        self.assertTrue(b["headline"].startswith("2 problems: Edition, Runner"), b["headline"]); self.assertIn("1 to watch", b["headline"])
        self.assertIn("BAD  Edition", health.text(b))

    def test_before_the_run_nothing_is_a_problem(self):
        _w(self.root / "data" / "runs.jsonl", "")
        for f in ("briefings/2026-11-14.md", "briefings/2026-11-14.mp3"):
            (self.root / f).unlink()
        b = health.board(self.root, CFG, dt.datetime(2026, 11, 14, 4, 30))
        by = {t["name"]: t for t in b["tiles"]}
        self.assertEqual(by["Today's run"]["state"], "off"); self.assertEqual(by["Edition"]["state"], "off")
        self.assertEqual(b["problems"], 0)
        b = health.board(self.root, CFG, dt.datetime(2026, 11, 14, 7, 0))
        self.assertEqual({t["name"]: t for t in b["tiles"]}["Today's run"]["state"], "bad")
