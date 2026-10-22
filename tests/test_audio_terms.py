"""The script check stops invented names, not common technical terms or plurals of words in the section."""
import unittest

from pipeline.audio import invented


class Terms(unittest.TestCase):
    def test_generic_terms_and_plurals_pass(self):
        self.assertEqual(invented("Nvidia sold more GPU capacity to Anthropic.",
                                  "Nvidia sold more GPUs and AI chips to Anthropic; the CEO says demand holds."), "")

    def test_invented_names_still_caught(self):
        self.assertIn("Microsoft", invented("Nvidia sold more GPU capacity.", "Nvidia sold capacity to Microsoft."))


if __name__ == "__main__":
    unittest.main()
