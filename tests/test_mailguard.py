import json
import tempfile
import unittest
from pathlib import Path

from pipeline.mailguard import GuardedIMAP, MailGuardError


class Box:
    def __init__(self):
        self.calls = []

    def select(self, f, readonly=True):
        self.calls.append(("select", f, readonly))
        return "OK", [b"1"]

    def search(self, *a):
        self.calls.append(("search",) + a)
        return "OK", [b"1 2"]

    def fetch(self, *a):
        self.calls.append(("fetch",) + a)
        return "OK", [(b"1", b"raw")]

    def uid(self, *a):
        self.calls.append(("uid",) + a)
        return "OK", [b"7"]

    def copy(self, *a):
        self.calls.append(("copy",) + a)

    def logout(self):
        pass


class Guard(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.box = Box()
        self.g = GuardedIMAP(self.box, {}, "test", self.root)

    def test_only_briefing_labels(self):
        for bad in ("INBOX", "[Gmail]/All Mail", "[Gmail]/Sent Mail", "AI-Briefing/Sources/../INBOX"):
            with self.assertRaises(MailGuardError):
                self.g.select(bad)
        self.g.select("AI-Briefing/Feedback")
        self.assertEqual(self.box.calls[-1], ("select", '"AI-Briefing/Feedback"', True))

    def test_reads_allowed_writes_fenced(self):
        with self.assertRaises(MailGuardError):
            self.g.search(None, "ALL")                       # nothing before a folder is chosen
        self.g.select("AI-Briefing/Sources")
        self.g.search(None, "SINCE", "01-Oct-2026")
        self.g.fetch(b"1", "(RFC822)")
        with self.assertRaises(MailGuardError):
            self.g.fetch(b"1", "(FLAGS)")
        with self.assertRaises(MailGuardError):              # read-only selection: no label writes
            self.g.uid("STORE", b"7", "+X-GM-LABELS", '("AI-Briefing/Cited")')
        self.g.select("AI-Briefing/Sources", readonly=False)
        self.g.uid("STORE", b"7", "+X-GM-LABELS", '("AI-Briefing/Briefing/2026-10-15" "AI-Briefing/Cited")')
        for args in ((b"7", "-X-GM-LABELS", '("AI-Briefing/Cited")'), (b"7", "+FLAGS", r"(\Deleted)"),
                     (b"7", "+X-GM-LABELS", '("\\\\Trash")'), (b"7", "+X-GM-LABELS", '("Personal")')):
            with self.assertRaises(MailGuardError):
                self.g.uid("STORE", *args)
        for cmd in ("COPY", "MOVE", "EXPUNGE"):
            with self.assertRaises(MailGuardError):
                self.g.uid(cmd, b"7", "INBOX")
        with self.assertRaises(MailGuardError):
            self.g.copy(b"1", "INBOX")
        with self.assertRaises(MailGuardError):
            self.g.expunge()
        self.assertFalse(any(c[0] == "copy" for c in self.box.calls))

    def test_audit_log_has_no_content(self):
        self.g.select("AI-Briefing/Sources")
        self.g.fetch(b"1", "(RFC822)")
        rows = [json.loads(x) for x in (self.root / "data/state/mail-audit.jsonl").read_text().splitlines()]
        self.assertEqual([r["op"] for r in rows], ["select", "fetch"])
        self.assertNotIn("raw", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()


class GuardInjection(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.box = Box()
        self.g = GuardedIMAP(self.box, {}, "test", self.root)
        self.g.select("AI-Briefing/Sources", readonly=False)

    def test_no_control_characters(self):
        with self.assertRaises(MailGuardError):
            self.g.uid("SEARCH", None, "X-GM-RAW", '"rfc822msgid:a@b"\r\nA1 UID STORE 1:* +X-GM-LABELS (\\Trash)')
        with self.assertRaises(MailGuardError):
            self.g.search(None, "SINCE", "01-Oct-2026\r\nA2 EXPUNGE")

    def test_label_list_must_be_only_briefing_labels(self):
        for bad in ('("AI-Briefing/x" \\Trash)', '("AI-Briefing/x") \\Trash', '(\\Trash "AI-Briefing/x")', '"AI-Briefing/x"'):
            with self.assertRaises(MailGuardError, msg=bad):
                self.g.uid("STORE", b"7", "+X-GM-LABELS", bad)

    def test_inner_connection_not_exposed(self):
        with self.assertRaises(MailGuardError):
            self.g._box
