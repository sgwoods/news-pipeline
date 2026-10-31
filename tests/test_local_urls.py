import unittest
from pipeline.scrub import local_urls


class LocalUrlTest(unittest.TestCase):
    def test_rewritten(self):
        t = "an instance may be http://127.0.0.1:8787/?x={handle}&l=20; or http://localhost:5000/feed."
        out = local_urls(t)
        self.assertNotIn("127.0.0.1", out)
        self.assertNotIn("localhost", out)
        self.assertIn("a local address on the Mac", out)

    def test_public_kept(self):
        self.assertEqual(local_urls("see https://x.com/karpathy"), "see https://x.com/karpathy")


if __name__ == "__main__":
    unittest.main()
