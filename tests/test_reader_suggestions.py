"""Readers suggest deep dives (Steven, 2026-10-28): a page from the email and the site, into the queue with the
name they gave (else "a reader"); addresses stay in data/, and the credit appears where the topic is shown."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import deepdive, mailer

ROWS = [{"at": "2026-10-28T13:00:00Z", "email": "r@x.com", "name": "Hugues", "topic": "Who actually pays for inference at scale", "why": "Margins.", "status": "new"},
        {"at": "2026-10-28T13:05:00Z", "email": "", "name": "", "topic": "Neoclouds and GPU-backed debt", "why": "", "status": "new"},
        {"at": "2026-10-28T13:06:00Z", "email": "r@x.com", "name": "x", "topic": "short", "why": "", "status": "new"}]


class ReaderSuggestions(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "data").mkdir()

    def test_pull_adds_once_with_credit(self):
        with mock.patch.object(mailer, "call", return_value={"ok": True, "suggestions": ROWS}):
            self.assertEqual(deepdive.pull_reader_suggestions(self.root, {}, log=lambda *a: None), 2)
            self.assertEqual(deepdive.pull_reader_suggestions(self.root, {}, log=lambda *a: None), 0)   # seen
        q = deepdive.load_queue(self.root)
        by = {x["topic"]: x for x in q}
        self.assertEqual(by["Who actually pays for inference at scale"]["suggested_by"], "Hugues")
        self.assertEqual(by["Who actually pays for inference at scale"]["origin"], "reader")
        self.assertEqual(by["Neoclouds and GPU-backed debt"]["suggested_by"], "a reader")
        self.assertNotIn("short", by)
        snap = deepdive.snapshot(self.root)
        self.assertEqual({s["by"] for s in snap}, {"Hugues", "a reader"})
        self.assertNotIn("r@x.com", json.dumps(snap))                   # the address never leaves data/

    def test_evening_note_names_the_reader(self):
        from pipeline import editor_note
        with mock.patch.object(mailer, "call", return_value={"ok": True, "suggestions": ROWS[:1]}):
            deepdive.pull_reader_suggestions(self.root, {}, log=lambda *a: None)
        (self.root / "briefings").mkdir()
        (self.root / "data" / "stories").mkdir()
        import datetime as dt
        msg = editor_note.build(self.root, {"paths": {"briefings": "briefings"}, "email": {}}, dt.date.today().isoformat(), [])
        self.assertIn("suggested by Hugues", msg["text"])
        self.assertNotIn("r@x.com", msg["text"] + msg["html"])

    def test_email_and_code_carry_the_suggest_link(self):
        self.assertIn("{{SUGGEST}}", mailer.TEMPLATE_PLACEHOLDERS)
        gs = (Path(__file__).resolve().parent.parent / "scripts" / "apps-script" / "Code.gs").read_text("utf-8")
        for needle in ("p.action === 'suggest'", "'{{SUGGEST}}'", "SGSHEET", "p.action === 'suggestions'"):
            self.assertIn(needle, gs)
