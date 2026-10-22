"""Speech layer, script checks, quote verification and the privacy scrub (no models, no network)."""
import unittest

from pipeline import audio, speech, stages


class TestSpeech(unittest.TestCase):
    def test_money_units_percent(self):
        self.assertEqual(speech.expand("a $5B loan"), "a five billion dollar loan")
        self.assertIn("one point three billion dollars of it", speech.expand("only $1.3B of it"))
        self.assertIn("twenty billion dollars", speech.expand("cut by $20B."))
        self.assertIn("seventy-two cents", speech.expand("costs $0.72 per task"))
        self.assertIn("ninety to ninety-nine percent", speech.expand("a 90–99% cut"))
        self.assertIn("five hundred megawatts of", speech.expand("500 MW of capacity"))
        self.assertIn("eight gigawatt campus", speech.expand("an 8 GW campus"))
        self.assertIn("fifty times", speech.expand("a 50x multiple"))
        self.assertIn("fifty-three.", speech.expand("versus 53."))
        self.assertIn("twenty twenty-seven", speech.expand("an IPO in 2027"))

    def test_pronounce_does_not_touch_other_words(self):
        tab = {"Andrew Ng": "Andrew Eng", "GPT": "G P T"}
        out = speech.spoken("Andrew Ng on GPT-6.1 and Ngozi", tab)
        self.assertIn("Andrew Eng", out)
        self.assertIn("G P T six point one", out)
        self.assertIn("Ngozi", out)


class TestScriptChecks(unittest.TestCase):
    def test_spelled_and_invented_and_quotes(self):
        src = 'What happened: Marcus claims OpenAI cut its forecast by $20B and called it "a WeWork moment".'
        self.assertTrue(audio.spelled_figures("a cut of two billion dollars"))
        self.assertEqual(audio.spelled_figures("the first of six stories"), "")
        self.assertTrue(audio.invented(src, "OpenAI cut its forecast by $2B."))
        self.assertEqual(audio.unquoted(src, 'He called it "a WeWork moment".'), "")
        self.assertTrue(audio.unquoted(src, 'He called it "a disaster".'))

    def test_opener_is_fixed(self):
        self.assertEqual(audio.opener("AI Briefing · Tuesday, October 13, 2026"),
                         "This is the AI Briefing for Tuesday, October 13. It is written and read by AI, from public sources.")


class TestQuotesAndPrivacy(unittest.TestCase):
    def test_verify_quotes(self):
        md, removed = stages.verify_quotes('He credits "brute force and stamina" and "made up words".',
                                           ["credits brute force and stamina, he says"])
        self.assertIn('"brute force and stamina"', md)
        self.assertNotIn('"made up words"', md)
        self.assertEqual(removed, ["made up words"])

    def test_scrub_keeps_other_people_with_same_first_name(self):
        names = ["Priya Natarajan", "Lee Moreau", "Chris Halvorsen"]
        out, _ = stages.scrub_private("Ali Ghodsi and Ray Dalio spoke. Ask Chris Halvorsen.", names)
        self.assertIn("Ali Ghodsi", out)
        self.assertIn("Ray Dalio", out)
        self.assertNotIn("Todd", out)

    def test_scrub_allows_published_sources(self):
        names = ["Priya Natarajan"]
        out, hits = stages.scrub_private("Priya Natarajan wrote that Lattice Lab shipped.", names, ["Priya Natarajan"])
        self.assertIn("Priya Natarajan", out)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
