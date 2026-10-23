"""Headers and Agenda lines must agree with the checked text and the sources (the 2026-10-23 deep dive)."""
import os
import tempfile
import unittest
from pathlib import Path

for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
    os.environ.pop(_k, None)

from pipeline import consistency as c, shipped  # noqa: E402

BODY = ("On October 21, Legora announced a $550M Series E at an $8.8B post-money valuation. Legora says its annual "
        "recurring revenue now stands at more than $200M. It does not disclose margin or retention. On the same day, "
        'the investor Keith Rabois posted on X that Quillery, a contract-drafting tool, "is saving a Fortune 100 '
        'company $21 m in outside counsel legal fees."')


class Headers(unittest.TestCase):
    def test_the_oct_23_why_today_line_is_refused(self):
        why = ("Legora raised $550M at $8.8B (up from $5.6B) with no disclosed ARR, margin or retention, the same day a "
               "vendor posted a $21M customer-savings claim with no stated method, period or named customer.")
        kept, notes = c.check_header(why, BODY + " Its previous round valued it at $5.6B.")
        self.assertEqual(kept, "")
        self.assertTrue(notes)

    def test_a_figure_must_travel_with_its_subject(self):
        bad = "Legora raised $550M, and an investor's post claimed $21M in savings for a contracting tool."
        self.assertEqual(c.check_header(bad, BODY)[0], "")
        good = "Legora raised $550M, and investor Keith Rabois posted that Quillery saves a client $21M."
        self.assertEqual(c.check_header(good, BODY)[0], good)

    def test_not_disclosed_claims_are_checked(self):
        self.assertEqual(c.check_header("Legora raised $550M with no disclosed ARR.", BODY)[0], "")
        ok = "Legora raised $550M with no disclosed margin or retention."
        self.assertEqual(c.check_header(ok, BODY)[0], ok)

    def test_figures_not_in_the_body_are_dropped(self):
        self.assertEqual(c.check_header("Harvey is worth $99B.", BODY)[0], "")

    def test_spoken_figures(self):
        self.assertIn("$21M", c.spoken_figures("saving twenty-one million dollars"))
        self.assertIn("$8.8B", c.spoken_figures("eight point eight billion dollars"))


class Roles(unittest.TestCase):
    def test_unsourced_role_claims_become_neutral(self):
        src = "Keith Rabois on X: Quillery is saving a Fortune 100 company $21M in outside counsel legal fees"
        txt, note = c.check_roles("Quillery founder promoting his own product", src)
        self.assertEqual(txt, c.NEUTRAL_AGENDA)
        self.assertIn("founder", note)
        self.assertEqual(c.check_roles("Quillery CEO Jordan Blake promoting his product",
                                       "Quillery CEO Jordan Blake said")[1], "")
        self.assertEqual(c.check_roles("A company announcing its own product", "x")[0],
                         "A company announcing its own product")


class HandCorrections(unittest.TestCase):
    def test_a_hand_edited_deep_dive_needs_a_correction(self):
        root = Path(tempfile.mkdtemp())
        for p, t in (("briefings/2026-10-23.md", "# b\n"), ("briefings/deepdives/2026-10-23.md", "# dd\nwrong\n")):
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_text(t)
        live = root / ".publish"
        for f in ("2026-10-23/index.html", "index.html", "feed.xml", "podcast.xml"):
            (live / f).parent.mkdir(parents=True, exist_ok=True)
            (live / f).write_text("x")
        shipped.record(root, "2026-10-23", live=live)
        (root / "briefings/deepdives/2026-10-23.md").write_text("# dd\nright\n")
        bad = shipped.guard(root, live, live, 30)
        self.assertTrue(any("deep dive changed" in b for b in bad))
        shipped.correct(root, "2026-10-23", "Fixed the attribution of the $21M claim")
        self.assertEqual(shipped.guard(root, live, live, 30), [])
        self.assertEqual(shipped.corrections(root, "2026-10-23")[0]["note"], "Fixed the attribution of the $21M claim")


BRIEF = """# AI Briefing · Friday

**The day in brief.** Legal AI keeps pricing ahead of metrics: Corvane at $8.8B, plus a $21M savings claim with no method. Quillery's tools spread.

## Top of mind

- **Corvane's price jumps.** Corvane raised $550M at $8.8B, with no ARR disclosed. [1](https://example.com/a)
- **A savings claim.** Jordan Blake posted that Quillery saves a client $21M. The post gives no method. [2](https://example.com/b)
- **Dunmore doubles.** A $1.5B round at $6.2B funds new chips. [3](https://example.com/c)
- **Rivet's $9B surprise.** It came from nowhere. [4](https://example.com/d)

## Must read

### 1. Corvane raises $550M at $8.8B
- **What happened:** Corvane raised $550M at an $8.8B valuation on self-reported ARR above $200M.
- **Our read:** Does Corvane disclose gross margin? It lacks retention data.

### 2. Investor says Quillery saves a client $21M
- **What happened:** Jordan Blake posted that Quillery is saving a Fortune 100 company $21M, with no method.

### 3. Dunmore raises $1.5B at $6.2B
- **What happened:** Dunmore's Series E of $1.5B values it at $6.2B.
"""


from pipeline import consistency  # noqa: E402


class Briefing(unittest.TestCase):
    def setUp(self):
        self.md, self.notes = consistency.check_briefing(BRIEF)

    def test_misattributed_figure_in_day_in_brief_is_dropped(self):
        self.assertNotIn("$21M savings claim", self.md)
        self.assertIn("Quillery's tools spread.", self.md)

    def test_not_disclosed_contradicted_by_the_body_is_dropped(self):
        self.assertNotIn("no ARR disclosed", self.md)
        self.assertNotIn("Corvane's price jumps", self.md)          # its only sentence was the false claim
        self.assertTrue(any("ARR wasn't disclosed" in n for n in self.notes))

    def test_figure_tied_through_the_bullet_lead_stays(self):
        self.assertIn("A $1.5B round at $6.2B funds new chips.", self.md)
        self.assertIn("saves a client $21M", self.md)

    def test_bullet_whose_lead_fails_goes_whole(self):
        self.assertNotIn("Rivet", self.md)
        self.assertNotIn("It came from nowhere", self.md)
        self.assertIn("[2](https://example.com/b)", self.md)

    def test_questions_and_negations_do_not_count_as_disclosure(self):
        md, notes = consistency.check_briefing(BRIEF.replace("with no ARR disclosed", "with no margin or retention disclosed"))
        self.assertIn("no margin or retention disclosed", md)

    def test_figure_only_in_sources_needs_the_same_names(self):
        md = BRIEF.replace("A $1.5B round at $6.2B funds new chips.", "Dunmore also books $40M in orders.")
        kept, _ = consistency.check_briefing(md, "Dunmore said it has $40M in orders.")
        self.assertIn("$40M in orders", kept)
        gone, _ = consistency.check_briefing(md, "Halberd said it has $40M in orders.")
        self.assertNotIn("$40M in orders", gone)


class CrossDay(unittest.TestCase):
    def test_flags_not_disclosed_against_an_earlier_day(self):
        today = "- **Our read:** Corvane's price comes with no disclosed revenue."
        flags = consistency.cross_day(today, {"2026-10-14": "- Corvane's ARR reached $70B, the FT found."})
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["earlier_day"], "2026-10-14")

    def test_other_companies_do_not_count(self):
        today = "- Corvane comes with no disclosed revenue."
        self.assertEqual(consistency.cross_day(today, {"2026-10-14": "- Halberd's ARR reached $70B."}), [])


if __name__ == "__main__":
    unittest.main()
