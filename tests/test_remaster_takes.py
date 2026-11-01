import unittest
from pathlib import Path


class RemasterKeepsTakes(unittest.TestCase):
    def test_remaster_revoices_takes(self):         # 2026-11-01: re-records dropped Steven's takes from the audio
        src = (Path(__file__).resolve().parent.parent / "run.py").read_text("utf-8")
        body = src.split("def cmd_remaster", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("takes.revoice", body)
        self.assertLess(body.index("cmd_audio(cfg, day)"), body.index("takes.revoice"))


if __name__ == "__main__":
    unittest.main()
