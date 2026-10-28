"""Takes edited in the Docs count as Steven's takes (Steven, 2026-10-28: written at home, augmented in the car with
Claude editing the shared Doc). Only edits after the pipeline's own last write; the deep-dive take re-records it."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import drivedocs, mailer, takes

DAY = "2026-10-28"
CFG = {"paths": {"briefings": "briefings"}, "email": {"script_url": "https://script.google.com/x", "test_to": "o@x.com"}}
DOC = """AI Briefing · Wednesday, October 28, 2026
Today in 30 seconds
Stuff.
Must read
1. Anthropic S-1: cash, compute commitments and founder voting control
What happened: things.
Steven's takes
The day overall: Liability evolution is the big one.
Anthropic S-1: cash, compute commitments and founder voting control: Massive demand or bust. Augmented in the car.
Top of mind: Founders who keep control should keep the liability
"""
DD = """Deep dive: Merging the Labs
Why today
Because.
Steven's take
Regulatory strategies for world dominance seem timely.
Watch for a consortium instead.
Sources
Forbes: x
"""
SLOTS = [{"slot": "0", "key": "overall", "title": "The day overall"}, {"slot": "T", "key": "top", "title": "Top of mind"},
         {"slot": "1", "key": "k1", "title": "Anthropic S-1: cash, compute commitments and founder voting control"}]


class Parse(unittest.TestCase):
    def test_titles_with_colons_match_longest_first(self):
        got = drivedocs.parse_takes(DOC, SLOTS)
        self.assertEqual(got["1"], "Massive demand or bust. Augmented in the car.")
        self.assertEqual(got["0"], "Liability evolution is the big one.")
        self.assertEqual(got["T"], "Founders who keep control should keep the liability")

    def test_deep_dive_take_stops_at_sources(self):
        self.assertEqual(drivedocs.parse_dd_take(DD), "Regulatory strategies for world dominance seem timely. Watch for a consortium instead.")
        self.assertEqual(drivedocs.parse_dd_take("no take here\nSources\nx"), "")


class Fetch(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings" / "deepdives").mkdir(parents=True)
        (self.root / "data" / "stories").mkdir(parents=True)
        (self.root / "briefings" / f"{DAY}.md").write_text("# AI Briefing · Wednesday, October 28, 2026\n")
        (self.root / "data" / "stories" / f"{DAY}.jsonl").write_text(json.dumps({"stories": [
            {"section": "must", "n": 1, "lead_id": "k1", "headline": "Anthropic S-1: cash, compute commitments and founder voting control", "ids": ["k1"]}]}) + "\n")
        (self.root / "briefings" / "deepdives" / f"{DAY}.md").write_text("# Deep dive: Merging the Labs\n\nsummary\n\n## Sources\n\n- x\n")

    def fetch(self, modified, saved=None):
        if saved:
            for which, name in (("briefing", drivedocs.names(DAY, "# AI Briefing · Wednesday, October 28, 2026\n")[1]),
                                ("deepdive", drivedocs.deepdive_name(DAY, "Deep dive: Merging the Labs"))):
                d = drivedocs._stamp_load(self.root)
                d.setdefault(DAY, {})[which] = {"name": name, "saved": saved}
                (self.root / drivedocs.STAMP).parent.mkdir(parents=True, exist_ok=True)
                (self.root / drivedocs.STAMP).write_text(json.dumps(d))
        docs = {drivedocs.names(DAY, "# AI Briefing · Wednesday, October 28, 2026\n")[1]: DOC,
                drivedocs.deepdive_name(DAY, "Deep dive: Merging the Labs"): DD}
        with mock.patch.object(mailer, "call", side_effect=lambda cfg, a, **p:
                               {"ok": True, "found": p["name"] in docs, "modified": modified, "text": docs.get(p["name"], "")}):
            return drivedocs.fetch_takes(self.root, CFG, DAY, log=lambda *a: None)

    def test_edits_after_our_write_count(self):
        got = self.fetch("2026-10-28T12:33:00Z", saved="2026-10-28T11:09:00+00:00")
        self.assertEqual(got["rows"][0]["via"], "drive")
        self.assertEqual(got["rows"][0]["takes"]["1"], "Massive demand or bust. Augmented in the car.")
        self.assertTrue(got["deepdive"].startswith("Regulatory strategies"))

    def test_a_take_already_saved_is_not_an_edit(self):      # no loop: the Doc says what commentary already has
        import json as _j
        (self.root / "data" / "commentary").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "commentary" / f"{DAY}.json").write_text(_j.dumps({"notes": {
            "k1": {"title": "x", "text": "Massive demand or bust. Augmented in the car."},
            "overall": {"title": "The day overall", "text": "Liability evolution is the big one."},
            "top": {"title": "Top of mind", "text": "Founders who keep control should keep the liability"}}}))
        got = self.fetch("2026-10-28T12:33:00Z")                  # no stamp at all, as after a bare re-publish
        self.assertEqual(got["rows"], [])
        self.assertTrue(got["deepdive"])                          # the deep-dive take is still new

    def test_our_own_write_is_not_an_edit(self):
        got = self.fetch("2026-10-28T11:09:30Z", saved="2026-10-28T11:09:00+00:00")
        self.assertEqual(got, {"rows": [], "deepdive": None})

    def test_sync_cadence(self):
        now = dt.datetime(2026, 10, 28, 9, 0)
        self.assertTrue(drivedocs.sync_due(self.root, now))
        drivedocs.mark_sync(self.root, False, now)
        self.assertFalse(drivedocs.sync_due(self.root, now + dt.timedelta(minutes=5)))
        self.assertTrue(drivedocs.sync_due(self.root, now + dt.timedelta(minutes=21)))

    def test_fetch_all_includes_drive_rows_last(self):
        with mock.patch.object(takes, "fetch_replies", return_value=[{"received": "2026-10-28T07:00:00", "takes": {"1": "Massive demand or bust."}, "done": True, "skip": False}]), \
             mock.patch.object(takes, "fetch_site", return_value=[]), \
             mock.patch.object(drivedocs, "fetch_takes", return_value={"rows": [{"received": "2026-10-28T12:33:00Z", "takes": {"1": "Longer."}, "done": False, "skip": False, "via": "drive"}], "deepdive": None}):
            rows = takes.fetch_all(self.root, CFG, DAY, log=lambda *a: None)
        self.assertEqual([r["takes"].get("1") for r in rows], ["Massive demand or bust.", "Longer."])
