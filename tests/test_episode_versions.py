import tempfile
import unittest
from pathlib import Path

from pipeline import episodes


class Versions(unittest.TestCase):
    def test_rebuild_after_publish_is_a_new_episode(self):
        root = Path(tempfile.mkdtemp())
        self.assertEqual((episodes.audio_file(root, "2026-10-13"), episodes.guid(root, "2026-10-13")),
                         ("2026-10-13.mp3", "ai-briefing-2026-10-13"))
        self.assertEqual(episodes.rebuilt(root, "2026-10-13"), 1)      # not yet published: same episode
        episodes.mark_published(root, ["2026-10-13"])
        self.assertEqual(episodes.rebuilt(root, "2026-10-13"), 2)
        self.assertEqual(episodes.rebuilt(root, "2026-10-13"), 2)      # until v2 is published
        self.assertEqual((episodes.audio_file(root, "2026-10-13"), episodes.guid(root, "2026-10-13")),
                         ("2026-10-13-v2.mp3", "ai-briefing-2026-10-13-v2"))
        self.assertEqual(episodes.audio_file(root, "deepdive:2026-10-14"), "deepdive-2026-10-14.mp3")
        episodes.set_hidden(root, "2026-10-12", True)
        self.assertEqual(episodes.hidden_days(root), {"2026-10-12"})


if __name__ == "__main__":
    unittest.main()
