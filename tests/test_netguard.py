import unittest

from pipeline import netguard


class NetGuard(unittest.TestCase):
    def test_private_targets_refused(self):
        for u in ("http://127.0.0.1:8765/api/x", "http://localhost/", "http://192.168.1.1/admin", "http://10.0.0.5",
                  "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://printer.local/", "file:///etc/passwd",
                  "ftp://example.com/x", "http://0.0.0.0/"):
            self.assertFalse(netguard.is_public_url(u), u)
            with self.assertRaises(netguard.BlockedURL):
                netguard.check(u)

    def test_public_ip_literal_allowed(self):
        self.assertTrue(netguard.is_public_url("https://1.1.1.1/"))


if __name__ == "__main__":
    unittest.main()
