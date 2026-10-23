"""Background services on macOS (launchd user agents) + health of what the pipeline depends on.

daily      runs `./np daily` at schedule.times (default 06:30 and a 07:30 retry)
dashboard  keeps `./np dash` running (starts at login, restarts if it crashes)
preflight  runs `./np preflight` each evening (schedule.preflight, default 20:30): notifies if an approval is pending
runner     the run queue (pipeline/runner.py): every minute and whenever a job file lands in data/queue/pending/

Plists live in ~/Library/LaunchAgents and point at this checkout, so moving the project to
another Mac is: clone, ./np setup, ./np service install.
"""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

LABELS = {"daily": "com.sgwoods.news-pipeline", "dashboard": "com.sgwoods.news-pipeline.dashboard",
          "preflight": "com.sgwoods.news-pipeline.preflight", "runner": "com.sgwoods.news-pipeline.runner"}


def _sh(args, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def plist_path(kind: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABELS[kind]}.plist"


def domain() -> str:
    return f"gui/{os.getuid()}"


def _path_env() -> str:
    dirs = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    for b in ("claude", "ollama", "ffmpeg", "gh", "git"):
        p = shutil.which(b)
        if p and os.path.dirname(p) not in dirs:
            dirs.append(os.path.dirname(p))
    return ":".join(dirs)


def build_plist(kind: str, root: Path, cfg: dict) -> dict:
    env = {"PATH": _path_env(), "HOME": str(Path.home()), "PYTHONUNBUFFERED": "1"}
    base = {"Label": LABELS[kind], "WorkingDirectory": str(root), "EnvironmentVariables": env}
    if kind == "daily":
        from .schedule import TICK_MINUTES               # every half hour; ./np scheduled checks the local time
        base.update({"ProgramArguments": ["/bin/bash", str(root / "np"), "scheduled", "daily"],
                     "StartCalendarInterval": [{"Minute": m} for m in TICK_MINUTES],
                     "StandardOutPath": str(root / "logs" / "launchd.out.log"),
                     "StandardErrorPath": str(root / "logs" / "launchd.err.log"), "RunAtLoad": False})
    elif kind == "preflight":
        from .schedule import TICK_MINUTES
        base.update({"ProgramArguments": ["/bin/bash", str(root / "np"), "scheduled", "preflight"],
                     "StartCalendarInterval": [{"Minute": m} for m in TICK_MINUTES],
                     "StandardOutPath": str(root / "logs" / "launchd.out.log"),
                     "StandardErrorPath": str(root / "logs" / "launchd.err.log"), "RunAtLoad": False})
    elif kind == "runner":                                # ticks fast; ./np runner tick exits at once when idle
        base.update({"ProgramArguments": ["/bin/bash", str(root / "np"), "runner", "tick"],
                     "StartInterval": 60, "WatchPaths": [str(root / "data" / "queue" / "pending")],
                     "StandardOutPath": str(root / "logs" / "runner.log"),
                     "StandardErrorPath": str(root / "logs" / "runner.log"), "RunAtLoad": True})
    else:
        base.update({"ProgramArguments": ["/bin/bash", str(root / "np"), "dash"],
                     "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 15,
                     "StandardOutPath": str(root / "logs" / "dashboard.out.log"),
                     "StandardErrorPath": str(root / "logs" / "dashboard.err.log")})
    return base


def install(kind: str, root: Path, cfg: dict) -> str:
    from .env import staging
    from .schedule import check
    if staging(root):
        raise RuntimeError("services are installed only in the production folder, never in the dev checkout")
    off = check(cfg)
    if off:
        raise RuntimeError(f"schedule times must be on :00 or :30 (the half-hour tick): {', '.join(off)}")
    p = plist_path(kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    if kind == "runner":
        (root / "data" / "queue" / "pending").mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        plistlib.dump(build_plist(kind, root, cfg), f)
    _sh(["launchctl", "bootout", f"{domain()}/{LABELS[kind]}"])
    r = _sh(["launchctl", "bootstrap", domain(), str(p)])
    return f"{kind}: installed" if r.returncode == 0 else f"{kind}: written but not loaded ({(r.stderr or r.stdout).strip()})"


def remove(kind: str) -> str:
    _sh(["launchctl", "bootout", f"{domain()}/{LABELS[kind]}"])
    plist_path(kind).unlink(missing_ok=True)
    return f"{kind}: removed"


def pause(kind: str) -> str:
    r = _sh(["launchctl", "bootout", f"{domain()}/{LABELS[kind]}"])
    return f"{kind}: paused (plist kept; resume to reload)" if r.returncode == 0 else f"{kind}: not loaded"


def resume(kind: str) -> str:
    r = _sh(["launchctl", "bootstrap", domain(), str(plist_path(kind))])
    return f"{kind}: resumed" if r.returncode == 0 else f"{kind}: {(r.stderr or r.stdout).strip() or 'failed'}"


def kick(kind: str, kill: bool = False) -> str:
    """daily: run the job now. dashboard: restart it (kill + start)."""
    args = ["launchctl", "kickstart"] + (["-k"] if kill else []) + [f"{domain()}/{LABELS[kind]}"]
    r = _sh(args)
    return f"{kind}: started" if r.returncode == 0 else f"{kind}: {(r.stderr or r.stdout).strip() or 'not loaded'}"


def restart_dashboard_detached() -> bool:
    """Restart the dashboard from inside the dashboard: fire-and-forget after a short delay."""
    if not loaded("dashboard"):
        return False
    subprocess.Popen(["/bin/bash", "-c", f"sleep 1; launchctl kickstart -k {domain()}/{LABELS['dashboard']}"],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def loaded(kind: str) -> bool:
    return _sh(["launchctl", "print", f"{domain()}/{LABELS[kind]}"]).returncode == 0


def status(kind: str) -> dict:
    st = {"kind": kind, "label": LABELS[kind], "installed": plist_path(kind).exists(), "loaded": False}
    r = _sh(["launchctl", "print", f"{domain()}/{LABELS[kind]}"])
    if r.returncode == 0:
        st["loaded"] = True
        for key, pat in (("state", r"^\s*state = (.+)$"), ("pid", r"^\s*pid = (\d+)"),
                         ("last_exit", r"last exit code = (.+)$"), ("runs", r"^\s*runs = (\d+)")):
            m = re.search(pat, r.stdout, re.M)
            if m:
                st[key] = m.group(1).strip()
    if st["installed"]:
        try:
            pl = plistlib.loads(plist_path(kind).read_bytes())
            cal = pl.get("StartCalendarInterval") or []
            st["times"] = [f"{c['Hour']:02d}:{c['Minute']:02d}" for c in cal]
            st["points_to"] = pl.get("WorkingDirectory", "")
        except Exception:  # noqa: BLE001
            pass
    return st


def ollama_status(cfg: dict) -> dict:
    base = ((cfg.get("llm") or {}).get("local") or {}).get("base_url", "http://localhost:11434").rstrip("/")
    out = {"url": base, "reachable": False, "models": []}
    try:
        import httpx
        r = httpx.get(f"{base}/api/tags", timeout=3)
        out["reachable"] = r.status_code == 200
        out["models"] = [m.get("name") for m in r.json().get("models", [])]
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
    out["brew_service"] = bool(shutil.which("brew")) and "ollama" in _sh(["brew", "services", "list"]).stdout
    return out


def restart_ollama() -> str:
    if not shutil.which("brew"):
        return "brew not found; restart the Ollama app manually"
    r = _sh(["brew", "services", "restart", "ollama"], timeout=60)
    return (r.stdout or r.stderr).strip() or "restarted"


def claude_status() -> dict:
    exe = shutil.which("claude")
    if not exe:
        return {"installed": False}
    r = _sh([exe, "--version"])
    return {"installed": True, "version": r.stdout.strip(), "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}


def all_status(root: Path, cfg: dict) -> dict:
    return {"daily": status("daily"), "dashboard": status("dashboard"), "preflight": status("preflight"),
            "ollama": ollama_status(cfg),
            "claude": claude_status(), "ffmpeg": bool(shutil.which("ffmpeg")), "gh": bool(shutil.which("gh")),
            "launchctl": bool(shutil.which("launchctl"))}
