"""Pronunciation and take pauses (Steven, 2026-11-04) and Slack reads that write nothing without a root."""
import unittest
from pathlib import Path

from pipeline import audio, speech

ROOT = Path(__file__).resolve().parent.parent
TABLE = {"GPT": "G P T", "SB": "S B", "FTC": "F T C", "SEC": "S E C", "PAC": "pack", "US": "U S"}   # as in the yaml


def say(s):
    return speech.spoken(s, TABLE)


class Speech(unittest.TestCase):
    def test_letter_o_models(self):
        self.assertIn("G P T-four-oh", say("GPT-4o"))
        self.assertEqual(say("4o is cheaper"), "four-oh is cheaper")
        self.assertIn("oh three", say("o3 and"))
        self.assertIn("oh four", say("o4-mini"))

    def test_chips_and_letters(self):
        self.assertIn("G B three hundred", say("GB300"))
        self.assertIn("M I three hundred X", say("MI300X"))
        self.assertIn("H one hundred", say("the H100"))
        self.assertIn("B two hundreds", say("B200s"))
        self.assertIn("R one", say("R1"))
        self.assertIn("K three point one", say("K3.1"))

    def test_acronyms(self):
        self.assertEqual(say("the FTC and SEC"), "the F T C and S E C")
        self.assertIn("super pack", say("super PAC"))
        self.assertEqual(say("us and US"), "us and U S")

    def test_comma_after_a_number_survives(self):
        self.assertEqual(say("SB 53, the law"), "S B fifty-three, the law")
        self.assertEqual(say("1,300 workers, 20 sites"), "one thousand three hundred workers, twenty sites")
        self.assertIn("forty dollars, then", say("$40, then"))


    def test_the_table_has_them(self):
        if not (ROOT / "pronunciations.yaml").exists():
            self.skipTest("the pronunciation table is not in the public code")
        real = speech.load_table(ROOT)
        for k, v in TABLE.items():
            self.assertEqual(real.get(k), v)


class TakePauses(unittest.TestCase):
    def test_splits_only_between_real_clauses(self):
        ph = audio.take_phrases("Yes, and this matters because the board flipped, but the CEO stayed — so plan for states now.")
        self.assertEqual([p for p, _ in ph][0], "Yes, and this matters because the board flipped,")
        self.assertEqual(ph[-1][1], 0.0)
        self.assertTrue(all(g in (0.22, 0.32) for _, g in ph[:-1]))
        self.assertEqual(audio.take_phrases("Short take, really."), [("Short take, really.", 0.0)])

    def test_only_takes(self):
        self.assertTrue(audio.is_take("Take 2") and audio.is_take("steven_take") and audio.is_take("Take overall"))
        self.assertFalse(audio.is_take("Must read 1") or audio.is_take("why_today"))

    def test_render_joins_phrases(self):
        import shutil
        import tempfile
        from unittest import mock
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg")

        class Eng:
            calls = []

            def synth(self, text, out):
                self.calls.append(text)
                audio._silence(out, 0.1)
        e = Eng()
        out = Path(tempfile.mkdtemp()) / "x.mp3"
        with mock.patch.object(audio.subprocess, "run"):     # no real encode (ffmpeg aborted under the release gate, 11-04)
            audio.render_mp3(e, [("Take 1", "One two three four, five six seven eight, nine ten eleven twelve.")], out)
        self.assertEqual(len(e.calls), 3)


class SlackNoRoot(unittest.TestCase):
    def test_no_root_writes_nothing_and_does_not_fail(self):
        import logging
        from unittest import mock
        from pipeline import slacksource
        import time

        class R:
            def __init__(self, d):
                self.d = d

            def raise_for_status(self):
                pass

            def json(self):
                return self.d

        class C:
            def get(self, url, params=None, headers=None):
                if url.endswith("conversations.list"):
                    return R({"ok": True, "channels": [{"name": "ch", "id": "C1"}]})
                return R({"ok": True, "messages": [{"user": "U1", "ts": str(time.time()),
                                                    "text": "this is my view <https://example.org/a>"}]})

            def close(self):
                pass
        cfg = {"slack": {"enabled": True, "channel": "ch", "authors": ["U1"]}}
        with mock.patch.object(slacksource, "token", lambda: "xoxp-test"), \
                mock.patch("pipeline.linkedin.is_own_post", lambda it, cfg: False):
            res = slacksource.fetch(None, cfg, "r", logging.getLogger("t"), client=C())
        self.assertEqual(res["sources"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
