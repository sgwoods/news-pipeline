"""Production or staging. A development checkout (git worktree on `dev`, docs/plans/release-process.md) is staging:
it can build everything but cannot reach readers or change shared state.

A checkout is staging when it has a `.staging` file at its root (untracked, gitignored, created by ./np dev setup)
or NP_ENV=staging is set. Nothing in config.yaml decides it, so a merge from dev can never carry staging into
production, or production into dev.

In staging the release gate's require() refuses every outbound action (site publish, backups, Gmail label
writes, the hub export, the public code push, subscriber and company email, Sheet changes), and mailer.call lets
through only reads and sends to the owner's own address, marked [STAGING].
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ".staging"


def mode(root: Path | None = None) -> str:
    v = (os.environ.get("NP_ENV") or "").strip().lower()
    if v in ("staging", "production"):
        return v
    return "staging" if ((root or ROOT) / MARKER).exists() else "production"


def staging(root: Path | None = None) -> bool:
    return mode(root) == "staging"


def label(root: Path | None = None) -> str:
    """'' in production, '[STAGING]' in staging (for subjects and banners)."""
    return "[STAGING]" if staging(root) else ""


def mark_subject(subject: str) -> str:
    """'AI Briefing · x' -> 'AI Briefing · [STAGING] x' (the Apps Script only sends subjects starting 'AI Briefing ·')."""
    s = str(subject or "")
    if "[STAGING]" in s:
        return s
    p = "AI Briefing ·"
    return f"{p} [STAGING]{s[len(p):]}" if s.startswith(p) else f"[STAGING] {s}"
