"""The weekly critic email (pipeline/critic.py) and the run-queue jobs around it."""
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import critic, mailer, runner

DIMS = [k for k, _, _ in critic.DIMS]


def week(date, us, shows=None):
    shows = shows or [("Alpha Show", 8), ("Beta Letter", 6), ("Gamma Cast", 4)]
    return {"date": date, "method": "Latest episodes, read not heard.",
            "shows": [{"name": n, "episode": f"{n} ep", "date": date, "link": "https://example.com/" + n.split()[0].lower(),
                       "scores": {k: v for k in DIMS}} for n, v in shows],
            "ours": {"scores": {k: us for k in DIMS}, "written_overall": us * 10, "podcast_overall": us * 10 - 1},
            "strengths": ["Evidence labels"],
            "suggestions": [{"title": f"Suggestion {i}", "evidence": f"Evidence {i}",
                             "options": [f"A. Option {i}a", f"B. Option {i}b"], "pick": "B" if i == 1 else "A"}
                            for i in range(1, 11)],
            "first_batch": ["1A", "2A"]}


class Render(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_overall_uses_the_weights(self):
        self.assertEqual(critic.overall({k: 10 for k in DIMS}), 100.0)
        self.assertEqual(sum(w for _, _, w in critic.DIMS), 100)

    def test_first_week_email(self):
        critic.save(self.root, week("2026-10-24", 6))
        m = critic.render(self.root)
        self.assertIn("60.0/100, #2 of 4", m["subject"])      # ties share the better rank
        self.assertIn("First week on record", m["html"])
        self.assertIn("so the trend shows from next week", m["html"])
        self.assertIn("Recommended: B. Option 1b", m["html"])
        self.assertIn("Other suggestions", m["html"])
        self.assertIn("Content selection (18): 6 / 6.0", m["text"])

    def test_trend_and_delta_over_weeks(self):
        critic.save(self.root, week("2026-10-24", 6))
        critic.save(self.root, week("2026-10-31", 7))
        m = critic.render(self.root)
        self.assertIn("+10.0 since 2026-10-24", m["html"])
        self.assertIn("10-31", m["html"])
        self.assertIn("▲ +1.0", m["html"])
        old = critic.render(self.root, "2026-10-24")
        self.assertIn("First week on record", old["html"])

    def test_shipped_lists_this_weeks_releases(self):
        (self.root / "data" / "state").mkdir(parents=True)
        (self.root / "data" / "state" / "releases.jsonl").write_text(
            json.dumps({"at": "2026-10-23T17:50:00", "kind": "release", "version": "0.2.0-beta",
                        "note": "reviewed: takes"}) + "\n", "utf-8")
        critic.save(self.root, week("2026-10-24", 6))
        self.assertIn("v0.2.0-beta: takes", critic.render(self.root)["html"])

    def test_send_goes_to_the_owner_with_the_mailer_signature(self):
        critic.save(self.root, week("2026-10-24", 6))
        sent = []

        def fake(cfg, action, _alert=False, **params):
            inspect.signature(mailer.call).bind(cfg, action, _alert, **params)
            sent.append(params)
            return {"ok": True}
        with mock.patch.object(mailer, "call", side_effect=fake), \
                mock.patch.object(mailer, "ecfg", return_value={"test_to": "owner@example.com"}):
            critic.send(self.root, {})
        self.assertEqual(sent[0]["to"], "owner@example.com")
        self.assertTrue(sent[0]["subject"].startswith("AI Briefing · Weekly critic"))

    def test_no_results_is_an_error(self):
        with self.assertRaises(RuntimeError):
            critic.render(self.root)


class Jobs(unittest.TestCase):
    def test_recipes_still_put_approvals_behind_the_click(self):
        self.assertEqual(runner.recipe_problems(), [])

    def test_source_add_needs_https_urls_and_steven(self):
        ok = runner.validate({"id": "a", "recipe": "source-add", "chat_approval": "yes, add them",
                              "args": {"name": "Example Show", "url": "https://example.com/feed"}})
        self.assertEqual(runner.argv_for(runner.RECIPES["source-add"]["steps"][0][1], ok["args"]),
                         ["sources", "add", "Example Show", "https://example.com/feed"])
        for bad in ("http://example.com/feed", "https://example.com/feed; rm -rf /", "javascript:alert(1)"):
            with self.assertRaises(runner.JobError):
                runner.validate({"id": "a", "recipe": "source-add", "chat_approval": "yes",
                                 "args": {"name": "X", "url": bad}})
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "source-add", "args": {"name": "X", "url": "https://example.com/f"}})

    def test_critic_email_is_automatic(self):
        self.assertEqual(runner.RECIPES["critic-email"]["tier"], "auto")


if __name__ == "__main__":
    unittest.main()
