import os
import unittest

from pipeline import llm


class ClaudeIsolation(unittest.TestCase):
    def setUp(self):
        llm.ClaudeCode._help = "--strict-mcp-config --mcp-config --tools --allowedTools --disallowedTools"

    def tearDown(self):
        llm.ClaudeCode._help = None

    def test_no_tools_no_mcp(self):
        a = llm.ClaudeCode({}).build_args("sys")
        self.assertEqual(a[a.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", a)
        self.assertEqual(a[a.index("--mcp-config") + 1], '{"mcpServers": {}}')
        dis = a[a.index("--disallowedTools") + 1].split(",")
        for t in ("Bash", "Read", "WebFetch", "WebSearch", "Agent", "Task", "mcp__*"):
            self.assertIn(t, dis)
        self.assertNotIn("--allowedTools", a)

    def test_web_stage_gets_only_search_and_fetch(self):
        c = llm.ClaudeCode({})
        c.web = True
        a = c.build_args("sys")
        self.assertEqual(a[a.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertEqual(a[a.index("--allowedTools") + 1], "WebSearch,WebFetch")
        self.assertIn("Bash", a[a.index("--disallowedTools") + 1])

    def test_secrets_never_reach_the_cli(self):
        os.environ["GMAIL_APP_PASSWORD"] = "abcdabcdabcdabcd"
        os.environ["SLACK_USER_TOKEN"] = "xoxp-1"
        try:
            env = llm.ClaudeCode.safe_env()
            self.assertNotIn("GMAIL_APP_PASSWORD", env)
            self.assertNotIn("SLACK_USER_TOKEN", env)
            self.assertIn("PATH", env)
        finally:
            del os.environ["GMAIL_APP_PASSWORD"], os.environ["SLACK_USER_TOKEN"]


if __name__ == "__main__":
    unittest.main()
