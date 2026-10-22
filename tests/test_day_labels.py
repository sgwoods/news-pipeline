import json
import tempfile
import unittest
from pathlib import Path

from pipeline import mailsource as ms


class Box:
    def __init__(self):
        self.stored, self.selected = [], None

    def select(self, folder, readonly=True):
        self.selected = (folder, readonly)
        return "OK", [b"3"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            q = args[-1]
            return "OK", [b"7" if "a@x" in q else b"8" if "b@x" in q else b""]
        self.stored.append(args)
        return "OK", [b""]

    def logout(self):
        pass


class DayLabels(unittest.TestCase):
    def test_labels_assessed_and_cited(self):
        root = Path(tempfile.mkdtemp())
        (root / "data/raw/2026-10-14").mkdir(parents=True)
        items = [{"id": "i1", "source_kind": "email", "message_id": "<a@x>"},
                 {"id": "i2", "source_kind": "email", "message_id": "<b@x>"},
                 {"id": "i3", "source_kind": "email", "message_id": "<gone@x>"},
                 {"id": "i4", "source_kind": "rss"}]
        (root / "data/raw/2026-10-14/items.jsonl").write_text("\n".join(json.dumps(i) for i in items))
        (root / "data/briefings.jsonl").write_text(json.dumps({"day": "2026-10-14", "item_ids": ["i2"], "considered_ids": ["i1", "i2"]}))
        box = Box()
        from pipeline import release
        orig_req, release.require = release.require, lambda *a, **k: None   # the gate itself is tested in test_release
        orig = ms.connect
        from pipeline.mailguard import GuardedIMAP
        guarded = GuardedIMAP(box, {}, "test", root)
        ms.connect = lambda cfg, purpose="": guarded
        try:
            r = ms.label_day(root, {}, "2026-10-14", log=lambda *a: None)
        finally:
            ms.connect = orig
            release.require = orig_req
        self.assertEqual((r["assessed"], r["labelled"], r["cited"], r["missing"]), (3, 2, 1, 1))
        self.assertFalse(box.selected[1])
        self.assertEqual(box.selected[0], '"AI-Briefing/Sources"')
        stored = {a[0]: a[2] for a in box.stored}
        self.assertEqual(stored[b"7"], '("AI-Briefing/Briefing/2026-10-14")')
        self.assertEqual(stored[b"8"], '("AI-Briefing/Briefing/2026-10-14" "AI-Briefing/Cited")')


if __name__ == "__main__":
    unittest.main()
