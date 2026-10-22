import tempfile
import unittest
from pathlib import Path

from pipeline import deepdive as dd


class DailyQueue(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "data").mkdir()
        dd.save_queue(self.root, [
            {"id": "a", "topic": "Weak idea", "status": "suggested", "strength": 2, "source_day": "2026-10-18"},
            {"id": "b", "topic": "Better idea", "status": "suggested", "strength": 3, "source_day": "2026-10-18"},
        ])

    def test_up_next_is_never_empty_when_suggestions_exist(self):
        it = dd.ensure_next(self.root, log=lambda *a: None)
        self.assertEqual(it["topic"], "Better idea")
        self.assertEqual(dd.queued(self.root)[0]["id"], "b")

    def test_default_cap_is_daily(self):
        self.assertEqual(dd.dcfg({})["max_per_week"], 7)


if __name__ == "__main__":
    unittest.main()


class WeekCount(unittest.TestCase):
    def test_counts_days_not_records(self):
        import json
        root = Path(tempfile.mkdtemp())
        (root / "data").mkdir()
        rows = [{"day": "2026-10-19", "status": "published"}, {"day": "2026-10-19", "status": "published"},
                {"day": "2026-10-20", "status": "published"}]
        (root / dd.LOG).parent.mkdir(parents=True, exist_ok=True)
        (root / dd.LOG).write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.assertEqual(dd._week_count(root, "2026-10-21"), 2)
