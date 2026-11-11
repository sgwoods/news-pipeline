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

    def _gh(self, statuses, posts):
        """A fake gh: builds/latest answers from `statuses` in turn; POST .../builds is recorded in `posts`."""
        import json
        class P:
            def __init__(self, code, out=""):
                self.returncode, self.stdout, self.stderr = code, out, ""
        def run(args, **kw):
            if "-X" in args:
                posts.append(args[-1])
                return P(0, "{}")
            st = statuses.pop(0) if statuses else "built"
            return P(0, json.dumps({"status": st, "error": {"message": "Page build failed."} if st == "errored" else None,
                                    "commit": "9234e182"}))
        return run

    def test_failed_pages_build_is_rebuilt_once_and_the_wait_restarts(self):
        from unittest import mock
        cfg = {"publish": {"site_url": "https://example.github.io/ai-briefing/", "repo": "o/r"}}
        # 404 for the first 3 polls (timeout), then live after the rebuild
        c = Client([R(404, "")] * 4 + [R(200, "<h1>2099-01-01</h1>")])
        posts, logs = [], []
        with mock.patch("shutil.which", lambda n: "/usr/bin/gh"):
            ok = publish.wait_live(cfg, "2099-01-01", timeout=30, every=10, log=logs.append, client=c,
                                   sleep=lambda s: None, run=self._gh(["errored"], posts))
        self.assertTrue(ok)
        self.assertEqual(posts, ["repos/o/r/pages/builds"])
        self.assertTrue(any("rebuild requested" in l for l in logs))

    def test_still_failing_after_the_rebuild_returns_false(self):
        from unittest import mock
        cfg = {"publish": {"site_url": "https://example.github.io/ai-briefing/", "repo": "o/r"}}
        c = Client([]); c.get = lambda url: R(404, "")
        posts = []
        with mock.patch("shutil.which", lambda n: "/usr/bin/gh"):
            ok = publish.wait_live(cfg, "2099-01-01", timeout=30, every=10, log=lambda *a: None, client=c,
                                   sleep=lambda s: None, run=self._gh(["errored", "errored"], posts))
        self.assertFalse(ok)
        self.assertEqual(len(posts), 1)                                       # one rebuild only

    def test_slow_build_gets_one_more_round(self):
        from unittest import mock
        cfg = {"publish": {"site_url": "https://example.github.io/ai-briefing/", "repo": "o/r"}}
        c = Client([R(404, "")] * 5 + [R(200, "2099-01-01")])
        posts = []
        with mock.patch("shutil.which", lambda n: "/usr/bin/gh"):
            ok = publish.wait_live(cfg, "2099-01-01", timeout=30, every=10, log=lambda *a: None, client=c,
                                   sleep=lambda s: None, run=self._gh(["building"], posts))
        self.assertTrue(ok)
        self.assertEqual(posts, [])

    def test_without_gh_the_old_timeout_holds(self):
        from unittest import mock
        c = Client([]); c.get = lambda url: R(404, "")
        with mock.patch("shutil.which", lambda n: None):
            self.assertFalse(publish.wait_live(CFG, "2099-01-01", timeout=30, every=10, log=lambda *a: None,
                                               client=c, sleep=lambda s: None))

    def test_no_site_configured_is_a_no_op(self):
        self.assertTrue(publish.wait_live({}, "2099-01-01", log=lambda *a: None))


if __name__ == "__main__":
    unittest.main()
