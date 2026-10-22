"""The email queue page: one-click picks in Steven's note, and his clicks applied to the queue at the next run."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import deepdive, editor_note


def seed(root):
    deepdive.save_queue(root, [
        {"id": "a1", "topic": "Third scaling law", "status": "queued", "order": 1},
        {"id": "b2", "topic": "Lab economics", "status": "queued", "order": 2},
        {"id": "c3", "topic": "AI math proofs", "status": "suggested", "strength": 5, "source_day": "2026-10-18"}])


class QueuePage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        seed(self.root)

    def test_clicks_are_applied_once_in_order(self):
        acts = [{"at": "2026-10-18T20:00:01Z", "op": "next", "id": "c3"},
                {"at": "2026-10-18T20:00:02Z", "op": "dismiss", "id": "b2"},
                {"at": "2026-10-18T20:00:03Z", "op": "add", "id": "", "topic": "Sovereign AI in Europe", "angle": ""}]
        with mock.patch("pipeline.mailer.call", lambda cfg, a, **k: {"ok": True, "actions": acts}):
            self.assertEqual(deepdive.apply_remote(self.root, {}, log=lambda *a: None), 3)
            self.assertEqual(deepdive.apply_remote(self.root, {}, log=lambda *a: None), 0)       # nothing twice
        self.assertEqual([x["topic"] for x in deepdive.queued(self.root)],
                         ["AI math proofs", "Third scaling law", "Sovereign AI in Europe"])

    def test_note_has_one_click_picks_and_the_page_link(self):
        with mock.patch("pipeline.watchlist.mentions", lambda root, days: []):
            m = editor_note.build(self.root, {}, "2026-10-18")
        self.assertIn("{{SCRIPT}}?action=queue&amp;t={{OWNER}}&amp;pick=b2", m["html"])
        self.assertIn("Make this next", m["html"])
        self.assertIn("Reorder or suggest topics", m["html"])

    def test_snapshot(self):
        snap = deepdive.snapshot(self.root)
        self.assertEqual([s["id"] for s in snap], ["a1", "b2", "c3"])
        self.assertTrue(json.dumps(snap))


if __name__ == "__main__":
    unittest.main()
