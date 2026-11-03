"""Audio branding (2026-11-03): sounds are made locally, placed at the open, between stories and at the close."""
import shutil
import tempfile
import unittest
import wave
from pathlib import Path

from pipeline import sonic

ROOT = Path(__file__).resolve().parents[1]
try:
    import numpy  # noqa: F401
    HAS_NUMPY = True
except ImportError:                     # the Linux VM sees the Mac's numpy wheel; the Mac runs these
    HAS_NUMPY = False


@unittest.skipUnless(HAS_NUMPY, "needs numpy")
class Sonic(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_styles_make_three_sounds_at_24k_mono(self):
        for st in sonic.STYLES:
            s = sonic.sounds(self.root, st)
            for k in ("logo", "sting", "close"):
                with wave.open(str(s[k])) as w:
                    self.assertEqual((w.getframerate(), w.getnchannels()), (24000, 1))
                    self.assertTrue(0.4 < w.getnframes() / 24000 < 3.5, (st, k))

    def test_same_style_same_sound(self):
        import numpy as np
        a, b = sonic.design("A")["logo"], sonic.design("A")["logo"]
        self.assertTrue(np.array_equal(a, b))

    def test_choice_off_by_default_and_saved(self):
        self.assertEqual(sonic.chosen(self.root), "")
        self.assertIsNone(sonic.for_audio(self.root))
        sonic.choose(self.root, "B")
        self.assertEqual(sonic.chosen(self.root), "B")
        self.assertEqual(set(sonic.for_audio(self.root)), {"logo", "sting", "close"})
        sonic.choose(self.root, "off")
        self.assertEqual(sonic.chosen(self.root), "")
        with self.assertRaises(ValueError):
            sonic.choose(self.root, "Z")

    def test_placement(self):
        parts = [("Cold open", "x"), ("Opener", "x"), ("Intro", "x"), ("Story 1", "x"), ("Story 2", "x"),
                 ("Quick hits", "x"), ("Outro", "x")]
        self.assertEqual(sonic.placement(parts), ["logo", None, None, "sting", "sting", "sting", None])

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_render_with_brand(self):
        from pipeline import audio
        import numpy as np

        class Eng:
            rate = 24000

            def synth(self, text, out):
                audio._write_wav(out, 0.2 * np.sin(np.arange(24000) / 10.0), 24000)
        out = self.root / "ep.mp3"
        brand = sonic.for_audio(self.root) or {k: str(v) for k, v in sonic.sounds(self.root, "A").items()}
        plain = audio.render_mp3(Eng(), [("Opener", "a"), ("Story 1", "b")], self.root / "plain.mp3")
        branded = audio.render_mp3(Eng(), [("Opener", "a"), ("Story 1", "b")], out, brand=brand)
        self.assertTrue(out.exists())
        self.assertGreater(branded, plain + 0.05)          # logo + sting + close add a few seconds


@unittest.skipUnless((ROOT / "config.yaml").exists(), "needs a checkout with config.yaml")
class Page(unittest.TestCase):
    def test_page_lists_styles(self):
        from dashboard.app import create_app
        h = create_app(ROOT).test_client().get("/audio-brand", headers={"Host": "127.0.0.1:8775"}).data.decode()
        for st in sonic.STYLES:
            self.assertIn(f"Style {st}", h)


if __name__ == "__main__":
    unittest.main()
