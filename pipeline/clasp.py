"""Deploy the mail script (scripts/apps-script/Code.gs) with Google's clasp CLI instead of copy and paste.

One-time setup on the Mac (by Steven): `npm install -g @google/clasp`, turn on the Apps Script API at
script.google.com/home/usersettings for the mailer's Google account, `clasp login` as that account, then
`./np mailer setup SCRIPT_ID` (Apps Script editor > Project Settings > Script ID). The deployment to update is the
one in email.script_url, so the web app URL never changes.

    ./np mailer status    clasp installed and logged in? does the live script match the repo?
    ./np mailer deploy    push Code.gs and update the deployment (needs Steven: a terminal, or Approve in the run
                          queue's dialog: the deploy-mailer job)

The clasp sign-in (~/.clasprc.json) can change Apps Script projects of that Google account, so deploys are behind
the same approval as releases, and only Code.gs (plus the project's own manifest) is ever pushed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

STATE = "data/state/clasp.json"
LOG = "data/state/mailer-deploys.jsonl"
BUILD = ".clasp-build"
SRC = "scripts/apps-script/Code.gs"
_ID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")


class ClaspError(RuntimeError):
    pass


def deployment_id(cfg: dict) -> str:
    m = re.search(r"/macros/s/([A-Za-z0-9_-]+)/exec", (cfg.get("email") or {}).get("script_url", ""))
    return m.group(1) if m else ""


def script_id(root: Path) -> str:
    try:
        return json.loads((root / STATE).read_text("utf-8")).get("script_id", "")
    except (OSError, ValueError):
        return ""


def setup(root: Path, sid: str) -> str:
    if not _ID.match(sid or ""):
        raise ClaspError("that doesn't look like a script ID (Apps Script editor > Project Settings > Script ID)")
    p = root / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"script_id": sid, "set": dt.datetime.now().isoformat(timespec="seconds")}) + "\n", "utf-8")
    return "script ID saved; next: ./np mailer status"


def _clasp(args: list, cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    exe = shutil.which("clasp")
    if not exe:
        raise ClaspError("clasp isn't installed: npm install -g @google/clasp")
    r = subprocess.run([exe, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise ClaspError(f"clasp {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def _project(root: Path, cfg: dict, d: Path) -> None:
    sid = script_id(root)
    if not sid:
        raise ClaspError("no script ID yet: ./np mailer setup SCRIPT_ID")
    d.mkdir(parents=True, exist_ok=True)
    (d / ".clasp.json").write_text(json.dumps({"scriptId": sid, "rootDir": "."}), "utf-8")
    (d / ".claspignore").write_text("**/**\n!Code.js\n!Code.gs\n!appsscript.json\n", "utf-8")


def live_code(root: Path, cfg: dict) -> str:
    """The script as it is in Apps Script now (clasp pull into a temporary folder)."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _project(root, cfg, d)
        _clasp(["pull"], d)
        f = next((p for p in (d / "Code.js", d / "Code.gs") if p.exists()), None)
        return f.read_text("utf-8") if f else ""


def _norm(s: str) -> str:
    return "\n".join(ln.rstrip() for ln in (s or "").replace("\r\n", "\n").strip().split("\n"))


def status(root: Path, cfg: dict) -> dict:
    out = {"clasp": bool(shutil.which("clasp")), "logged_in": (Path.home() / ".clasprc.json").exists(),
           "script_id": bool(script_id(root)), "deployment": bool(deployment_id(cfg)), "matches": None}
    if all(out[k] for k in ("clasp", "logged_in", "script_id")):
        try:
            out["matches"] = _norm(live_code(root, cfg)) == _norm((root / SRC).read_text("utf-8"))
        except ClaspError as e:
            out["error"] = str(e)
    return out


def deploy(root: Path, cfg: dict, version: str = "") -> str:
    from .presence import confirmed
    if not confirmed():
        raise ClaspError("deploying the mail script needs Steven (a terminal, or Approve in the run queue's dialog)")
    dep = deployment_id(cfg)
    if not dep:
        raise ClaspError("email.script_url has no deployment ID")
    d = root / BUILD
    if d.exists():
        shutil.rmtree(d)
    _project(root, cfg, d)
    _clasp(["pull"], d)                                  # the project's own manifest (appsscript.json)
    for old in ("Code.js", "Code.gs"):
        (d / old).unlink(missing_ok=True)
    code = (root / SRC).read_text("utf-8")
    (d / "Code.js").write_text(code, "utf-8")
    _clasp(["push", "-f"], d)
    desc = f"AI Briefing mailer {version}".strip()
    _clasp(["deploy", "--deploymentId", dep, "--description", desc], d)
    rec = {"at": dt.datetime.now().isoformat(timespec="seconds"), "version": version,
           "sha": hashlib.sha256(code.encode()).hexdigest()[:16]}
    with (root / LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    shutil.rmtree(d, ignore_errors=True)
    return f"mail script deployed ({desc}; same URL)"
