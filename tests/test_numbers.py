"""Number check: stated differences and changes must add up; one thing must not get two near-identical figures."""
import unittest

from pipeline import numbers


class Numbers(unittest.TestCase):
    def test_wrong_difference(self):
        iss = numbers.check("Team A scores 61.8% at $155 cost, vs. all-Sol's 63.2% at $510 ($70 cheaper).")
        self.assertTrue(any("$355" in i for i in iss))
        self.assertEqual(numbers.check("A costs $155 vs B at $510 ($355 cheaper)."), [])

    def test_wrong_change_percent(self):
        self.assertTrue(numbers.check("Revenue rose from $11.5B to $16.8B (up 20%)."))
        self.assertEqual(numbers.check("Revenue rose from $11.5B to $16.8B (up 46%)."), [])

    def test_near_twins_but_not_different_metrics(self):
        md = "- Astra costs $3.26 per task.\n- Later: pricier than Astra (~$3.32).\n"
        self.assertTrue(any("Astra" in i for i in numbers.check(md)))
        md2 = "- Anthropic's Q3 revenue was $16.8B.\n- Anthropic's Q2 revenue was $11.5B.\n"
        self.assertEqual(numbers.check(md2), [])


class Fix(unittest.TestCase):
    def test_difference_is_corrected(self):
        md, fixes = numbers.fix("At $155 cost, vs. all-Sol at $510 ($70 cheaper; 1.4-point drop).")
        self.assertIn("($355 cheaper;", md)
        self.assertEqual(numbers.check(md), [])
        self.assertEqual(numbers.fix("A at $155 vs B at $510 ($355 cheaper).")[1], [])


if __name__ == "__main__":
    unittest.main()
