import unittest

from pipeline import takes, site


class FakeLLM:
    def __init__(self, fixes):
        self.fixes = fixes

    def complete_json(self, system, user, max_tokens=None):
        return {"fixes": self.fixes}


class CopyEditTest(unittest.TestCase):
    def test_typo_fixed(self):
        text, edits = takes.copyedit("highly valueable use cases", FakeLLM([{"from": "valueable", "to": "valuable"}]))
        self.assertEqual(text, "highly valuable use cases")
        self.assertEqual(edits, [{"from": "valueable", "to": "valuable"}])

    def test_guess_too_far_refused(self):          # "healer" -> "better" is a guess at meaning, not a typo fix
        self.assertEqual(takes.copyedit("move to healer and cheaper", FakeLLM([{"from": "healer", "to": "better"}])),
                         ("move to healer and cheaper", []))

    def test_rewrites_refused(self):
        for f in [{"from": "Round", "to": "Circular"}, {"from": "imho", "to": "in my opinion"}, {"from": "x", "to": "x"}]:
            text, edits = takes.copyedit("Round and round imho x", FakeLLM([f]))
            self.assertEqual((text, edits), ("Round and round imho x", []), f)

    def test_failure_keeps_text(self):
        class Bad:
            def complete_json(self, *a, **k):
                raise RuntimeError("down")
        self.assertEqual(takes.copyedit("teh note", Bad()), ("teh note", []))


class LeadTest(unittest.TestCase):
    def test_lead_key(self):
        self.assertEqual(takes.lead_key({"overall": "x", "top": "y"}), "overall")
        self.assertEqual(takes.lead_key({"top": "y"}), "top")
        self.assertEqual(takes.lead_key({}), "")

    def test_site_puts_overall_under_the_title(self):
        page = "<h1>AI Briefing</h1><h2>Today in 30 seconds</h2><ul><li>a</li></ul>"
        out = site._with_takes(page, {"overall": {"text": "Slowly, then fast."}})
        self.assertLess(out.index("Slowly, then fast."), out.index("Today in 30 seconds"))


if __name__ == "__main__":
    unittest.main()
