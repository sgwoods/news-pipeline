import unittest

from pipeline import stages


def it(i, url, text="A real paragraph with enough words to count as content here.", title="T"):
    return {"id": f"id{i}", "url": url, "text": text, "title": title}


class TestPrefilter(unittest.TestCase):
    def test_canonical_url(self):
        self.assertEqual(stages.canonical_url("https://corvane.com/de/blog/x"), "https://corvane.com/blog/x")
        self.assertEqual(stages.canonical_url("https://corvane.com/pt-br/blog/x"), "https://corvane.com/blog/x")
        self.assertEqual(stages.canonical_url("https://x.com/ai/blog/x"), "https://x.com/ai/blog/x")  # not a locale

    def test_translated_duplicates_keep_one(self):
        items = [it(1, "https://c.com/de/blog/n"), it(2, "https://c.com/fr/blog/n"), it(3, "https://c.com/blog/other")]
        rest, d = stages.prefilter(items, known_urls=set())
        self.assertEqual([x["id"] for x in rest], ["id1", "id3"])
        self.assertIn("translated duplicate", d["id2"]["reason"])

    def test_translated_duplicates_when_original_archived(self):
        items = [it(1, "https://c.com/de/blog/n")]
        rest, d = stages.prefilter(items, known_urls={"https://c.com/blog/n"})
        self.assertEqual(rest, [])
        self.assertFalse(d["id1"]["keep"])

    def test_original_preferred_over_translation(self):
        items = [it(1, "https://c.com/de/blog/n"), it(2, "https://c.com/blog/n")]
        rest, d = stages.prefilter(items, known_urls={"https://c.com/blog/n", "https://c.com/de/blog/n"})
        self.assertEqual([x["id"] for x in rest], ["id2"])

    def test_embed_only_dropped_without_llm(self):
        items = [it(1, "https://bsky.app/p/1", text="[contains quote post or other embedded content]", title="[contains quote post or other embedded content]")]
        rest, d = stages.prefilter(items, set(), min_chars=25)
        self.assertEqual(rest, [])
        self.assertIn("no substantive content", d["id1"]["reason"])

    def test_unverified_quotes(self):
        item = {"title": "", "text": "Revenue grew to $2B, he said, calling it “a step change for us”."}
        self.assertEqual(stages.unverified_quotes('He called it "a step change for us".', item), [])
        self.assertEqual(stages.unverified_quotes("He said 'the AI industry is in a bubble'.", item),
                         ["the AI industry is in a bubble"])


if __name__ == "__main__":
    unittest.main()
