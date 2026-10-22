import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import audio, deepdive


class HostAndHandoff(unittest.TestCase):
    def test_host_introduces_themselves(self):
        op = audio.opener("AI Briefing · Tuesday, October 20, 2026", {"host_name": "Michael"})
        self.assertTrue(op.startswith("This is the AI Briefing for Tuesday, October 20. I'm Michael."))
        self.assertIn("written and read by AI", op)

    def test_handoff_promotes_the_deep_dive_and_where_to_find_it(self):
        t = audio.outro_for({"_handoff": "The third scaling law", "deepdive_host": "Bella"})
        self.assertIn("right after this, Bella takes you through today's deep dive, on The third scaling law", t)
        self.assertIn("web page", t)
        self.assertIn("every past episode", t)
        self.assertIn("past episodes", audio.OUTRO)
        self.assertIn("every past episode", deepdive.OUTRO)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class Combined(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "briefings" / "deepdives").mkdir(parents=True)
        for path, f in ((self.root / "briefings" / "2099-01-01.mp3", 440),
                        (self.root / "briefings" / "deepdives" / "2099-01-01.mp3", 660)):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={f}:duration=2",
                            "-ac", "1", "-b:a", "64k", str(path)], check=True)

    def _script(self, text):
        (self.root / "briefings" / "2099-01-01.script.md").write_text(text)

    def test_one_file_when_the_briefing_hands_off(self):
        self._script("... Bella takes you through today's deep dive, on X ...")
        with mock.patch("pipeline.episodes.rebuilt", lambda root, key: 1):
            out = deepdive.make_podcast(self.root, {}, "2099-01-01", log=lambda *a: None)
        self.assertTrue(out and out.is_file())
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True)
        self.assertGreater(float(r.stdout), 4.5)            # 2 s + 1.2 s pause + 2 s

    def test_no_handoff_keeps_them_separate(self):
        self._script("That's the briefing. Until tomorrow.")
        self.assertIsNone(deepdive.make_podcast(self.root, {}, "2099-01-01", log=lambda *a: None))


if __name__ == "__main__":
    unittest.main()
