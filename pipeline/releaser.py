"""Promote a release from dev to production, or roll production back (docs/plans/release-process.md).

    ./np release VERSION "reviewed: ..."   # in production, 08:30-20:00: merge dev, gate + approval, tag,
                                           # public code, backup, hub status. One approval for the whole release.
    ./np rollback "reviewed: ..."          # in production, any time no run is in progress: code back to the
                                           # previous release (VERSION included), gate + approval, backup, hub

Production code only changes here (and in a hotfix). Content (watchlist, sources, perspective, takes) is
edited in production as before. Data paths are never part of a release: the dev hook refuses them.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

from .env import staging

CODE_PATHS = ("pipeline", "dashboard", "scripts", "tests", "run.py", "np", "requirements.txt", "VERSION")
WINDOW = (dt.time(8, 30), dt.time(20, 0))
LOG = "data/state/releases.jsonl"


class ReleaseError(RuntimeError):
    pass


def _clean_env() -> dict:
    """The environment without GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE: git here always acts on the repo at cwd."""
    import os
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}


def _git(root: Path, *a, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, env=_clean_env())
    if check and r.returncode:
        raise ReleaseError(f"git {' '.join(a[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def run_in_progress(root: Path) -> bool:
    p = root / "data" / "run_current.json"
    try:
        cur = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        cur = {}
    if cur and not cur.get("ended"):
        return True
    import os
    if os.environ.get("NP_TESTING"):                     # tests never look at the machine's real processes
        return False
    r = subprocess.run(["pgrep", "-f", "run.py (--daily|--rebrief|--reprocess)"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _checks(root: Path, force: bool, now: dt.datetime | None, window: bool = True):
    if staging(root):
        raise ReleaseError("releases are promoted from the production folder, not from dev")
    t = (now or dt.datetime.now()).time()
    if window and not force and not (WINDOW[0] <= t <= WINDOW[1]):
        raise ReleaseError("releases go out between 08:30 and 20:00 (after the morning send, before the evening "
                           "preflight); use --force only if you must")
    if run_in_progress(root):
        raise ReleaseError("a run is in progress: wait for it to finish")
    dirty = _git(root, "status", "--porcelain", "--", *CODE_PATHS).stdout.strip()
    if dirty:
        raise ReleaseError("production has code changes outside a release:\n" + dirty[:600] +
                           "\nmove them to dev (or make them a hotfix) first")


def history(root: Path) -> list:
    p = root / LOG
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def _record(root: Path, row: dict):
    p = root / LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _approve(root: Path, cfg: dict, note: str, pre: str, interactive=None, log=print):
    from .release import ReleaseBlocked, approve
    try:
        rec = approve(root, cfg, note, log=log, interactive=interactive)
    except ReleaseBlocked as e:
        _git(root, "reset", "-q", "--hard", pre)
        raise ReleaseError(f"not released, production is back at {pre[:12]}: {e}") from e
    if not rec["passed"]:
        _git(root, "reset", "-q", "--hard", pre)
        raise ReleaseError(f"the release gate failed; production is back at {pre[:12]}")
    from .archive import Archive
    Archive(root, cfg.get("paths") or {}).git_commit("security: release approval", paths=("docs/security/approvals.json",))


def promote(root: Path, cfg: dict, version: str, note: str, force: bool = False, now=None, interactive=None,
            log=print) -> dict:
    version = version.lstrip("v")
    _checks(root, force, now)
    if not note.lower().startswith("reviewed"):
        raise ReleaseError('the note must start with "reviewed:" (what you reviewed in the release)')
    if _git(root, "rev-parse", "-q", "--verify", f"refs/tags/v{version}", check=False).returncode == 0:
        raise ReleaseError(f"v{version} is already released")
    if _git(root, "rev-parse", "-q", "--verify", "refs/heads/dev", check=False).returncode:
        raise ReleaseError("there is no dev branch: ./np dev setup")
    for marker in (".staging", ".venv", ".env"):          # checkout-local files never travel in a release
        if _git(root, "ls-tree", "--name-only", "dev", "--", marker).stdout.strip():
            raise ReleaseError(f"dev has {marker} committed: git rm --cached {marker} on dev first")
    dev_version = _git(root, "show", "dev:VERSION").stdout.strip()
    if dev_version != version:
        raise ReleaseError(f"dev is at {dev_version or '(no VERSION)'}, not {version}: set VERSION on dev and commit")
    if f"## v{version}" not in _git(root, "show", "dev:CHANGELOG.md").stdout:
        raise ReleaseError(f"CHANGELOG.md on dev has no '## v{version}' section")
    previous = (root / "VERSION").read_text("utf-8").strip() if (root / "VERSION").exists() else ""
    pre = _git(root, "rev-parse", "HEAD").stdout.strip()
    r = _git(root, "merge", "--no-ff", "dev", "-m", f"release v{version}", check=False)
    if r.returncode:
        _git(root, "merge", "--abort", check=False)
        raise ReleaseError(f"merging dev failed (production unchanged): {(r.stderr or r.stdout).strip()[:300]}")
    _approve(root, cfg, f"release v{version}: {note}", pre, interactive, log)
    _git(root, "tag", "-a", f"v{version}", "-m", f"AI Briefing v{version}")
    from .release import install_hooks
    install_hooks(root)                                  # hooks change with releases too
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    _record(root, {"at": dt.datetime.now().isoformat(timespec="seconds"), "kind": "release", "version": version,
                   "previous": previous, "commit": sha, "note": note[:300]})
    return {"version": version, "previous": previous, "commit": sha}


def rollback(root: Path, cfg: dict, note: str, interactive=None, log=print) -> dict:
    _checks(root, True, None, window=False)
    if not note.lower().startswith("reviewed"):
        raise ReleaseError('the note must start with "reviewed:" (why you are rolling back)')
    cur = (root / "VERSION").read_text("utf-8").strip()
    prev = next((h.get("previous") for h in reversed(history(root)) if h.get("kind") == "release"
                 and h.get("version") == cur), "")
    if not prev:
        raise ReleaseError(f"no recorded release before v{cur} to roll back to")
    if _git(root, "rev-parse", "-q", "--verify", f"refs/tags/v{prev}", check=False).returncode:
        raise ReleaseError(f"tag v{prev} not found")
    pre = _git(root, "rev-parse", "HEAD").stdout.strip()
    have = lambda ref, p: _git(root, "cat-file", "-e", f"{ref}:{p}", check=False).returncode == 0  # noqa: E731
    paths = [p for p in CODE_PATHS if have("HEAD", p) or have(f"v{prev}", p)]
    _git(root, "restore", f"--source=v{prev}", "--staged", "--worktree", "--", *paths)
    _git(root, "commit", "-q", "-m", f"rollback v{cur} -> v{prev}")
    _approve(root, cfg, f"rollback v{cur} -> v{prev}: {note}", pre, interactive, log)
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    _record(root, {"at": dt.datetime.now().isoformat(timespec="seconds"), "kind": "rollback", "version": prev,
                   "previous": cur, "commit": sha, "note": note[:300]})
    return {"version": prev, "previous": cur, "commit": sha}
