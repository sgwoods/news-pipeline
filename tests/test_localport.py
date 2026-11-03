"""Shared localhost agreement (2026-11-02): the dashboard stays in 8770-8779, never stops another project's server,
and replaces its own older copy. Uses throwaway servers in subprocesses and a temp HOME for the state files."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from pipeline import localport as lp

ROOT = Path(__file__).resolve().parents[1]
NEEDS_CONFIG = unittest.skipUnless((ROOT / "config.yaml").exists(), "needs a checkout with config.yaml (not the public export)")

SERVER = r"""
import http.server, json, os, sys
project, port = sys.argv[1], int(sys.argv[2])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if project == "-" or self.path != "/whoami":
            self.send_response(404); self.end_headers(); return
        b = json.dumps({"project": project, "port": port, "pid": os.getpid(), "version": "test"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def free_in_block(skip=()):
    for p in lp.block():
        if p not in skip and lp.free(p):
            return p
    raise unittest.SkipTest("no free port in 8770-8779 on this machine")


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        os.environ["NP_PORTS_HOME"] = str(self.home)
        self.procs = []

    def tearDown(self):
        os.environ.pop("NP_PORTS_HOME", None)
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(5)

    def serve(self, project, port):
        p = subprocess.Popen([sys.executable, "-c", SERVER, project, str(port)])
        self.procs.append(p)
        end = time.time() + 10
        while time.time() < end and lp.free(port):
            time.sleep(0.05)
        self.assertFalse(lp.free(port), "test server did not start")
        return p


class NeverOutsideBlock(Base):
    def test_default_first_then_block_only(self):
        self.assertEqual(lp.block()[0], 8775)
        self.assertEqual(sorted(lp.block()), list(range(8770, 8780)))
        port = lp.choose()
        self.assertTrue(8770 <= port <= 8779)

    def test_busy_default_moves_within_block(self):
        busy = free_in_block()
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # an earlier test's TIME_WAIT on macOS
            s.bind(("127.0.0.1", busy)); s.listen()
            port = lp.choose(busy)
            self.assertNotEqual(port, busy)
            self.assertTrue(8770 <= port <= 8779)

    def test_outside_preference_is_ignored(self):
        port = lp.choose(8765)                               # virtual-bookshelf's default
        self.assertTrue(8770 <= port <= 8779)

    def test_whole_block_busy_stops_with_names(self):
        orig, orig_holder = lp.free, lp.holder
        lp.free = lambda p: False
        lp.holder = lambda p: f"pid 1 fake{p}"
        try:
            with self.assertRaises(lp.PortsBusy) as cm:
                lp.choose()
            self.assertIn("8770-8779", str(cm.exception))
            self.assertIn("fake8779", str(cm.exception))
        finally:
            lp.free, lp.holder = orig, orig_holder

    @NEEDS_CONFIG
    def test_main_never_binds_outside_block(self):
        from dashboard import app as dapp
        seen = {}
        orig_run = dapp.Flask.run
        dapp.Flask.run = lambda self, host=None, port=None, **k: seen.update(host=host, port=port)
        try:
            dapp.main(port=8765)
        finally:
            dapp.Flask.run = orig_run
            lp.clear_state()
        self.assertEqual(seen["host"], "127.0.0.1")
        self.assertTrue(8770 <= seen["port"] <= 8779)


class NeverStopsOthers(Base):
    def test_other_project_left_alone(self):
        port = free_in_block()
        p = self.serve("aurora", port)
        lp.write_state(port, pid=p.pid)                      # even if our file (wrongly) names it
        self.assertIsNone(lp.replace_old(log=lambda *a: None, grace=0.5))
        time.sleep(0.3)
        self.assertIsNone(p.poll(), "another project's server was stopped")

    def test_no_whoami_left_alone(self):
        port = free_in_block()
        p = self.serve("-", port)                            # answers HTTP, but not /whoami
        lp.write_state(port, pid=p.pid)
        self.assertIsNone(lp.replace_old(log=lambda *a: None, grace=0.5))
        time.sleep(0.3)
        self.assertIsNone(p.poll(), "a server without /whoami was stopped")

    def test_pid_mismatch_left_alone(self):
        port = free_in_block()
        self.serve(lp.PROJECT, port)                         # our project answers, but with a different pid
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.procs.append(other)
        lp.write_state(port, pid=other.pid)
        self.assertIsNone(lp.replace_old(log=lambda *a: None, grace=0.5))
        self.assertIsNone(other.poll())


class ReplacesOwnCopy(Base):
    def test_older_copy_replaced_and_port_reused(self):
        port = free_in_block()
        p = self.serve(lp.PROJECT, port)
        lp.write_state(port, pid=p.pid)
        freed = lp.replace_old(log=lambda *a: None, grace=3)
        self.assertEqual(freed, port)
        p.wait(5)
        self.assertIsNotNone(p.poll())
        self.assertTrue(lp.free(port))
        self.assertEqual(lp.choose(freed), port)

    def test_stale_file_is_harmless(self):
        lp.write_state(8775, pid=2 ** 22 + 12345)            # no such process
        self.assertIsNone(lp.replace_old(log=lambda *a: None))

    def test_state_written_and_cleared_only_by_owner(self):
        lp.write_state(8776)
        self.assertEqual(lp.read_state()["pid"], os.getpid())
        lp.clear_state(pid=os.getpid() + 1)                  # someone else's exit: file stays
        self.assertTrue(lp.state_path().exists())
        lp.clear_state()
        self.assertFalse(lp.state_path().exists())


class Registry(Base):
    def test_created_with_header_and_our_line(self):
        lp.ensure_registry("/repo", log=lambda *a: None)
        lines = lp.registry_path().read_text("utf-8").splitlines()
        self.assertEqual(lines[0], lp.HEADER)
        self.assertIn("news-pipeline\t8770-8779\t8775\t/repo", lines)

    def test_other_lines_untouched_and_overlap_warned(self):
        p = lp.registry_path()
        p.parent.mkdir(parents=True)
        before = "# name\tports\tdefault\trepo\nvirtual-bookshelf\t8760-8769\t8765\t~/b\nrogue\t8778-8781\t8780\t~/r"
        p.write_text(before, "utf-8")
        warns = lp.ensure_registry("/repo", log=lambda *a: None)
        after = p.read_text("utf-8")
        self.assertTrue(after.startswith(before))
        self.assertEqual(after.count("news-pipeline\t"), 1)
        self.assertEqual(len(warns), 1)
        self.assertIn("rogue", warns[0])
        lp.ensure_registry("/repo", log=lambda *a: None)     # idempotent
        self.assertEqual(p.read_text("utf-8"), after)

    def test_status_reports_running_projects(self):
        port = free_in_block()
        self.serve(lp.PROJECT, port)
        lp.ensure_registry("/repo", log=lambda *a: None)
        out = []
        found = lp.status(out=out.append)
        self.assertTrue(any(f["port"] == port for f in found))
        self.assertTrue(any(f"running on {port}" in ln for ln in out))


@NEEDS_CONFIG
class PagesSayWhichProject(unittest.TestCase):
    def test_whoami_and_title(self):
        from dashboard.app import create_app
        root = Path(__file__).resolve().parents[1]
        c = create_app(root).test_client()
        w = c.get("/whoami", headers={"Host": "127.0.0.1:8775"}).get_json()
        self.assertEqual(w["project"], "news-pipeline")
        self.assertEqual(w["pid"], os.getpid())
        self.assertEqual(w["port"], 8775)
        self.assertTrue(w["version"])
        h = c.get("/status", headers={"Host": "127.0.0.1:8775"}).data.decode()
        self.assertIn("<title>News · 8775 ·", h)
        self.assertIn('rel="icon"', h)
        self.assertIn("News · :8775", h)


if __name__ == "__main__":
    unittest.main()
