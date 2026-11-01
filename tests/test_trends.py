import json
import tempfile
import unittest
from pathlib import Path

from pipeline import critic, trends


def _week(root, date, ours, peer):
    critic.save(root, {"date": date, "shows": [{"name": "Peer", "scores": {k: peer for k, _, _ in critic.DIMS}}],
                       "ours": {"scores": {k: ours for k, _, _ in critic.DIMS}}})


class TrendsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        _week(self.root, "2026-10-24", 6, 7)
        _week(self.root, "2026-10-31", 7, 7)

    def test_field_series(self):
        f = trends.field(self.root)
        self.assertEqual(f[critic.OURS], [("2026-10-24", 60.0), ("2026-10-31", 70.0)])
        self.assertEqual(f["Peer"][-1], ("2026-10-31", 70.0))
        self.assertEqual(trends.field(self.root, "accuracy")[critic.OURS][-1], ("2026-10-31", 7.0))

    def test_svg(self):
        svg = trends.svg_lines(trends.field(self.root), "Overall")
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertIn(critic.OURS, svg)
        self.assertIn("no data yet", trends.svg_lines({}, "Empty"))

    def test_flat_series_and_email_table(self):
        self.assertIn("<svg", trends.svg_lines({critic.OURS: [("2026-10-30", 100), ("2026-10-31", 100)]}, "Flat", "%"))
        html = critic.chart_field(critic.history(self.root))
        self.assertIn("Peer", html)
        self.assertIn("70.0", html)


if __name__ == "__main__":
    unittest.main()
