"""Special editions in the deep-dive podcast feed (Steven, 2026-11-04 evening)."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline import special


class Feed(unittest.TestCase):
    def test_released_specials_are_feed_episodes(self):
        root = Path(tempfile.mkdtemp())
        (root / special.DIR).mkdir(parents=True)
        (root / "data").mkdir()
        (root / special.DIR / "2026-11-04.md").write_text("# Deep dive: T\n\n*AI Briefing · special edition*\n\nThe summary.\n\n## Sources\n")
        (root / special.DIR / "2026-11-04.mp3").write_bytes(b"ID3")
        (root / special.DIR / "2026-11-05.md").write_text("# x\n")
        with open(root / special.LOG, "w") as f:
            f.write(json.dumps({"day": "2026-11-04", "status": "published", "title": "T"}) + "\n")
            f.write(json.dumps({"day": "2026-11-05", "status": "written", "title": "Draft"}) + "\n")
        eps = special.feed_episodes(root, "https://example.org/b/")
        self.assertEqual([e["day"] for e in eps], ["2026-11-04"])      # a draft is not an episode
        e = eps[0]
        self.assertEqual((e["title"], e["file"], e["guid"], e["link"]),
                         ("Special edition: T", "special-2026-11-04.mp3", "ai-briefing-dd-special-2026-11-04",
                          "https://example.org/b/2026-11-04/special/"))
        self.assertEqual(e["summary"], "The summary.")


if __name__ == "__main__":
    unittest.main()
