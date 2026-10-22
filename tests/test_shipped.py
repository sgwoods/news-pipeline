"""Shipped editions don't break (pipeline/shipped.py): the publish guard, carried-over audio, corrections, and the
after-publish check."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
    os.environ.pop(_k, None)

from pipeline import shipped, site  # noqa: E402

DAY = "2026-10-21"
TODAY = dt.date(2026, 10, 22)


def page(path: Path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class Shipped(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        page(self.root / "briefings" / f"{DAY}.md", "# AI Briefing · x\n\nshipped text\n")
        self.live = self.root / ".publish"
        for f in (f"{DAY}/index.html", f"{DAY}/deep-dive/index.html", "index.html", "feed.xml",
                  f"audio/{DAY}.mp3", f"audio/{DAY}-full.mp3"):
            page(self.live / f)
        page(self.live / "podcast.xml", f"<item><link>https://x/{DAY}/</link></item><item><link>https://x/2026-10-20/</link></item>")
        shipped.record(self.root, DAY, live=self.live)
        self.site = self.root / "site"
        for f in (f"{DAY}/index.html", f"{DAY}/deep-dive/index.html", "index.html", "feed.xml",
                  f"audio/{DAY}-v2-full.mp3"):
            page(self.site / f)
        page(self.site / "podcast.xml", f"<item><link>https://x/{DAY}/</link></item><item><link>https://x/2026-10-20/</link></item>")

    def test_record_names_pages_and_audio(self):
        e = shipped.load(self.root)[DAY]
        self.assertEqual(e["pages"], [f"{DAY}/index.html", f"{DAY}/deep-dive/index.html"])
        self.assertEqual(e["audio"], [f"{DAY}-full.mp3", f"{DAY}.mp3"])

    def test_remaster_keeps_the_old_audio(self):
        self.assertTrue(any("audio missing" in p for p in shipped.guard(self.root, self.site, self.live, 30, TODAY)))
        carried = shipped.carry_audio(self.root, self.site, self.live, 30, TODAY)
        self.assertEqual(sorted(carried), [f"{DAY}-full.mp3", f"{DAY}.mp3"])
        self.assertEqual(shipped.guard(self.root, self.site, self.live, 30, TODAY), [])

    def test_guard_refuses_what_would_break_readers(self):
        shipped.carry_audio(self.root, self.site, self.live, 30, TODAY)
        (self.site / DAY / "deep-dive" / "index.html").unlink()
        page(self.site / "podcast.xml", "<item><link>https://x/2026-10-20/</link></item>")
        (self.root / "briefings" / f"{DAY}.md").write_text("# silently rewritten\n")
        bad = shipped.guard(self.root, self.site, self.live, 30, TODAY)
        self.assertTrue(any("page missing" in b for b in bad))
        self.assertTrue(any("changed without a correction" in b for b in bad))
        self.assertTrue(any(f"podcast feed would drop episode(s): {DAY}" in b for b in bad))

    def test_old_audio_outside_retention_may_go(self):
        self.assertEqual([p for p in shipped.guard(self.root, self.site, self.live, 1, dt.date(2026, 12, 1))
                          if "audio" in p], [])

    def test_a_correction_is_recorded_and_shown(self):
        before = shipped._sha(self.root / "briefings" / f"{DAY}.md")
        (self.root / "briefings" / f"{DAY}.md").write_text("# AI Briefing · x\n\nfixed text\n")
        shipped.correct(self.root, DAY, "Fixed the Legora valuation", before)
        shipped.carry_audio(self.root, self.site, self.live, 30, TODAY)
        self.assertEqual(shipped.guard(self.root, self.site, self.live, 30, TODAY), [])
        with self.assertRaises(ValueError):
            shipped.correct(self.root, DAY, "  ", before)
        out = self.root / "out"
        site.build(self.root, {}, out=out)
        self.assertIn("Corrected", (out / DAY / "index.html").read_text())
        self.assertIn("Fixed the Legora valuation", (out / DAY / "index.html").read_text())

    def test_verify_live(self):
        class R:
            def __init__(self, c):
                self.status_code = c

        class C:
            def __init__(self, bad):
                self.bad = bad

            def get(self, u):
                return R(404 if self.bad in u else 200)

            def head(self, u):
                return self.get(u)
        base = "https://x.example/b/"
        self.assertEqual(shipped.verify_live(self.root, base, client=C("nothing")), [])
        bad = shipped.verify_live(self.root, base, client=C("deep-dive"))
        self.assertEqual(len(bad), 1)
        self.assertIn("deep-dive", bad[0])
        urls = shipped.live_urls(self.root, base)
        self.assertIn(f"https://x.example/b/{DAY}/index.html", urls)
        self.assertTrue(any(u.endswith(".mp3") for u in urls))


if __name__ == "__main__":
    unittest.main()
