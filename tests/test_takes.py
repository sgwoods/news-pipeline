"""Steven's takes (pipeline/takes.py): slots, reply parsing, Slack words, the privacy hold, the wait, audio, email."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import mailer, takes
from pipeline.textutil import item_id

DAY = "2026-10-24"
URL1, URL2 = "https://example.com/corvane-raise", "https://example.com/dunmore-chips"


def make_root():
    root = Path(tempfile.mkdtemp())
    (root / "data" / "stories").mkdir(parents=True)
    stories = [{"section": "must", "n": 1, "headline": "Corvane raises $550M", "lead_url": URL1, "lead_id": item_id(URL1),
                "ids": ["aaaa1111bbbb2222"], "what_happened": "Corvane raised $550M."},
               {"section": "must", "n": 2, "headline": "Dunmore doubles", "lead_url": URL2, "lead_id": item_id(URL2),
                "ids": ["cccc3333dddd4444"], "what_happened": "Dunmore raised $1.5B."}]
    (root / "data" / "stories" / f"{DAY}.jsonl").write_text(json.dumps({"stories": stories}) + "\n", "utf-8")
    return root


CFG = {"takes": {"enabled": True, "cutoff": "09:15"}, "paths": {"briefings": "briefings"}}


class Parse(unittest.TestCase):
    def test_numbered_lines_continuations_and_done(self):
        r = takes.parse("1: The margin matters\nmore than the headline.\n\nT - Watch the sovereign money.\n0) Quiet day.\ndone")
        self.assertEqual(r["takes"], {"1": "The margin matters more than the headline.", "T": "Watch the sovereign money.",
                                      "0": "Quiet day."})
        self.assertTrue(r["done"])
        self.assertFalse(r["skip"])

    def test_skip_and_loose_formatting(self):
        r = takes.parse("  take 2 :  Chips are a capex story  \nskip")
        self.assertEqual(r["takes"], {"2": "Chips are a capex story"})
        self.assertTrue(r["skip"])

    def test_prose_without_numbers_is_not_a_take(self):
        self.assertEqual(takes.parse("Thanks, looks good")["takes"], {})

    def test_slack_text_keeps_only_his_words(self):
        self.assertEqual(takes.slack_text("This is the real story <https://x.com/a|link> cc <@U123> in <#C1|general>"),
                         "This is the real story cc in")


class Slots(unittest.TestCase):
    def test_slots_and_email(self):
        root = make_root()
        sl = takes.slots(root, DAY)
        self.assertEqual([s["slot"] for s in sl], ["0", "T", "1", "2"])
        self.assertEqual(sl[2]["key"], item_id(URL1))
        (root / "briefings").mkdir()
        (root / "briefings" / f"{DAY}.md").write_text(MD, "utf-8")
        with mock.patch("pipeline.mailsource.mcfg", return_value={"account": "briefing@example.com"}):
            m = takes.build_email(root, CFG, DAY)
        self.assertEqual(m["subject"], "AI Briefing · Your takes · Sat Oct 24")
        self.assertIn("1: Corvane raises $550M", m["text"])
        self.assertIn("09:15", m["text"])
        self.assertIn("Corvane raised $550M.", m["html"])                       # the edition itself, to read
        self.assertIn("mailto:briefing@example.com?subject=Re%3A%20AI%20Briefing%20%C2%B7%20Your%20takes", m["html"])
        self.assertIn("&amp;body=1%3A%20", m["html"])                           # the reply opens with "1: "
        self.assertIn("Add your take on this (T)", m["html"])
        self.assertIn("https://sgwoods.github.io/ai-briefing/2026-10-24/", m["html"])
        r = takes.parse("1: Margins matter.")                                   # what the reply contains parses
        self.assertEqual(r["takes"], {"1": "Margins matter."})


class Collect(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        p1 = mock.patch("pipeline.stages.private_names", return_value=["Alex Morgan"])
        p2 = mock.patch("pipeline.owner.addresses", return_value=["owner@example.com"])
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def notes(self):
        p = self.root / "data" / "commentary" / f"{DAY}.json"
        return json.loads(p.read_text("utf-8"))["notes"] if p.exists() else {}

    def test_clean_takes_publish_and_private_ones_are_held(self):
        st = takes.collect(self.root, CFG, DAY, [{"takes": {"1": "Margins matter.", "2": "Alex Morgan told me this."},
                                                 "done": True, "skip": False}])
        self.assertEqual([p["slot"] for p in st["published"]], ["1"])
        self.assertEqual(st["held"][0]["slot"], "2")
        self.assertIn("private name", st["held"][0]["why"][0])
        n = self.notes()
        self.assertEqual(n[item_id(URL1)]["text"], "Margins matter.")
        self.assertNotIn(item_id(URL2), n)

    def test_owner_address_and_disclosure_are_held(self):
        st = takes.collect(self.root, CFG, DAY, [{"takes": {"0": "Mail me at owner@example.com",
                                                            "T": "Shared by Steven, as usual."}, "done": False}])
        self.assertEqual(st["published"], [])
        self.assertEqual(len(st["held"]), 2)

    def test_reply_beats_slack_and_slack_alone_counts(self):
        takes.add_slack(self.root, [
            {"ts": "1", "at": f"{DAY}T07:10:00-04:00", "id": item_id(URL1), "url": URL1, "text": "Slack view one"},
            {"ts": "2", "at": f"{DAY}T07:20:00-04:00", "id": "cccc3333dddd4444", "url": URL2, "text": "Slack view two"}])
        st = takes.collect(self.root, CFG, DAY, [{"takes": {"1": "Reply view one"}, "done": True}])
        got = {p["slot"]: (p["text"], p["from"]) for p in st["published"]}
        self.assertEqual(got["1"], ("Reply view one", "reply"))
        self.assertEqual(got["2"], ("Slack view two", "slack"))

    def test_skip_publishes_nothing_and_unknown_slots_are_reported(self):
        st = takes.collect(self.root, CFG, DAY, [{"takes": {"1": "x y z", "7": "no such story"}, "skip": True}])
        self.assertEqual(st["published"], [])
        st = takes.collect(self.root, {**CFG}, "2026-10-24", [{"takes": {"7": "no such story"}}])
        self.assertEqual(st["unknown"][0]["slot"], "7")


class Wait(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        p = mock.patch("pipeline.stages.private_names", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def test_waits_until_done(self):
        clock = [dt.datetime(2026, 10, 24, 7, 0)]
        calls = []

        def fetch():
            calls.append(1)
            return [{"takes": {"1": "Fine."}, "done": len(calls) >= 3}]
        st = takes.wait(self.root, CFG, DAY, log=lambda *a: None, now=lambda: clock[0],
                        sleep=lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=s)), fetch=fetch)
        self.assertEqual(len(calls), 3)
        self.assertTrue(st["done"])
        self.assertLess(clock[0], dt.datetime(2026, 10, 24, 9, 15))

    def test_stops_at_the_cutoff_with_no_replies(self):
        clock = [dt.datetime(2026, 10, 24, 9, 0)]
        st = takes.wait(self.root, CFG, DAY, log=lambda *a: None, now=lambda: clock[0],
                        sleep=lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=s)), fetch=lambda: [])
        self.assertEqual(st["published"], [])
        self.assertGreaterEqual(clock[0], dt.datetime(2026, 10, 24, 9, 15))
        self.assertLess(clock[0], dt.datetime(2026, 10, 24, 9, 16))

    def test_release_now_ends_the_wait(self):
        clock = [dt.datetime(2026, 10, 24, 7, 0)]

        def fetch():
            takes.release_now(self.root, DAY)
            return []
        takes.wait(self.root, CFG, DAY, log=lambda *a: None, now=lambda: clock[0], sleep=lambda s: None, fetch=fetch)
        self.assertEqual(clock[0], dt.datetime(2026, 10, 24, 7, 0))

    def test_a_mailbox_error_never_raises(self):
        clock = [dt.datetime(2026, 10, 24, 9, 14)]

        def fetch():
            raise OSError("imap down")
        st = takes.wait(self.root, CFG, DAY, log=lambda *a: None, now=lambda: clock[0],
                        sleep=lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=s)), fetch=fetch)
        self.assertEqual(st["published"], [])

    def test_pending_and_released(self):
        import os
        takes.mark_pending(self.root, DAY, os.getpid())
        self.assertTrue(takes.waiting(self.root, DAY))
        takes.mark_released(self.root, DAY)
        self.assertFalse(takes.waiting(self.root, DAY))
        takes.mark_pending(self.root, DAY, 999999)          # a run that died: not waiting
        self.assertFalse(takes.waiting(self.root, DAY))


class Audio(unittest.TestCase):
    def test_takes_go_after_their_story_and_before_the_close(self):
        parts = [("Intro", "Hi."), ("Story 1", "One."), ("Story 2", "Two."), ("Close", "Bye."), ("Outro", "Out.")]
        st = {"published": [{"slot": "1", "text": "Margins matter."}, {"slot": "0", "text": "Quiet day."},
                            {"slot": "T", "text": "Watch money."}]}
        with mock.patch("pipeline.speech.load_table", return_value={}), \
                mock.patch("pipeline.speech.spoken", side_effect=lambda s, t: s):
            out = takes.audio_parts(parts, st)
        names = [n for n, _ in out]
        self.assertEqual(names, ["Intro", "Take top", "Story 1", "Take 1", "Story 2", "Take overall", "Close", "Outro"])
        self.assertEqual(dict(out)["Take 1"], "Here's Steven's take. Margins matter.")

    def test_a_story_the_episode_does_not_voice_gets_its_take_after_the_quick_hits(self):
        parts = [("Intro", "Hi."), ("Story 1", "One."), ("Quick hits", "More."), ("Close", "Bye.")]
        st = {"published": [{"slot": "5", "title": "Dunmore doubles", "text": "Capex story."}]}
        with mock.patch("pipeline.speech.load_table", return_value={}), \
                mock.patch("pipeline.speech.spoken", side_effect=lambda s, t: s):
            out = takes.audio_parts(parts, st)
        self.assertEqual([n for n, _ in out], ["Intro", "Story 1", "Quick hits", "Take 5", "Close"])
        self.assertIn("On Dunmore doubles, here's Steven's take.", dict(out)["Take 5"])

    def test_spoken_text_round_trip(self):
        p = Path(tempfile.mkdtemp()) / "x.spoken.txt"
        p.write_text("[Intro]\nHello there.\n\n[Story 1]\nLine one.\nLine two.\n", "utf-8")
        self.assertEqual(takes.read_spoken(p), [("Intro", "Hello there."), ("Story 1", "Line one.\nLine two.")])


MD = f"""# AI Briefing · Saturday

