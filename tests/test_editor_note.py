import tempfile
import unittest
from pathlib import Path

from pipeline import deepdive, editor_note, watchlist


class EditorNote(unittest.TestCase):
    def test_note_contents(self):
        root = Path(tempfile.mkdtemp())
        a = deepdive.add_manual(root, "AI math proofs explained", day="2026-10-14")
        deepdive.add_suggestions(root, "2026-10-14", [{"topic": "Lab economics in the filings", "strength": 5,
                                                       "why_today": "IPO documents"}], [])
        watchlist.add_mentions(root, [{"company": "Corvane", "title": "Corvane opens Ottawa office", "url": "https://x.com/a",
                                       "source": "news", "found": "2999-01-01T00:00:00"}])
        m = editor_note.build(root, {}, "2026-10-14")
        self.assertIn("AI math proofs explained", m["subject"])
        for s in ("TOMORROW'S DEEP DIVE", "Lab economics in the filings (strength 5)", "Corvane: Corvane opens Ottawa office",
                  "127.0.0.1:8765/deep-dives"):
            self.assertIn(s, m["text"])
        self.assertIn("Only you receive this note", m["html"])
        self.assertEqual(a["status"], "queued")


if __name__ == "__main__":
    unittest.main()
