"""The running version: VERSION at the project root (0.MINOR.PATCH[-beta]); release notes in CHANGELOG.md."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def full(root: Path | None = None) -> str:
    """'0.1.0-beta', or 'dev' when there is no VERSION file."""
    try:
        return (( root or ROOT) / "VERSION").read_text("utf-8").strip() or "dev"
    except OSError:
        return "dev"


def short(root: Path | None = None) -> str:
    """'v0.1 beta' for footers: major.minor plus the pre-release word."""
    v = full(root)
    m = re.match(r"^(\d+)\.(\d+)\.\d+(?:-([a-z]+))?", v)
    if not m:
        return v
    return f"v{m.group(1)}.{m.group(2)}" + (f" {m.group(3)}" if m.group(3) else "")


def tag(root: Path | None = None) -> str:
    return "v" + full(root)


def changelog(root: Path | None = None) -> str:
    try:
        return ((root or ROOT) / "CHANGELOG.md").read_text("utf-8")
    except OSError:
        return ""


def releases(root: Path | None = None) -> list:
    """[(heading, body markdown)] for each '## v...' section, newest first; 'Unreleased' left out."""
    text = changelog(root)
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    out = []
    for p in parts:
        head, _, body = p.partition("\n")
        if head.strip().lower().startswith("unreleased"):
            continue
        out.append((head.strip(), body.strip()))
    return out
