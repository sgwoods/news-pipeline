import unittest

from pipeline import publish

CFG = {"publish": {"site_url": "https://example.github.io/ai-briefing/"}}


class R:
    def __init__(self, code, text):
        self.status_code, self.text = code, text


class Client:
    def __init__(self, answers):
        self.answers, self.urls = list(answers), []

    def get(self, url):
        self.urls.append(url)
        return self.answers.pop(0) if self.answers else R(200, "2099-01-01")


class WaitLive(unittest.TestCase):
    def test_waits_until_the_new_page_is_served(self):
        c = Client([R(404, ""), R(200, "old page 2099-01-00"), R(200, "<h1>2099-01-01</h1>")])
        slept = []
        ok = publish.wait_live(CFG, "2099-01-01", timeout=60, every=10, log=lambda *a: None, client=c,
                               sleep=slept.append)
        self.assertTrue(ok)
        self.assertEqual(len(slept), 2)
        self.assertTrue(c.urls[0].startswith("https://example.github.io/ai-briefing/2099-01-01/index.html?v="))

    def test_gives_up_after_the_timeout(self):
        c = Client([R(404, "")] * 20)
        c.get = lambda url: R(404, "")
        self.assertFalse(publish.wait_live(CFG, "2099-01-01", timeout=30, every=10, log=lambda *a: None, client=c,
                                           sleep=lambda s: None))

    def test_no_site_configured_is_a_no_op(self):
        self.assertTrue(publish.wait_live({}, "2099-01-01", log=lambda *a: None))


if __name__ == "__main__":
    unittest.main()
