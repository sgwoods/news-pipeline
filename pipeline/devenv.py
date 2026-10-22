"""The development checkout: a git worktree on branch `dev`, in staging mode (docs/plans/release-process.md).

    ./np dev setup          # from production: create ~/Developer/news-pipeline-dev (branch dev), mark it staging
    ./np staging sync       # in dev: bring in production's latest data and fixes (merge main), recent audio
    ./np staging run [DAY]  # in dev: rebuild DAY's edition (default: production's latest) with the dev code;
                            # outbound is off; --email sends the review copy to the owner only, marked [STAGING]
    ./np staging reset      # in dev: throw away what staging runs wrote (data/, briefings/, hub/, site/)

Production is never written by these commands. Staging outputs are never committed: the shared pre-commit hook
refuses data paths in a staging checkout. Staging runs refuse the production window (03:30-08:30) unless --force,
so they never compete with the morning run for the local model.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

from .env import MARKER, staging

DATA_PATHS = ("data", "briefings", "hub", "sources.yaml")
WINDOW = (dt.time(3, 30), dt.time(8, 30))


class DevError(RuntimeError):
    pass


def _clean_env() -> dict:
    """The environment without GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE: git here always acts on the repo at cwd."""
    import os
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}


def _git(cwd: Path, *a, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, env=_clean_env())
    if check and r.returncode:
        raise DevError(f"git {' '.join(a[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def production_root(root: Path) -> Path:
    """The main worktree (production) for this repository."""
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    return common.parent


def dev_path(root: Path, cfg: dict) -> Path:
    p = (cfg.get("dev") or {}).get("path")
    return Path(os.path.expanduser(p)) if p else root.parent / f"{root.name}-dev"


def setup(root: Path, cfg: dict, log=print) -> str:
    if staging(root):
        raise DevError("run ./np dev setup from the production folder, not from dev")
    dev = dev_path(root, cfg)
    if not (dev / ".git").exists():
        has = _git(root, "rev-parse", "-q", "--verify", "refs/heads/dev", check=False).returncode == 0
        args = ["worktree", "add", str(dev), "dev"] if has else ["worktree", "add", "-b", "dev", str(dev), "HEAD"]
        _git(root, *args)
        log(f"created {dev} on branch dev")
    (dev / MARKER).write_text("development checkout: staging mode (pipeline/env.py). Don't copy this file to production.\n")
    venv = dev / ".venv"
    if not venv.exists() and (root / ".venv").exists():
        venv.symlink_to(root / ".venv")                  # same packages as production; ./np setup --rebuild for its own
    for name in (".env",):
        src = root / name
        if src.is_file() and not (dev / name).exists():
            shutil.copy2(src, dev / name)
            os.chmod(dev / name, 0o600)
    from .release import install_hooks
    install_hooks(root)                                  # shared by both checkouts; refuses data paths in staging
    return f"dev checkout ready: {dev} (staging). Next: cd {dev} && ./np staging sync && ./np staging run"


def _need_staging(root: Path):
    if not staging(root):
        raise DevError("this is the production folder: staging commands run only in the dev checkout")


def reset(root: Path, log=print) -> str:
    _need_staging(root)
    paths = [p for p in DATA_PATHS if (root / p).exists()]
    _git(root, "checkout", "--", *paths)
    _git(root, "clean", "-fdq", "--", *paths)
    if (root / "site").exists():
        shutil.rmtree(root / "site")
    return "staging outputs discarded (data, briefings, hub, site)"


def sync(root: Path, cfg: dict, log=print, audio_days: int = 3) -> str:
    _need_staging(root)
    prod = production_root(root)
    log(reset(root))
    if _git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise DevError("dev has uncommitted code changes: commit them on dev first (sync merges production's main)")
    r = _git(root, "merge", "--no-edit", "main", check=False)
    if r.returncode:
        _git(root, "merge", "--abort", check=False)
        raise DevError(f"merging production's main into dev failed: {(r.stderr or r.stdout).strip()[:300]}")
    copied = 0                                           # recent audio is gitignored: copy (never link) a few days
    days = sorted(p.stem for p in (prod / "briefings").glob("????-??-??.md"))[-audio_days:]
    for d in days:
        for src in list((prod / "briefings").glob(f"{d}*.mp3")) + list((prod / "briefings" / "deepdives").glob(f"{d}*.mp3")):
            dst = root / src.relative_to(prod)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    head = _git(root, "log", "-1", "--format=%h %s").stdout.strip()
    return f"dev synced with production main ({head}); {copied} recent audio file(s) copied"


def check_window(force: bool = False, now: dt.datetime | None = None):
    t = (now or dt.datetime.now()).time()
    if not force and WINDOW[0] <= t <= WINDOW[1]:
        raise DevError("03:30-08:30 is the production window: staging runs would compete with the morning run "
                       "(use --force if production isn't running)")


def latest_day(root: Path) -> str:
    days = sorted(p.stem for p in (root / "briefings").glob("????-??-??.md"))
    if not days:
        raise DevError("no editions in dev yet: run ./np staging sync")
    return days[-1]
