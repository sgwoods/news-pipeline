"""Release gate: nothing goes out (site publish, subscriber email, Steven's note, Gmail label writes, backup
push) unless this gate has passed for the exact code that is running.

    ./np release-check                 run every check, record the result for this code
    ./np release-check approve "…"   after reviewing a change to a security-sensitive file, record the approval
    ./np release-check live          also exercise the claude CLI isolation flags (Mac only)
    ./np release-check install-hooks git hooks: secret scan on commit, full gate on push

Checks: unit tests; secret scan of every tracked file (patterns + the real secret values); security
invariants (mailbox guard, model isolation, web stages without mailbox text, output privacy gates, dashboard
localhost-only, publish and backup guards, Apps Script recipient limit, .gitignore); a privacy scan of the
last editions; and, when a security-sensitive file changed, an explicit human approval.
Results: data/state/release.json (latest) and docs/security/approvals.json (approvals, committed).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = "data/state/release.json"
PASSED = "data/state/release-passed.jsonl"   # every code + sensitive-files fingerprint that passed the full gate
APPROVALS = "docs/security/approvals.json"
CODE = ["pipeline/**/*.py", "pipeline/prompts/*.md", "dashboard/**/*.py", "dashboard/templates/*.html",
        "scripts/**/*.gs", "run.py", "np", "requirements.txt"]
# Everything that runs or steers the models needs a person's approval (security review 2026-10-18, H4: the
# hand-picked list had drifted; run.py and the privacy check itself could change unapproved). Files the dashboard
# edits day to day (watchlist.yaml, sources.yaml, profiles/*.yaml) stay out, or every click would need approval.
SENSITIVE = CODE + ["tests/**/*.py", ".gitignore", "config.yaml", "owner.yaml", "author.md", "author-private.md",
                    "newsletters.yaml", "conflicts.yaml", "source_profiles.yaml", "pronunciations.yaml"]
SECRET_PATTERNS = [
    (r"xox[abpr]-\d{6,}-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic key"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "private key"),
    (r"(?m)^\s*(?:GMAIL_APP_PASSWORD|SLACK_USER_TOKEN|EMAIL_SCRIPT_KEY|ANTHROPIC_API_KEY)\s*=\s*[^\s#<]{8,}", "secret assignment"),
    (r"AIza[0-9A-Za-z_-]{35}", "Google API key"),
]


OUTBOUND = [("pipeline/publish.py", "push"), ("pipeline/publish.py", "backup_push"), ("pipeline/mailsource.py", "label_day"),
            ("pipeline/hub.py", "push"), ("pipeline/export.py", "push"), ("pipeline/mailer.py", "call")]


class ReleaseBlocked(RuntimeError):
    pass


def _files(globs: list, root: Path = ROOT) -> list:
    out = set()
    for g in globs:
        out |= {p for p in root.glob(g) if p.is_file() and "__pycache__" not in p.parts}
    return sorted(out)


def fingerprint(globs: list, root: Path = ROOT) -> str:
    h = hashlib.sha256()
    for p in _files(globs, root):
        h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def _read(p: Path) -> str:
    try:
        return p.read_text("utf-8", errors="replace")
    except OSError:
        return ""


# ---------- checks: each returns (ok, detail) ----------

def check_tests(root: Path = ROOT) -> tuple:
    import os                                            # tests describe production behaviour, in either checkout,
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root,  # and never read the
                       capture_output=True, text=True, timeout=600,                              # live machine's state
                       env={**os.environ, "NP_ENV": "production", "NP_TESTING": "1"})
    out = (r.stderr or "") + (r.stdout or "")
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "release-tests.txt").write_text(out, "utf-8")
    failed = re.findall(r"^(?:FAIL|ERROR): (\S+) \(([^)]+)\)", out, re.M)
    ran = re.findall(r"^Ran \d+ tests?.*$", r.stderr or "", re.M)        # unittest's own summary, not test output
    verdict = re.findall(r"^(?:OK|FAILED)\b.*$", r.stderr or "", re.M)
    tail = (ran[-1:] + verdict[-1:]) or (out.strip().splitlines()[-1:] if out.strip() else [])
    detail = " · ".join(tail) + (" · " + ", ".join(f"{c}.{t}" for t, c in failed[:6]) if failed else "") \
        + (" · full output: logs/release-tests.txt" if r.returncode else "")
    return r.returncode == 0, detail[:400]


def tracked(root: Path = ROOT) -> list:
    r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True)
    return [root / f for f in r.stdout.split("\0") if f]


def check_secrets(root: Path = ROOT, files: list | None = None) -> tuple:
    from .vault import NAMES, env_file_mode_ok, get
    values = [v for v in (get(n) for n in NAMES) if v and len(v) >= 8]
    hits = []
    files = tracked(root) if files is None else files
    for p in files:
        if not p.is_file() or p.suffix.lower() in (".mp3", ".png", ".jpg", ".wav", ".zip") or p.stat().st_size > 5_000_000:
            continue
        t = _read(p)
        rel = str(p.relative_to(root))
        for pat, what in SECRET_PATTERNS:
            if rel.startswith("tests/") and what == "secret assignment":
                continue
            if re.search(pat, t):
                hits.append(f"{rel}: {what}")
        for v in values:
            if v in t or v.replace(" ", "") in t.replace(" ", ""):
                hits.append(f"{rel}: contains a real secret value")
                break
    gi = _read(root / ".gitignore")
    if ".env" in {str(p.relative_to(root)) for p in files}:
        hits.append(".env is tracked by git")
    for need in (".env", "data/inbox/"):
        if need not in gi.splitlines():
            hits.append(f".gitignore does not list {need}")
    if not env_file_mode_ok():
        hits.append(".env is readable by others (chmod 600 .env)")
    return not hits, "; ".join(hits[:10]) or "no secrets in tracked files"


def check_invariants(root: Path = ROOT) -> tuple:
    bad = []
    src = {p: _read(root / p) for p in ("pipeline/mailsource.py", "pipeline/feedback.py", "run.py", "pipeline/dive.py",
                                         "pipeline/deepdive.py", "pipeline/publish.py", "dashboard/app.py",
                                         "scripts/apps-script/Code.gs", "pipeline/stages.py")}
    # 1 mailbox: imaplib only inside mailsource.connect, which returns the guard
    for p in _files(["pipeline/**/*.py", "dashboard/**/*.py", "run.py"], root):
        rel = str(p.relative_to(root))
        if rel not in ("pipeline/mailsource.py", "pipeline/mailguard.py", "pipeline/release.py") and \
                re.search(r"^\s*(?:import|from)\s+imaplib\b|\bimaplib\.", _read(p), re.M):
            bad.append(f"{rel} uses imaplib directly (must go through mailsource.connect)")
    for p in _files(["pipeline/**/*.py", "dashboard/**/*.py", "run.py"], root):
        rel = str(p.relative_to(root))
        if rel not in ("pipeline/mailguard.py", "pipeline/release.py") and re.search(r"_GuardedIMAP__box|\._box\b", _read(p)):
            bad.append(f"{rel} reaches past the mailbox guard")
    if "return GuardedIMAP(box" not in src["pipeline/mailsource.py"]:
        bad.append("mailsource.connect does not return the mailbox guard")
    # 2 models: no tools, no MCP, no secrets
    from .llm import ClaudeCode
    saved = ClaudeCode._help
    ClaudeCode._help = "--strict-mcp-config --mcp-config --tools"
    try:
        a = ClaudeCode({}).build_args("x")
        if a[a.index("--tools") + 1] != "" or "--allowedTools" in a:
            bad.append("claude_code default has tools")
        w = ClaudeCode({})
        w.web = True
        aw = w.build_args("x")
        if aw[aw.index("--tools") + 1] != "WebSearch,WebFetch":
            bad.append("web stage has tools beyond WebSearch/WebFetch")
        if "--strict-mcp-config" not in a:
            bad.append("MCP servers are not disabled")
    finally:
        ClaudeCode._help = saved
    import os
    os.environ["__RG_PROBE_GMAIL_APP_PASSWORD"] = "x"
    for n in ("GMAIL_APP_PASSWORD", "SLACK_USER_TOKEN", "EMAIL_SCRIPT_KEY", "ANTHROPIC_API_KEY"):
        if n in ClaudeCode.ENV_KEEP:
            bad.append(f"{n} is passed to the claude CLI")
    del os.environ["__RG_PROBE_GMAIL_APP_PASSWORD"]
    # 3 web stages never see mailbox text
    if "web_safe_text" not in src["pipeline/dive.py"] or "web_safe_text" not in src["pipeline/deepdive.py"]:
        bad.append("a web-enabled stage may receive mailbox text")
    # 4 output gates
    for need in ("verify_quotes", "scrub_private", "scrub_output"):
        if need not in src["run.py"].split("def save_briefing", 1)[-1].split("\ndef ", 1)[0]:
            bad.append(f"save_briefing no longer applies {need}")
    if "scan_site(" not in src["pipeline/publish.py"].split("def push", 1)[-1]:
        bad.append("publish.push does not scan the site")
    if "PRIVATE" not in src["pipeline/publish.py"].split("def backup_push", 1)[-1]:
        bad.append("backup push does not check the repo is private")
    # 5 dashboard
    if 'host="127.0.0.1"' not in src["dashboard/app.py"] or "def localhost_only" not in src["dashboard/app.py"]:
        bad.append("dashboard is not localhost-only")
    # 6 Apps Script recipient limit
    if "recipient not allowed" not in src["scripts/apps-script/Code.gs"]:
        bad.append("Apps Script send is not limited to subscribers/owner")
    # 7 the private people list is read in one place only
    for p in _files(["pipeline/**/*.py", "dashboard/**/*.py", "run.py"], root):
        rel = str(p.relative_to(root))
        # publish.py names the file only to refuse publishing it; release.py names it to check this rule
        if rel not in ("pipeline/stages.py", "pipeline/publish.py", "pipeline/release.py") and "author-private" in _read(p):
            bad.append(f"{rel} reads author-private.md")
    # 9 staging can't reach readers: every outbound function goes through require() (refused in staging), and the
    #   mailer keeps its staging branch (docs/plans/release-process.md, pipeline/env.py)
    import ast
    for rel, fn in OUTBOUND:
        t = _read(root / rel)
        if not t:
            continue
        node = next((n for n in ast.walk(ast.parse(t)) if isinstance(n, ast.FunctionDef) and n.name == fn), None)
        calls = {getattr(c.func, "id", getattr(c.func, "attr", "")) for c in ast.walk(node) if isinstance(c, ast.Call)} \
            if node else set()
        if "require" not in calls:
            bad.append(f"{rel}:{fn} does not pass the release gate (require), so staging could reach readers")
    if "staging(_root)" not in _read(root / "pipeline/mailer.py"):
        bad.append("the mailer has lost its staging guard")
    return not bad, "; ".join(bad) or "all invariants hold"


def check_outputs(root: Path, cfg: dict, days: int = 3) -> tuple:
    from .quality import privacy_check
    bdir = root / (cfg.get("paths") or {}).get("briefings", "briefings")
    texts = []
    for f in sorted(bdir.glob("????-??-??.md"))[-days:]:
        texts.append(_read(f))
        texts.append(_read(bdir / f"{f.stem}.script.md"))
        texts.append(_read(bdir / "deepdives" / f"{f.stem}.md"))
        texts.append(_read(bdir / "deepdives" / f"{f.stem}.script.md"))
    status, details = privacy_check(root, cfg, [t for t in texts if t])
    return status == "pass", "; ".join(details) or f"last {days} editions clean"


def check_cli(root: Path = ROOT) -> tuple:
    """live: the installed claude CLI supports the isolation flags (else the deny-list is the only layer)."""
    from .llm import ClaudeCode
    c = ClaudeCode({})
    import shutil
    if not shutil.which(c.cmd):
        return True, "claude CLI not on PATH here (checked on the Mac)"
    flags = c._flags()
    missing = [f for f in ("--strict-mcp-config", "--tools") if f not in flags]
    return not missing, ("supports --strict-mcp-config and --tools" if not missing
                         else "claude CLI lacks " + ", ".join(missing) + ": update Claude Code")


def approvals(root: Path = ROOT) -> list:
    try:
        return json.loads(_read(root / APPROVALS) or "[]")
    except json.JSONDecodeError:
        return []


def changed_sensitive(root: Path = ROOT) -> list:
    """Security-sensitive files changed since the commit of the last approval (for the evening notice)."""
    import subprocess
    last = (approvals(root) or [{}])[-1].get("commit", "")
    if not last:
        return []
    r = subprocess.run(["git", "diff", "--name-only", last, "--"] + SENSITIVE, cwd=root, capture_output=True, text=True)
    return [x for x in r.stdout.split() if x]


def check_approval(root: Path = ROOT) -> tuple:
    fp = fingerprint(SENSITIVE, root)
    ok = any(a.get("sensitive") == fp for a in approvals(root))
    return ok, ("security-sensitive files approved" if ok else
                "security-sensitive files changed since the last approval: review the diff, then "
                "./np release-check approve \"what you reviewed\"")


def run(root: Path, cfg: dict, live: bool = False, tests: bool = True, log=print) -> dict:
    checks = {}
    if tests:
        checks["tests"] = check_tests(root)
    checks["secrets"] = check_secrets(root)
    checks["invariants"] = check_invariants(root)
    checks["outputs"] = check_outputs(root, cfg)
    if live:
        checks["cli"] = check_cli(root)
    checks["approval"] = check_approval(root)
    passed = all(ok for ok, _ in checks.values())
    rec = {"at": dt.datetime.now().isoformat(timespec="seconds"), "fingerprint": fingerprint(CODE, root),
           "sensitive": fingerprint(SENSITIVE, root), "passed": passed,
           "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip(),
           "checks": {k: {"ok": ok, "detail": d} for k, (ok, d) in checks.items()}}
    p = root / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=1) + "\n", "utf-8")
    if passed and tests and not passed_before(root, rec["fingerprint"], rec["sensitive"]):
        with (root / PASSED).open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: rec[k] for k in ("at", "fingerprint", "sensitive", "commit")}) + "\n")
    for k, (ok, d) in checks.items():
        log(f"  {'PASS' if ok else 'FAIL'}  {k:11} {d}")
    log(f"Release gate: {'PASSED' if passed else 'BLOCKED'} for code {rec['fingerprint']} (commit {rec['commit']})")
    return rec


def passed_before(root: Path, fp: str, sfp: str) -> bool:
    """Has exactly this code and these sensitive files passed the full gate (tests included) before?"""
    p = root / PASSED
    if not p.exists():
        return False
    for ln in p.read_text("utf-8").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("fingerprint") == fp and r.get("sensitive") == sfp:
            return True
    return False


def approve(root: Path, cfg: dict, note: str, who: str = "Steven", log=print, interactive=None) -> dict:
    """Only a person at a terminal can approve: scheduled jobs, agents and the dashboard cannot."""
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if not interactive:
        raise ReleaseBlocked("approval needs a person at a terminal: run ./np release-check approve \"...\" in Terminal")
    if not note.strip():
        raise ReleaseBlocked("say what you reviewed: ./np release-check approve \"...\"")
    rec = run(root, cfg, log=lambda *a: None)
    others = {k: v for k, v in rec["checks"].items() if k != "approval"}
    if not all(v["ok"] for v in others.values()):
        raise ReleaseBlocked("fix the failing checks before approving: " +
                             "; ".join(f"{k}: {v['detail']}" for k, v in others.items() if not v["ok"]))
    rows = approvals(root)
    rows.append({"at": rec["at"], "sensitive": rec["sensitive"], "commit": rec["commit"], "by": who, "note": note.strip()[:500]})
    p = root / APPROVALS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=1) + "\n", "utf-8")
    return run(root, cfg, log=log)


def require(root: Path, cfg: dict, action: str, log=print, staging_ok: bool = False) -> None:
    """Call before anything outbound. Re-runs the gate (without the slow live check) when the code changed.
    In a staging checkout (pipeline/env.py) every outbound action is refused, except the few that pass staging_ok
    (owner-only review sends)."""
    from .env import staging
    if staging(root) and not staging_ok:
        raise ReleaseBlocked(f"{action} is switched off in staging (this is a development checkout)")
    try:
        rec = json.loads(_read(root / STATE) or "{}")
    except json.JSONDecodeError:
        rec = {}
    fp, sfp = fingerprint(CODE, root), fingerprint(SENSITIVE, root)
    if rec.get("passed") and rec.get("fingerprint") == fp and rec.get("sensitive") == sfp:
        return
    # Code that already passed the full gate (tests included) and is approved never re-runs the tests: a morning
    # publish must not depend on the test suite behaving the same while a run is in progress (2026-10-23).
    if not staging(root) and passed_before(root, fp, sfp) and check_approval(root)[0]:
        return
    log(f"Release gate: code changed since the last check; checking before {action}...")
    rec = run(root, cfg, log=log)
    if staging(root) and staging_ok:                     # the dev preview: every check but the production approval
        bad = {k: v for k, v in rec["checks"].items() if not v["ok"] and k != "approval"}
        if bad:
            raise ReleaseBlocked(f"{action} blocked by the release gate: " +
                                 "; ".join(f"{k}: {v['detail']}" for k, v in bad.items())[:500])
        return
    if not rec["passed"]:
        bad = "; ".join(f"{k}: {v['detail']}" for k, v in rec["checks"].items() if not v["ok"])
        raise ReleaseBlocked(f"{action} blocked by the release gate: {bad}"[:600])


HOOKS = {
    "pre-commit": "#!/bin/sh\n# news-pipeline: no secrets in a commit (pipeline/release.py)\n"
                  "cd \"$(git rev-parse --show-toplevel)\" || exit 1\nPY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python\n"
                  "if [ -f .staging ] && git diff --cached --name-only | grep -qE '^(data|briefings|hub|site)/|^sources.yaml$'; then\n"
                  "  echo 'staging: data paths are never committed from the dev checkout (./np staging reset)'; exit 1; fi\n"
                  "exec \"$PY\" -c 'import sys; from pathlib import Path; from pipeline import release as r; "
                  "import subprocess; fs=[Path(f) for f in subprocess.run([\"git\",\"diff\",\"--cached\",\"--name-only\",\"--diff-filter=ACM\"],"
                  "capture_output=True,text=True).stdout.split()]; ok,d=r.check_secrets(Path(\".\").resolve(),[Path(\".\").resolve()/f for f in fs]); "
                  "print(\"secret scan:\", d); sys.exit(0 if ok else 1)'\n",
    "pre-push": "#!/bin/sh\n# news-pipeline: the release gate before anything is pushed (fast when this code already passed)\n"
                "cd \"$(git rev-parse --show-toplevel)\" || exit 1\nPY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python\n"
                "exec \"$PY\" run.py --release-check require\n",
}


def install_hooks(root: Path = ROOT) -> list:
    d = root / ".git" / "hooks"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for name, body in HOOKS.items():
        p = d / name
        p.write_text(body, "utf-8")
        p.chmod(0o755)
        out.append(name)
    return out
