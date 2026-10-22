import tempfile
import unittest
from pathlib import Path

from pipeline.archive import Archive, read_jsonl


class TestArchive(unittest.TestCase):
    def test_add_items_is_append_only_and_dedupes(self):
        root = Path(tempfile.mkdtemp())
        a = Archive(root, {})
        it = {"id": "abc", "url": "https://x/1", "title": "One", "person": "P", "text": "t"}
        self.assertEqual(a.add_items([it, dict(it)], "2026-10-05"), 1)
        self.assertEqual(a.add_items([it], "2026-10-06"), 0)          # seen on an earlier day
        self.assertEqual(len(read_jsonl(a.index_path)), 1)
        self.assertEqual(read_jsonl(a.raw_file("2026-10-05"))[0]["url"], "https://x/1")
        self.assertFalse(a.raw_file("2026-10-06").exists())
        idx = read_jsonl(a.index_path)[0]
        self.assertEqual(idx["first_seen"], "2026-10-05")
        self.assertEqual(idx["raw"], "data/raw/2026-10-05/items.jsonl")

    def test_state_roundtrip(self):
        a = Archive(Path(tempfile.mkdtemp()), {})
        self.assertIsNone(a.load_state("pages-Corvane-https://corvane.com"))
        a.save_state("pages-Corvane-https://corvane.com", {"seen": ["u"]})
        self.assertEqual(a.load_state("pages-Corvane-https://corvane.com"), {"seen": ["u"]})


if __name__ == "__main__":
    unittest.main()
