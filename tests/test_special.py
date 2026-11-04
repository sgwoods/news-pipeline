"""Special editions (pipeline/special.py) and the headless last try (pipeline/headless.py)."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("NP_TESTING", "1")
from pipeline import deepdive, headless, special  # noqa: E402


def _root():
    d = Path(tempfile.mkdtemp())
    (d / "data" / "audit").mkdir(parents=True)
    (d / special.DIR).mkdir(parents=True)
    return d


def _written(root, day, parts=None):
    parts = parts or [["Opener", "x"], ["why_today", "Dow rose 1,240 points. Nvidia fell 2%."], ["Outro", "y"]]
    (root / special.DIR / f"{day}.parts.json").write_text(json.dumps({"title": "T", "parts": parts}))
    (root / special.DIR / f"{day}.md").write_text("# Deep dive: T\n\n*AI Briefing · special edition*\n\nSummary line.\n\n"
                                                  "**Why today.** Because.\n\n## Sources\n\n- [a](https://a.example)\n")
    with open(root / special.LOG, "a") as f:
        f.write(json.dumps({"day": day, "status": "written", "title": "T", "pick": {"queue_id": "q1"}}) + "\n")
    (root / "data" / "audit" / f"{day}-special.json").write_text(json.dumps({"held": [
        {"claim": "Dow rose 1,240 points.", "verdict": "not found", "why": "no source", "proposed": "Dow rose 1,131 points."},
        {"claim": "Nvidia fell 2%.", "verdict": "not found", "why": "no source"},
        {"claim": "So what changes?", "verdict": "not found", "why": "a question"}]}))


class Edition(unittest.TestCase):
    def test_namespace_swaps_and_restores(self):
        before = (deepdive.DIR, deepdive.LOG, deepdive.EDITION)
        with special.edition() as dd:
            self.assertEqual((dd.DIR, dd.LOG, dd.EDITION), (special.DIR, special.LOG, "special"))
            self.assertIn("special edition", dd.opener("2026-11-04", "The sweep", {"deepdive_host": "Bella", "host_name": "Michael"}))
            self.assertNotIn("Thanks", dd.opener("2026-11-04", "The sweep", {"deepdive_host": "Bella", "host_name": "Michael"}))
            self.assertEqual(dd.outro(), deepdive.SPECIAL_OUTRO)
        self.assertEqual((deepdive.DIR, deepdive.LOG, deepdive.EDITION), before)
        self.assertEqual(deepdive.outro(), deepdive.OUTRO)

    def test_fact_items_recommend_and_apply(self):
        root, day = _root(), "2026-11-04"
        _written(root, day)
        its = special.fact_items(root, day)
        self.assertEqual([i["rec"] for i in its], ["B", "C", "A"])     # rewrite · cut · a question stays
        special.decide(root, day, "F2: A")
        special.apply_choices(root, day, log=lambda *a: None)
        txt = json.loads((root / special.DIR / f"{day}.parts.json").read_text())["parts"][1][1]
        self.assertEqual(txt, "Dow rose 1,131 points. Nvidia fell 2%.")
        with self.assertRaises(special.SpecialError):
            special.decide(root, day, "F9: B")

    def test_draft_refuses_twice_a_day_and_too_often(self):
        root, day = _root(), dt.date.today().isoformat()
        _written(root, day)
        with self.assertRaises(special.SpecialError):
            special.draft(root, {}, "q1")
        root2 = _root()
        with open(root2 / special.LOG, "w") as f:
            for k in range(1, special.MAX_PER_30_DAYS + 1):
                f.write(json.dumps({"day": (dt.date.today() - dt.timedelta(days=k)).isoformat(), "status": "published"}) + "\n")
        with self.assertRaises(special.SpecialError):
            special.draft(root2, {}, "q1")

    def test_email_once_and_only_when_live(self):
        root, day = _root(), "2026-11-04"
        _written(root, day)
        with open(root / special.LOG, "a") as f:
            f.write(json.dumps({"day": day, "status": "published", "title": "T", "minutes": 9}) + "\n")
        sent = []
        noon = dt.datetime(2026, 11, 4, 12, 0)
        with mock.patch("pipeline.mailer.call", lambda cfg, a, **k: sent.append(k) or {"ok": True, "sent": 3}), \
                mock.patch("pipeline.mailer.privacy_gate", lambda m, c: []), \
                mock.patch("pipeline.special.dt.datetime", wraps=dt.datetime) as fake:
            fake.now.return_value = noon
            with self.assertRaises(special.SpecialError):                        # page not live
                special.email(root, {}, day, fetch=lambda u: (404, ""), log=lambda *a: None)
            r = special.email(root, {}, day, fetch=lambda u: (200, f"special-{day}.mp3"), log=lambda *a: None)
            self.assertTrue(r["ok"])
            self.assertTrue(sent[0]["subject"].startswith("AI Briefing · Special edition: "))
            self.assertIn("skipped", special.email(root, {}, day, fetch=lambda u: (200, ""), log=lambda *a: None))
        self.assertEqual(len(sent), 1)

    def test_site_page_not_in_feeds(self):
        root, day = _root(), "2026-11-04"
        _written(root, day)
        with open(root / special.LOG, "a") as f:
            f.write(json.dumps({"day": day, "status": "published", "title": "T"}) + "\n")
        (root / special.DIR / f"{day}.mp3").write_bytes(b"ID3")
        (root / special.DIR / f"{day}.script.md").write_text("## why_today\n\nBecause.\n")
        out = Path(tempfile.mkdtemp())
        made = special.site_pages(root, {}, out, "", lambda t, b, *a, **k: f"<h1>{t}</h1>{b}", lambda m: m)
        self.assertEqual(made, [day])
        html = (out / day / "special" / "index.html").read_text()
        self.assertIn(f"special-{day}.mp3", html)
        self.assertTrue((out / "audio" / f"special-{day}.mp3").exists())


class Headless(unittest.TestCase):
    def setUp(self):
        headless.reset()
        patcher = mock.patch("pipeline.netguard._host_ok", lambda h: bool(h) and not h.startswith("127."))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, html):
        return lambda *a, **k: mock.Mock(stdout=html)

    def test_respects_robots_and_walls(self):
        good = "<p>" + "word " * 600 + "</p>"
        cfg = {"fetch": {"user_agent": "news-pipeline/0.1"}}
        allow = lambda u: (200, "User-agent: *\nAllow: /\n")
        deny = lambda u: (200, "User-agent: *\nDisallow: /\n")
        self.assertEqual(headless.fetch("https://a.example/x", cfg, run=self._run(good), get=allow), good)
        headless.reset()
        self.assertEqual(headless.fetch("https://a.example/x", cfg, run=self._run(good), get=deny), "")
        headless.reset()
        wall = "<p>Just a moment... verify you are human</p>"
        self.assertEqual(headless.fetch("https://b.example/x", cfg, run=self._run(wall), get=allow), "")
        self.assertEqual(headless.fetch("http://127.0.0.1/x", cfg, run=self._run(good), get=allow), "")
        self.assertEqual(headless.fetch("https://c.example/x", {"fetch": {"headless": False}}, run=self._run(good), get=allow), "")

    def test_cap_and_no_real_browser_in_tests(self):
        cfg = {"fetch": {"headless_max_pages": 1}}
        good = "<p>" + "word " * 600 + "</p>"
        allow = lambda u: (200, "")
        self.assertTrue(headless.fetch("https://a.example/1", cfg, run=self._run(good), get=allow))
        self.assertEqual(headless.fetch("https://a.example/2", cfg, run=self._run(good), get=allow), "")
        headless.reset()
        self.assertEqual(headless.fetch("https://a.example/3", {}), "")     # NP_TESTING: never a real browser


if __name__ == "__main__":
    unittest.main()
