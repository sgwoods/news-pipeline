import unittest
from pipeline import deepdive


class TechnicalTest(unittest.TestCase):
    def test_brief_only_for_technical(self):
        self.assertIn("investors and business people", deepdive.angle_for({"kind": "technical", "angle": "A."}))
        self.assertEqual(deepdive.angle_for({"kind": "controversy", "angle": "A."}), "A.")

    def test_themes_default_and_override(self):
        self.assertIn("world models", deepdive.dcfg({})["technical_themes"])
        self.assertEqual(deepdive.dcfg({"deepdive": {"technical_themes": ["x"]}})["technical_themes"], ["x"])

    def test_pick_prompt_has_themes_slot(self):
        from pipeline import stages
        t, _ = stages.prompt("deepdive_pick")
        self.assertIn("{{themes}}", t)
        self.assertIn("technical |", t)


if __name__ == "__main__":
    unittest.main()
