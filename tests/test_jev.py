"""Jev in the shadow (Steven, 2026-10-30): asked after the local filter, logged beside it, changes nothing; a daily
token budget; off without a key, and in staging."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import jev

ITEMS = [{"id": "a1", "title": "OpenAI cuts prices 80%", "text": "OpenAI cut API prices again.", "person": "TechCrunch", "source_kind": "rss", "published": "2026-10-30"},
         {"id": "b2", "title": "Lunch", "text": "Great tacos today.", "person": "Someone", "source_kind": "bluesky", "published": "2026-10-30"},
         {"id": "c3", "title": "Robots", "text": "A robot startup raised money.", "person": "BetaKit", "source_kind": "rss", "published": "2026-10-30"},
         {"id": "d4", "title": "ruled", "text": "x", "person": "x", "source_kind": "rss"}]
DEC = {"a1": {"keep": True}, "b2": {"keep": True}, "c3": {"keep": False}, "d4": {"keep": False, "rule": True}}
ANSW = {"a1": 0.95, "b2": 0.05, "c3": 0.5}


class R:
    def __init__(self, p):
        self.status_code, self.p = 200, p

    def json(self):
        return {"answers": {"keep": {"type": "noul", "noul": self.p}, "nothing": {"type": "noul", "noul": 0.02}},
                "usage": {"input_tokens": 150, "output_tokens": 4}}


class Client:
    def __init__(self):
        self.states = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.states.append(json["state"])
        return R(ANSW[json["state"].split("\n")[1].split(" ")[0][:2].lower()] if False else
                 ANSW[next(k for k, it in {x["id"]: x for x in ITEMS}.items() if it["title"] in json["state"])])


class Shadow(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.cfg = {"jev": {"enabled": True}}

    def test_logs_both_and_changes_nothing(self):
        cl = Client()
        with mock.patch.object(jev, "key", return_value="k"):
            s = jev.shadow(self.root, self.cfg, "2026-10-30", ITEMS, DEC, log=lambda *a: None, client=cl)
        self.assertEqual(s["asked"], 3)                              # the rule-dropped item is never sent
        self.assertEqual(s["agree"], 1)                              # a1 agree; b2 disagree; c3 unsettled
        self.assertEqual(s["unsettled"], 1)
        self.assertEqual(s["would_drop_kept"], 1)
        self.assertEqual(DEC["b2"]["keep"], True)                    # untouched
        rows = [json.loads(x) for x in (self.root / jev.LOG).read_text().splitlines()]
        self.assertEqual([r["jev"] for r in rows], ["keep", "drop", "unsettled"])
        self.assertTrue(all("TechCrunch" in st or "Someone" in st or "BetaKit" in st for st in cl.states))
        rep = jev.report(self.root, 7)
        self.assertEqual(rep["agreement"], 0.5)
        self.assertEqual(rep["would_drop_kept"][0]["id"], "b2")

    def test_budget_and_off_switches(self):
        cl = Client()
        with mock.patch.object(jev, "key", return_value="k"):
            s = jev.shadow(self.root, {"jev": {"enabled": True, "daily_tokens": 200}}, "2026-10-30", ITEMS, DEC, log=lambda *a: None, client=cl)
        self.assertEqual(s["asked"], 2)                              # 150 + 150 > 200 after the second
        with mock.patch.object(jev, "key", return_value=""):
            self.assertEqual(jev.shadow(self.root, self.cfg, "2026-10-30", ITEMS, DEC, log=lambda *a: None, client=cl), {})
        self.assertEqual(jev.shadow(self.root, {"jev": {"enabled": False}}, "2026-10-30", ITEMS, DEC, log=lambda *a: None, client=cl), {})
        with mock.patch("pipeline.env.staging", return_value=True), mock.patch.object(jev, "key", return_value="k"):
            self.assertEqual(jev.shadow(self.root, self.cfg, "2026-10-30", ITEMS, DEC, log=lambda *a: None, client=cl), {})

    def test_state_is_what_a_person_would_read(self):
        st = jev.state_of(ITEMS[0], 1400)
        self.assertTrue(st.startswith("TechCrunch · rss · 2026-10-30\nOpenAI cuts prices 80%"))
