import unittest
from pathlib import Path

from pipeline import service


class TestService(unittest.TestCase):
    def test_daily_plist(self):
        p = service.build_plist("daily", Path("/Users/x/news-pipeline"), {"schedule": {"times": ["06:30", "07:30"]}})
        self.assertEqual(p["ProgramArguments"], ["/bin/bash", "/Users/x/news-pipeline/np", "scheduled", "daily"])  # v0.1.5: half-hour tick, local clock decides
        self.assertEqual(p["StartCalendarInterval"], [{"Minute": 0}, {"Minute": 30}])
        self.assertFalse(p["RunAtLoad"])
        self.assertIn("/opt/homebrew/bin", p["EnvironmentVariables"]["PATH"])

    def test_dashboard_plist_stays_alive(self):
        p = service.build_plist("dashboard", Path("/r"), {})
        self.assertTrue(p["KeepAlive"])
        self.assertTrue(p["RunAtLoad"])
        self.assertEqual(p["ProgramArguments"][-1], "dash")
        self.assertEqual(p["Label"], "com.sgwoods.news-pipeline.dashboard")


if __name__ == "__main__":
    unittest.main()
