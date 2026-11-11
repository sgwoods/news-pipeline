"""Auto-add dedupe (pipeline/mailsource.py, 2026-11-09): a new sender of a newsletter we already list is merged into
it instead of becoming a duplicate source; hand-edited newsletters.yaml is never written."""
import tempfile
import unittest
from pathlib import Path

from pipeline import mailsource as m

HAND = [{"name": "Lenny's Newsletter", "from": ["lenny@substack.com"], "web": "https://www.lennysnewsletter.com/"},
        {"name": "Simple AI (Dharmesh Shah)", "from": ["dharmesh@simple.ai"], "web": "https://simple.ai/"},
        {"name": "Dwarkesh Patel", "from": [], "web": "https://www.dwarkesh.com/"},
        {"name": "Import AI", "from": ["importai@substack.com"], "web": "https://importai.substack.com/"}]


class MergeTarget(unittest.TestCase):
    def test_plus_address_root(self):
        self.assertEqual(m.merge_target("lenny+how-i-ai@substack.com", "How I AI", HAND), "Lenny's Newsletter")

    def test_own_domain(self):
        self.assertEqual(m.merge_target("agentai@mail.simple.ai", "Agent AI", HAND), "Simple AI (Dharmesh Shah)")
        self.assertEqual(m.merge_target("newsletter@dwarkesh.com", "Dwarkesh Podcast", HAND), "Dwarkesh Patel")   # via web

    def test_shared_platform_domain_does_not_merge(self):
        self.assertIsNone(m.merge_target("someone-else@substack.com", "Someone Else", HAND))
        self.assertIsNone(m.merge_target("x@mail.beehiiv.com", "The X Letter", HAND))

    def test_display_name(self):
        self.assertEqual(m.merge_target("news@othermail.example", "Import AI", HAND), "Import AI")
        self.assertEqual(m.merge_target("news@othermail.example", "Lenny's Newsletter (Lenny Rachitsky)", HAND), "Lenny's Newsletter")
        self.assertIsNone(m.merge_target("news@othermail.example", "AI", HAND))                     # too short to trust


class AutoAddMerges(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "newsletters.yaml").write_text(
            "- name: Lenny's Newsletter\n  from: [lenny@substack.com]\n  web: https://www.lennysnewsletter.com/\n"
            "- name: Simple AI (Dharmesh Shah)\n  from: [dharmesh@simple.ai]\n  web: https://simple.ai/\n", "utf-8")
        self.cfg = {"forwarders": [], "account": "you+briefing@example.com"}

    def test_merges_instead_of_duplicating(self):
        e = m.auto_add(self.root, "lenny+the-skip@substack.com", "The Skip", "Issue 1", "2026-11-09", self.cfg)
        self.assertTrue(e and e.get("merged"))
        self.assertEqual(e["merge_into"], "Lenny's Newsletter")
        nl = {n["name"]: n for n in m.load_newsletters(self.root)}
        self.assertNotIn("The Skip", nl)
        self.assertIn("lenny+the-skip@substack.com", nl["Lenny's Newsletter"]["from"])
        self.assertEqual(m.match_sender("lenny+the-skip@substack.com", list(nl.values()))["name"], "Lenny's Newsletter")
        # a second sender of the same newsletter joins the same merge entry
        m.auto_add(self.root, "lenny+growth@substack.com", "Growth", "Issue 2", "2026-11-09", self.cfg)
        autos = m._load_auto(self.root)
        self.assertEqual(len(autos), 1)
        self.assertEqual(sorted(autos[0]["from"]), ["lenny+growth@substack.com", "lenny+the-skip@substack.com"])
        # newsletters.yaml itself is untouched
        self.assertNotIn("the-skip", (self.root / "newsletters.yaml").read_text("utf-8"))

    def test_unrelated_sender_still_added(self):
        e = m.auto_add(self.root, "letter@newpub.example", "New Pub", "Hello", "2026-11-09", self.cfg)
        self.assertFalse(e.get("merged"))
        self.assertEqual(e["name"], "New Pub")
        self.assertIn("AUTO-ADDED", e["flags"])
        self.assertEqual(m.proposed_merges(self.root), [])

    def test_proposed_merges_dry_run(self):
        m.auto_add(self.root, "letter@newpub.example", "New Pub", "Hello", "2026-11-09", self.cfg)
        autos = m._load_auto(self.root)
        autos.append({"name": "Agent AI", "from": ["agentai@mail.simple.ai"], "web": ""})      # an old duplicate
        m._save_auto(self.root, autos)
        self.assertEqual(m.proposed_merges(self.root), [("Agent AI", "agentai@mail.simple.ai", "Simple AI (Dharmesh Shah)")])


if __name__ == "__main__":
    unittest.main()
