"""The advance deep dive (Steven, 2026-10-29): drafted at 15:30 for the commute home, into Drive with "Steven's take"
and "Notes for the editor" sections; the morning run reads them back, revises from the notes, keeps the take."""
import datetime as dt
import json
import unittest
from unittest import mock

from pipeline import deepdive, drivedocs, mailer, ntfy, schedule, service

from tests.test_deepdive import DeepDive, Fake, WRITE


class Advance(unittest.TestCase):
    setUp, tearDown = DeepDive.setUp, DeepDive.tearDown

    def test_schedule_and_service_know_advance(self):
        self.assertEqual(schedule.times({"schedule": {"advance": "15:30"}}, "advance"), ["15:30"])
        self.assertEqual(schedule.times({}, "advance"), ["15:30"])
        self.assertIn("advance", service.LABELS)

    def _draft(self):
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.cfg["email"] = {"test_to": "o@x.com", "script_url": "https://script.google.com/x"}
        deepdive.add_manual(self.root, "How AI proofs get checked")       # queued by Steven
        saved = {}
        with mock.patch.object(deepdive, "_backend", return_value=Fake(WRITE)), \
             mock.patch.object(deepdive, "suggest", return_value={"best": None}), \
             mock.patch.object(mailer, "call", side_effect=lambda cfg, a, **p: saved.setdefault(a, []).append(p) or {"ok": True, "url": "https://docs/x"}), \
             mock.patch.object(ntfy, "notify", return_value=True):
            out = deepdive.draft_tomorrow(self.root, self.cfg, log=lambda *a: None)
        return tomorrow, out, saved

    def test_draft_writes_tomorrow_and_saves_the_doc(self):
        tomorrow, out, saved = self._draft()
        self.assertEqual(out["status"], "drafted")
        self.assertEqual(out["day"], tomorrow)
        rec = deepdive.latest(self.root, tomorrow)
        self.assertEqual((rec["status"], rec.get("draft")), ("written", True))
        self.assertTrue((self.root / deepdive.DIR / f"{tomorrow}.parts.json").exists())
        self.assertFalse((self.root / deepdive.DIR / f"{tomorrow}.mp3").exists())          # not voiced yet
        doc = saved["savedoc"][0]
        self.assertTrue(doc["name"].endswith("(draft)"))
        self.assertIn("## Notes for the editor", doc["text"])
        self.assertIn("## Steven's take", doc["text"])
        self.assertEqual(len(saved["send"]), 1)                                               # the email with the link
        self.assertIn("deep dive", saved["send"][0]["subject"].lower())

    def test_morning_take_goes_in_without_notes(self):
        tomorrow, _, _ = self._draft()
        with mock.patch.object(drivedocs, "fetch_deepdive_draft", return_value={"take": "Trust is not a security position.", "notes": ""}):
            fb = deepdive.apply_draft_feedback(self.root, self.cfg, tomorrow, log=lambda *a: None)
        self.assertEqual(fb, {"take": True, "revised": False})
        parts = json.loads((self.root / deepdive.DIR / f"{tomorrow}.parts.json").read_text())["parts"]
        self.assertIn("steven_take", [n for n, _ in parts])
        self.assertEqual(deepdive.latest(self.root, tomorrow)["status"], "written")            # voice() will record it

    def test_morning_notes_revise_the_draft(self):
        tomorrow, _, _ = self._draft()
        revised = {**WRITE, "title": "How AI proofs get checked, revised"}
        fake = Fake(revised)
        with mock.patch.object(drivedocs, "fetch_deepdive_draft", return_value={"take": "My take.", "notes": "Lead with the referees. Cut the cost line. done"}), \
             mock.patch.object(deepdive, "_backend", return_value=fake):
            fb = deepdive.apply_draft_feedback(self.root, self.cfg, tomorrow, log=lambda *a: None)
        self.assertEqual(fb, {"take": True, "revised": True})
        self.assertIn("EDITOR'S NOTES FROM STEVEN", fake.prompts[-1])
        self.assertIn("Lead with the referees", fake.prompts[-1])
        rec = deepdive.latest(self.root, tomorrow)
        self.assertEqual(rec["title"], "How AI proofs get checked, revised")
        self.assertTrue(rec.get("revised_from_notes"))
        self.assertTrue(rec.get("take"))

    def test_notes_parse_strips_done(self):
        text = "x\nSteven's take\nMy words.\nNotes for the editor\nShorter please.\ndone\nSources\nx"
        self.assertEqual(drivedocs.parse_notes(text), "Shorter please.")
        self.assertEqual(drivedocs.parse_dd_take(text), "My words.")
