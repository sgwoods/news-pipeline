"""Mail-script deploys via clasp (pipeline/clasp.py) and the v0.2.8 takes jobs."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import clasp, presence, runner, takes

CFG = {"email": {"script_url": "https://script.google.com/macros/s/AKfycbTESTDEPLOYMENTID1234567890/exec"}}
SID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abc"


class Clasp(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "scripts" / "apps-script").mkdir(parents=True)
        (self.root / "scripts" / "apps-script" / "Code.gs").write_text("function doGet() {}\n", "utf-8")

    def test_deployment_id_from_the_web_app_url(self):
        self.assertEqual(clasp.deployment_id(CFG), "AKfycbTESTDEPLOYMENTID1234567890")

    def test_setup_checks_the_script_id(self):
        with self.assertRaises(clasp.ClaspError):
            clasp.setup(self.root, "not an id")
        clasp.setup(self.root, SID)
        self.assertEqual(clasp.script_id(self.root), SID)

    def test_deploy_needs_a_person(self):
        clasp.setup(self.root, SID)
        with mock.patch("sys.stdin") as s:
            s.isatty.return_value = False
            with self.assertRaises(clasp.ClaspError):
                clasp.deploy(self.root, CFG, "v0.2.8-beta")

    def test_deploy_pushes_only_code_and_updates_the_same_deployment(self):
        clasp.setup(self.root, SID)
        calls = []

        def fake(args, cwd, timeout=180):
            calls.append(args)
            if args == ["pull"]:
                (cwd / "appsscript.json").write_text("{}", "utf-8")
                (cwd / "Code.js").write_text("old", "utf-8")
            if args == ["push", "-f"]:
                self.assertEqual((cwd / "Code.js").read_text("utf-8"), "function doGet() {}\n")
                self.assertIn("!Code.js", (cwd / ".claspignore").read_text("utf-8"))
                self.assertEqual(json.loads((cwd / ".clasp.json").read_text("utf-8"))["scriptId"], SID)
            return subprocess.CompletedProcess(args, 0, "", "")
        with mock.patch.object(clasp, "_clasp", side_effect=fake), presence.granted("job"), \
                mock.patch("sys.stdin") as s:
            s.isatty.return_value = False
            out = clasp.deploy(self.root, CFG, "v0.2.8-beta")
        self.assertEqual(calls[0], ["pull"])
        self.assertEqual(calls[1], ["push", "-f"])
        self.assertEqual(calls[2][:3], ["deploy", "--deploymentId", "AKfycbTESTDEPLOYMENTID1234567890"])
        self.assertIn("same URL", out)
        self.assertTrue((self.root / clasp.LOG).exists())
        self.assertFalse((self.root / clasp.BUILD).exists())

    def test_status_compares_live_and_repo(self):
        clasp.setup(self.root, SID)
        with mock.patch("shutil.which", return_value="/usr/local/bin/clasp"), \
                mock.patch.object(Path, "exists", lambda p: True if p.name == ".clasprc.json" else Path.is_file(p) or Path.is_dir(p)), \
                mock.patch.object(clasp, "live_code", return_value="function doGet() {}  \n"):
            self.assertTrue(clasp.status(self.root, CFG)["matches"])
        with mock.patch("shutil.which", return_value="/usr/local/bin/clasp"), \
                mock.patch.object(Path, "exists", lambda p: True if p.name == ".clasprc.json" else Path.is_file(p) or Path.is_dir(p)), \
                mock.patch.object(clasp, "live_code", return_value="old"):
            self.assertFalse(clasp.status(self.root, CFG)["matches"])


class Jobs(unittest.TestCase):
    def test_recipes(self):
        self.assertEqual(runner.recipe_problems(), [])
        self.assertEqual(runner.RECIPES["deploy-mailer"]["tier"], "mac")
        self.assertEqual(runner.RECIPES["takes-test"]["tier"], "auto")
        self.assertEqual(runner.RECIPES["takes-check"]["tier"], "auto")
        self.assertEqual(runner.RECIPES["takes-apply"]["tier"], "chat")
        with self.assertRaises(runner.JobError):
            runner.validate({"id": "a", "recipe": "takes-apply", "args": {"day": "2026-10-25"}})   # needs Steven's yes

    def test_check_merges_without_saving(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(takes, "fetch_all", return_value=[{"received": "1", "takes": {"1": "Site take."}, "via": "site"},
                                                                 {"received": "2", "takes": {}, "done": True}]), \
                mock.patch.object(takes, "slack_takes", return_value={}), mock.patch.object(takes, "slots", return_value=[]), \
                mock.patch("pipeline.stages.private_names", return_value=[]):
            r = takes.check(root, {}, "2026-10-25")
        self.assertEqual(r["takes"][0]["from"], "site")
        self.assertTrue(r["done"])
        self.assertFalse((root / "data").exists())

    def test_site_script_handles_a_changed_hash_and_the_email_link_is_fresh(self):
        from pipeline import site
        self.assertIn('addEventListener("hashchange", start)', site.TAKES_JS)
        src = Path(takes.__file__).read_text("utf-8")
        self.assertIn("?action=review&d={day}&t={TOKEN_MARK}", src)       # private review page (2026-10-26)


if __name__ == "__main__":
    unittest.main()
