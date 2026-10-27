"""The edition and deep dive as Google Docs in Drive (v0.2.11, Steven 2026-10-26)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import deepdive, drivedocs, mailer

ROOT = Path(__file__).resolve().parent.parent
DAY = "2026-10-26"
MD = ("# AI Briefing · Monday, October 26, 2026\n\n**The day in brief.** Two stories.\n\n## Top of mind\n\n"
      "- **Margins are the story.** Corvane raised.\n- **Second thing.** More.\n")
CFG = {"paths": {"briefings": "briefings"}}


def make_root():
    root = Path(tempfile.mkdtemp())
    (root / "briefings").mkdir()
    (root / "briefings" / f"{DAY}.md").write_text(MD, "utf-8")
    return root


class Names(unittest.TestCase):
    def test_names_start_with_the_date(self):
        draft, final = drivedocs.names(DAY, MD)
        self.assertEqual(final, "2026-10-26 · AI Briefing · Margins are the story")
        self.assertEqual(draft, "2026-10-26 · AI Briefing (draft, held for your takes) · Margins are the story")
        self.assertEqual(drivedocs.deepdive_name(DAY, "Deep dive: Payoff outside tech"), "2026-10-26 · Deep dive · Payoff outside tech")
        self.assertIn("Monday, October 26, 2026", drivedocs.names(DAY, "# AI Briefing · Monday, October 26, 2026\n")[1])


class Save(unittest.TestCase):
    def run_save(self, root, final):
        calls = []
        with mock.patch.object(mailer, "call", side_effect=lambda cfg, a, _alert=False, **p:
                               calls.append((a, p)) or {"ok": True, "url": f"https://docs.example/{len(calls)}"}):
            out = drivedocs.save_day(root, CFG, DAY, final=final, log=lambda *a: None)
        return out, calls

    def test_draft_then_final_renames_and_adds_takes(self):
        root = make_root()
        (root / "data" / "commentary").mkdir(parents=True)
        (root / "data" / "commentary" / f"{DAY}.json").write_text(json.dumps(
            {"notes": {"overall": {"text": "Slowly, then fast.", "title": "The day overall"}}}), "utf-8")
        out, calls = self.run_save(root, final=False)
        self.assertEqual(calls[0][0], "savedoc")
        self.assertIn("draft, held", calls[0][1]["name"])
        self.assertNotIn("Steven's takes", calls[0][1]["text"])
        self.assertNotIn("replace", calls[0][1])
        self.assertEqual(out, {"briefing": "https://docs.example/1"})          # no deep dive that day
        out, calls = self.run_save(root, final=True)
        self.assertEqual(calls[0][1]["name"], "2026-10-26 · AI Briefing · Margins are the story")
        self.assertIn("draft, held", calls[0][1]["replace"])                 # the draft becomes the published doc
        self.assertIn("- **The day overall:** Slowly, then fast.", calls[0][1]["text"])

    def test_deep_dive_doc_has_notes_article_and_sources(self):
        root = make_root()
        d = root / deepdive.DIR
        d.mkdir(parents=True)
        (d / f"{DAY}.md").write_text("# Deep dive: Payoff\n\n*AI Briefing · x*\n\nSummary.\n\n## Sources\n\n- [A](https://a.example)\n", "utf-8")
        (d / f"{DAY}.script.md").write_text("# x\n\n## plainly\n\nBody text.\n\n## steven_take\n\nHere's Steven's take. Mine.\n", "utf-8")
        out, calls = self.run_save(root, final=True)
        name, text = calls[1][1]["name"], calls[1][1]["text"]
        self.assertEqual(name, "2026-10-26 · Deep dive · Payoff")
        self.assertLess(text.index("Summary."), text.index("Body text."))
        self.assertLess(text.index("## Steven's take\n\nMine."), text.index("## Sources"))
        self.assertEqual(set(out), {"briefing", "deepdive"})

    def test_a_drive_failure_never_raises(self):
        root = make_root()
        with mock.patch.object(mailer, "call", side_effect=mailer.MailError("down")):
            self.assertEqual(drivedocs.save_day(root, CFG, DAY, final=True, log=lambda *a: None), {})
        self.assertEqual(drivedocs.save_day(root, {**CFG, "drive": {"enabled": False}}, DAY, final=True), {})


class Wiring(unittest.TestCase):
    def test_script_and_run_wiring(self):
        gs = (ROOT / "scripts" / "apps-script" / "Code.gs").read_text("utf-8")
        auth = gs.index("if (!authed_(p)) return json_")
        self.assertGreater(gs.index("if (p.action === 'savedoc')"), auth)                   # key only
        self.assertNotIn("setTrashed", gs)                                                   # never deletes
        doc = gs[gs.index("function saveDoc_"):gs.index("function authorizeDrive")]
        self.assertLess(doc.index("try {"), doc.index("removeFromParent"))                  # 10-27: rewrite failed
        self.assertLess(doc.index("body.appendParagraph('')"), doc.index("body.clear()"))   # list item at the end
        run = (ROOT / "run.py").read_text("utf-8")
        self.assertIn("drivedocs.save_day(ROOT, cfg, today, final=False", run)              # with the takes email
        self.assertEqual(run.count("drivedocs.save_day(ROOT, cfg, today, final=True"), 2)   # after each publish
        from pipeline import runner
        self.assertEqual(runner.RECIPES["drive-save"]["tier"], "auto")

    def test_takes_email_links_the_draft_doc(self):
        from pipeline import takes
        root = make_root()
        with mock.patch.object(takes, "slots", return_value=[]):
            m = takes.build_email(root, CFG, DAY, review=False, drive="https://docs.google.com/document/d/abc/edit")
        self.assertIn('href="https://docs.google.com/document/d/abc/edit"', m["html"])
        self.assertIn("Read it in Google Docs: https://docs.google.com/document/d/abc/edit", m["text"])


if __name__ == "__main__":
    unittest.main()
