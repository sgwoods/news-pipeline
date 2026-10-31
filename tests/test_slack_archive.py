"""Steven 2026-10-31: the posts made before #cto-ai-newsletter existed become one "Earlier editions" message."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import slackpost

CFG = {"paths": {"briefings": "briefings"}, "publish": {"site_url": "https://example.github.io/ai-briefing/"},
       "slack": {"post": {"enabled": True, "channel": "cto-ai-newsletter"}}}


class Archive(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings").mkdir()
        (self.root / "briefings" / "2026-10-28.md").write_text(
            "# x\n\n## Today in 30 seconds\n- **Lead one.** Text.\n\n## Must read\n", "utf-8")

    def test_one_line_per_day_with_links_and_no_missing_days(self):
        with mock.patch.object(slackpost, "_dd", return_value=("A dive", "", "", "https://example.github.io/ai-briefing/2026-10-28/deep-dive/")):
            t = slackpost.build_archive(self.root, CFG, ["2026-10-28", "2026-10-29"])
        self.assertIn("*Wed Oct 28* — Lead one.", t)
        self.assertIn("<https://example.github.io/ai-briefing/2026-10-28/|Read>", t)
        self.assertIn("Deep dive: A dive", t)
        self.assertNotIn("Oct 29", t)

    def test_posted_once(self):
        sent = []
        with mock.patch.object(slackpost, "token", return_value="t"), \
                mock.patch.object(slackpost, "channel_id", return_value="C1"), \
                mock.patch.object(slackpost, "_send", side_effect=lambda *a, **k: sent.append(a) or "1.0"), \
                mock.patch("pipeline.release.require"), mock.patch.object(slackpost, "_dd", return_value=("", "", "", "")):
            self.assertTrue(slackpost.post_archive(self.root, CFG, ["2026-10-28"], log=lambda *a: None, client=object())["ok"])
            self.assertFalse(slackpost.post_archive(self.root, CFG, ["2026-10-28"], log=lambda *a: None, client=object())["ok"])
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()


class KnownChannel(unittest.TestCase):
    def test_a_configured_id_skips_the_lookup(self):
        self.assertEqual(slackpost.channel_id(object(), "t", "cto-ai-newsletter", "C0CDBLD1JT1"), "C0CDBLD1JT1")