**The day in brief.** Two stories.

## Top of mind

- **Corvane raises.** Corvane raised $550M. [1]({URL1})

## Must read

### 1. Corvane raises $550M
**Example News** · report · [source]({URL1})

- **What happened:** Corvane raised $550M.
"""


class Email(unittest.TestCase):
    def test_takes_appear_in_the_subscriber_email(self):
        msg = mailer.render(DAY, MD, {}, takes={item_id(URL1): "Margins matter.", "top": "Watch money.",
                                                "overall": "Quiet day."})
        for t in ("Margins matter.", "Watch money.", "Quiet day."):
            self.assertIn(t, msg["html"])
            self.assertIn(t, msg["text"])
        self.assertIn("Steven&#x27;s take", msg["html"])

    def test_no_takes_no_box(self):
        msg = mailer.render(DAY, MD, {})
        self.assertNotIn("Steven&#x27;s take", msg["html"])


class Feedback(unittest.TestCase):
    def test_takes_replies_are_not_feedback(self):
        from email.message import EmailMessage
        from pipeline import feedback
        m = EmailMessage()
        m["Subject"] = "Re: AI Briefing · Your takes · Sat Oct 24"
        m["From"] = "owner@example.com"
        m["In-Reply-To"] = "<x@y>"
        m.set_content("1: Margins matter.")
        self.assertIsNone(feedback.parse_reply(m.as_bytes(), {}))


class Sending(unittest.TestCase):
    """Calls the real mailer.call signature (2026-10-24: positional arguments broke the first takes morning)."""
    def test_takes_email_and_held_note_use_the_mailer_signature(self):
        root = make_root()
        sent = []
        real = mailer.call

        def fake(cfg, action, _alert=False, **params):
            import inspect
            inspect.signature(real).bind(cfg, action, _alert, **params)      # raises if the call shape is wrong
            sent.append(params)
            return {"ok": True}
        with mock.patch.object(mailer, "call", side_effect=fake), \
                mock.patch.object(mailer, "ecfg", return_value={"test_to": "owner@example.com"}):
            self.assertIn("sent", takes.send_email(root, CFG, DAY))
            takes.report_email(root, CFG, DAY, {"published": [], "held": [{"slot": "1", "title": "x", "why": ["a private name"]}]})
        self.assertEqual(sent[0]["to"], "owner@example.com")
        self.assertTrue(sent[0]["subject"].startswith("AI Briefing · Your takes"))
        self.assertIn("held back", sent[1]["subject"])
        self.assertEqual(takes.send_email(root, CFG, DAY)[:28], "takes email already sent at ")


class WorthAndColours(unittest.TestCase):
    def test_worth_slot_light_bold_and_audio(self):
        root = make_root()
        f = root / "data" / "stories" / f"{DAY}.jsonl"
        rows = json.loads(f.read_text("utf-8"))
        rows["stories"].append({"section": "worth", "n": 3, "headline": "Small thing"})
        f.write_text(json.dumps(rows) + "\n", "utf-8")
        self.assertEqual([s["slot"] for s in takes.slots(root, DAY)], ["0", "T", "1", "2", "W"])
        (root / "briefings").mkdir()
        (root / "briefings" / f"{DAY}.md").write_text(MD + "\n## Worth knowing\n\n- **3. Small thing.** It matters a bit.\n", "utf-8")
        with mock.patch("pipeline.mailsource.mcfg", return_value={"account": "briefing@example.com"}):
            m = takes.build_email(root, CFG, DAY)
        self.assertIn("Add your take on this (W)", m["html"])
        self.assertIn('<strong style="color:#111827">Corvane raises.</strong>', m["html"])   # readable on white
        self.assertNotIn("#d7ecff", m["html"])
        self.assertEqual(takes.parse("W: Quick hits were thin")["takes"], {"W": "Quick hits were thin"})
        parts = [("Intro", "Hi."), ("Quick hits", "More."), ("Close", "Bye.")]
        with mock.patch("pipeline.speech.load_table", return_value={}), \
                mock.patch("pipeline.speech.spoken", side_effect=lambda s, t: s):
            out = takes.audio_parts(parts, {"published": [{"slot": "W", "text": "Thin today."}]})
        self.assertEqual([n for n, _ in out], ["Intro", "Quick hits", "Take worth", "Close"])
        msg = mailer.render(DAY, MD + "\n## Worth knowing\n\n- **3. Small thing.** It matters.\n", {},
                            takes={"worth": "Thin today."})
        self.assertIn("Thin today.", msg["html"])


class SiteTakes(unittest.TestCase):
    """Takes typed on the site page (takes.js) go to the mail script and back to the pipeline (v0.2.7)."""
    def test_site_rows_become_reply_like_rows(self):
        rows = {"ok": True, "takes": [{"at": "2026-10-24T07:10:00Z", "slot": "1", "text": "Margins.", "done": False},
                                      {"at": "2026-10-24T07:12:00Z", "slot": "w", "text": "Thin.", "done": False},
                                      {"at": "2026-10-24T07:13:00Z", "slot": "DONE", "text": "", "done": True},
                                      {"at": "2026-10-24T07:14:00Z", "slot": "ZZ", "text": "bad slot", "done": False}]}
        with mock.patch.object(mailer, "call", return_value=rows) as call:
            out = takes.fetch_site({}, DAY)
        call.assert_called_once_with({}, "takes_pull", d=DAY)
        self.assertEqual([r["takes"] for r in out], [{"1": "Margins."}, {"W": "Thin."}, {}])
        self.assertTrue(out[2]["done"])

    def test_fetch_all_merges_replies_and_site_in_time_order(self):
        with mock.patch.object(takes, "fetch_replies", return_value=[{"received": "2026-10-24T07:20:00+00:00",
                                                                     "takes": {"1": "Later email."}, "done": False}]), \
                mock.patch.object(takes, "fetch_site", return_value=[{"received": "2026-10-24T07:10:00Z",
                                                                      "takes": {"1": "Site first."}, "done": False}]):
            out = takes.fetch_all(Path("."), {}, DAY)
        self.assertEqual([r["takes"]["1"] for r in out], ["Site first.", "Later email."])

    def test_one_failing_source_does_not_stop_the_other(self):
        with mock.patch.object(takes, "fetch_replies", side_effect=OSError("imap down")), \
                mock.patch.object(takes, "fetch_site", return_value=[{"received": "x", "takes": {"T": "ok"}}]):
            self.assertEqual(len(takes.fetch_all(Path("."), {}, DAY, log=lambda *a: None)), 1)

    def test_email_link_carries_the_placeholder_only_after_defusing(self):
        root = make_root()
        (root / "briefings").mkdir()
        (root / "briefings" / f"{DAY}.md").write_text(MD.replace("Corvane raised $550M.", "Corvane {{OWNERT}} raised."), "utf-8")
        sent = []
        with mock.patch.object(mailer, "call", side_effect=lambda cfg, a, _alert=False, **p: sent.append(p) or {"ok": True}), \
                mock.patch.object(mailer, "ecfg", return_value={"test_to": "owner@example.com"}), \
                mock.patch("pipeline.mailsource.mcfg", return_value={"account": "briefing@example.com"}):
            takes.send_email(root, CFG, DAY)
        html = sent[0]["html"]
        self.assertIn("2026-10-24/#takes={{OWNERT}}", html)
        self.assertEqual(html.count("{{OWNERT}}"), 1)                 # a story can't inject the placeholder
        self.assertIn("#takes={{OWNERT}}", sent[0]["text"])

    def test_takes_pull_is_a_read_action(self):
        self.assertIn("takes_pull", mailer.READ_ACTIONS)


class SitePageAndScript(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_mail_script_checks_the_takes_token(self):
        gs = (self.ROOT / "scripts" / "apps-script" / "Code.gs").read_text("utf-8")
        self.assertIn("t: 2", gs)
        self.assertIn("if (!ownerOf_(p.t, 't')) return page_('Link not recognised'", gs)
        self.assertLess(gs.index("p.action === 'takes')"), gs.index("if (!authed_(p)) return json_"))
        self.assertGreater(gs.index("p.action === 'takes_pull'"), gs.index("if (!authed_(p)) return json_"))
        self.assertIn(".split('{{OWNERT}}').join(ownt)", gs)

    def test_takes_script_only_with_the_token_and_a_script_url(self):
        from pipeline import site
        js = site.TAKES_JS
        self.assertIn("takes=([A-Za-z0-9_-]{8,64})", js)
        self.assertIn("script\\.google\\.com", js)
        self.assertNotIn("innerHTML", js)                             # no page text built from strings
        self.assertIn('data-takes', site.TAKES_JS.replace('"script[data-takes]"', "data-takes"))


if __name__ == "__main__":
    unittest.main()
