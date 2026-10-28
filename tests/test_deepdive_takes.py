"""Steven's take on a deep dive (v0.2.11): set from the evening email's queue page or the dashboard, read verbatim
after the deep dive. And every topic in the evening email has its own buttons (Steven, 2026-10-26)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import deepdive, editor_note, mailer

ROOT = Path(__file__).resolve().parent.parent


def queue3(root):
    a = deepdive.add_manual(root, "Chip export controls", day="2026-10-26")
    b = deepdive.add_manual(root, "Robot fleet economics", day="2026-10-26")
    c = deepdive.add_manual(root, "Inference pricing wars", day="2026-10-26")
    s = deepdive.add_suggestions(root, "2026-10-26", [{"topic": "Sovereign cloud demand", "strength": 4, "why_today": "x"}], [])[0]
    return a, b, c, s


class Take(unittest.TestCase):
    def test_set_clear_and_snapshot(self):
        root = Path(tempfile.mkdtemp())
        a, *_ = queue3(root)
        deepdive.set_take(root, a["id"], "  Slow,\n then fast.  ")
        self.assertEqual(deepdive.load_queue(root)[0]["take"], "Slow, then fast.")
        self.assertEqual(deepdive.snapshot(root)[0]["take"], "Slow, then fast.")
        deepdive.set_take(root, a["id"], "")
        self.assertNotIn("take", deepdive.load_queue(root)[0])
        with self.assertRaises(KeyError):
            deepdive.set_take(root, "nope", "x")

    def test_take_part_is_verbatim_and_privacy_held(self):
        with mock.patch("pipeline.takes.problems", return_value=[]):
            self.assertEqual(deepdive.take_part({"take": "It matters."}, {}),
                             ("steven_take", "Here's Steven's take. It matters."))
        with mock.patch("pipeline.takes.problems", return_value=["a private name"]):
            self.assertIsNone(deepdive.take_part({"take": "secret"}, {}, log=lambda *a: None))
        self.assertIsNone(deepdive.take_part({}, {}))

    def test_written_article_shows_the_take_under_its_heading(self):
        root = Path(tempfile.mkdtemp())
        d = root / deepdive.DIR
        d.mkdir(parents=True)
        (d / "2026-10-27.script.md").write_text("# x\n\n## Opener\n\nHi\n\n## plainly\n\nBody.\n\n## steven_take\n\n"
                                                "Here's Steven's take. Ramp slowly.\n\n## Outro\n\nBye\n", "utf-8")
        md = deepdive.written_md(root, "2026-10-27")
        self.assertIn("## Steven's take\n\nRamp slowly.", md)

    def test_queue_page_actions_apply(self):
        root = Path(tempfile.mkdtemp())
        a, b, c, s = queue3(root)
        acts = [{"at": "2026-10-26T20:00:01", "op": "take", "id": b["id"], "angle": "My words."},
                {"at": "2026-10-26T20:00:02", "op": "queue", "id": s["id"]}]
        with mock.patch.object(mailer, "call", return_value={"ok": True, "actions": acts}):
            self.assertEqual(deepdive.apply_remote(root, {}, log=lambda *a: None), 2)
        q = deepdive.queued(root)
        self.assertEqual([x["topic"] for x in q][-1], "Sovereign cloud demand")
        self.assertEqual(next(x for x in q if x["id"] == b["id"])["take"], "My words.")


class EveningEmail(unittest.TestCase):
    def test_every_topic_has_its_own_buttons(self):
        root = Path(tempfile.mkdtemp())
        a, b, c, s = queue3(root)
        deepdive.set_take(root, a["id"], "Already said.")
        m = editor_note.build(root, {}, "2026-10-26")
        page = "{{SCRIPT}}?action=queue&t={{OWNER}}"
        self.assertIn(f"{page}&pick={a['id']}&op=take", m["text"])             # tomorrow's: add your take
        self.assertIn("Your take: Already said.", m["text"])
        for op in ("next", "down", "take", "dismiss"):                          # the second in line
            self.assertIn(f"&pick={b['id']}&op={op}", m["text"])
        for op in ("next", "up", "take", "dismiss"):                            # the last one
            self.assertIn(f"&pick={c['id']}&op={op}", m["text"])
        for op in ("next", "queue", "take", "dismiss"):                         # a suggestion
            self.assertIn(f"&pick={s['id']}&op={op}", m["text"])

    def test_links_keep_their_placeholders_after_defusing(self):
        root = Path(tempfile.mkdtemp())
        a, *_ = queue3(root)
        deepdive.set_take(root, a["id"], "Sneaky {{OWNER}} here")
        sent = []
        with mock.patch.object(mailer, "call", side_effect=lambda cfg, act, _alert=False, **p: sent.append(p) or {"ok": True}), \
                mock.patch.object(mailer, "ecfg", return_value={"test_to": "owner@example.com"}):
            editor_note.send(root, {}, "2026-10-26", new_mentions=[])
        html = sent[-1]["html"]
        self.assertIn("{{SCRIPT}}?action=queue&amp;t={{OWNER}}&amp;pick=", html)
        self.assertNotIn("Sneaky {{OWNER}}", html)                               # a take can't inject the token


class Script(unittest.TestCase):
    def test_queue_page_take_and_queue_ops(self):
        gs = (ROOT / "scripts" / "apps-script" / "Code.gs").read_text("utf-8")
        self.assertIn("'queue', 'take'].indexOf(op)", gs)
        self.assertIn("QHEAD = ['id', 'topic', 'status', 'why', 'take', 'by']", gs)
        self.assertIn("ask[0].split('%').join(esc_(it.topic))", gs)             # topic text is escaped, never a pattern
        page = gs[gs.index("function queuePage_"):gs.index("function stars_")]
        self.assertIn("esc_(r.take || '')", page)


class Dashboard(unittest.TestCase):
    def test_deep_dives_page_has_a_take_box(self):
        t = (ROOT / "dashboard" / "templates" / "deepdives.html").read_text("utf-8")
        self.assertIn('action="/api/deep-dives/{{ x.id }}/take"', t)
        self.assertIn('elif op == "take"', (ROOT / "dashboard" / "explore.py").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
