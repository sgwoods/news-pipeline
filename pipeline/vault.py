"""Secrets: macOS Keychain first, then the environment / .env (gitignored, mode 600).

    ./np secrets status        which secrets are set, and where (never prints values)
    ./np secrets migrate       copy .env secrets into the Keychain (service "news-pipeline"); then you may
                               delete those lines from .env yourself

Secrets are read only by the modules that need them and are never passed to model subprocesses
(see llm.ClaudeCode: it runs with a minimal environment).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE = "news-pipeline"
NAMES = ("GMAIL_APP_PASSWORD", "SLACK_USER_TOKEN", "EMAIL_SCRIPT_KEY", "ANTHROPIC_API_KEY")
ROOT = Path(__file__).resolve().parent.parent


def _keychain(name: str) -> str:
    if sys.platform != "darwin" or not shutil.which("security"):
        return ""
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _dotenv() -> dict:
    p = ROOT / ".env"
    out = {}
    try:
        for ln in p.read_text("utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def get(name: str) -> str:
    return _keychain(name) or os.environ.get(name, "") or _dotenv().get(name, "")


def where(name: str) -> str:
    if _keychain(name):
        return "Keychain"
    if os.environ.get(name):
        return "environment"
    if _dotenv().get(name):
        return ".env"
    return "not set"


def migrate() -> list:
    """Copy secrets from .env into the Keychain. -> names stored."""
    if sys.platform != "darwin":
        raise RuntimeError("Keychain is macOS only")
    env, done = _dotenv(), []
    for n in NAMES:
        v = env.get(n)
        if not v:
            continue
        if any(ch in v for ch in '"\\\n'):
            continue
        # `security -i` reads the command from stdin, so the secret never appears in the process list
        r = subprocess.run(["security", "-i"], input=f'add-generic-password -U -s {SERVICE} -a {n} -w "{v}"\n',
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            done.append(n)
    return done


def set_keychain(name: str, value: str) -> bool:
    if sys.platform != "darwin" or any(ch in value for ch in '"\\\n'):
        return False
    r = subprocess.run(["security", "-i"], input=f'add-generic-password -U -s {SERVICE} -a {name} -w "{value}"\n',
                       capture_output=True, text=True, timeout=10)
    return r.returncode == 0


def env_file_mode_ok() -> bool:
    p = ROOT / ".env"
    return not p.exists() or (p.stat().st_mode & 0o077) == 0
