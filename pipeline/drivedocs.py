"""The day's edition and deep dive as Google Docs in Drive (Steven, 2026-10-26).

The mail script writes them into the mailer account's "Briefings" folder, which is shared with Steven, so he can
read them anywhere (and give feedback, e.g. while driving) and Claude can read them through Drive. Two moments:

- pre-release (the takes email): "<day> · AI Briefing (draft, held for your takes) · <lead>" and the deep dive;
- published: the draft is renamed "<day> · AI Briefing · <lead>" and rewritten with Steven's takes; the deep dive
  doc is rewritten (with his take on it, when there is one).

Names start with the date so the folder sorts by day. A rerun rewrites the same doc; nothing is ever deleted.
Drive is a copy for reading: a failure here never holds the edition.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _lead(md: str) -> str:
    """The first Top of mind headline (what the subscriber email's subject uses), else the edition title."""
    m = re.search(r"(?m)^-\s+\*\*(.+?)\*\*", md.split("## Top of mind", 1)[-1]) if "## Top of mind" in md else None
    if m:
        return m.group(1).strip().rstrip(".")
    first = md.splitlines()[0].lstrip("# ").strip() if md.startswith("# ") else "AI Briefing"
    return first.split("·", 1)[-1].strip()


def names(day: str, md: str) -> tuple:
    lead = _lead(md)[:110]
    return f"{day} · AI Briefing (draft, held for your takes) · {lead}", f"{day} · AI Briefing · {lead}"


def deepdive_name(day: str, title: str) -> str:
    return f"{day} · Deep dive · {title.removeprefix('Deep dive: ').strip()[:110]}"


def _takes_md(root: Path, day: str) -> str:
    try:
        notes = json.loads((root / "data" / "commentary" / f"{day}.json").read_text("utf-8")).get("notes", {})
    except (OSError, ValueError):
        return ""
    rows = [f"- **{n.get('title') or k}:** {n['text']}" for k, n in notes.items() if str(n.get("text", "")).strip()]
    return "## Steven's takes\n\n" + "\n".join(rows) + "\n" if rows else ""


def briefing_md(root: Path, cfg: dict, day: str, final: bool) -> str:
    md = (root / cfg["paths"]["briefings"] / f"{day}.md").read_text("utf-8")
    return md.rstrip() + "\n\n" + (_takes_md(root, day) if final else "")


def deepdive_md(root: Path, cfg: dict, day: str) -> tuple:
    """(title, markdown) of DAY's deep dive: show notes, then the article, then the sources; ('', '') if none."""
    from . import deepdive
    p = root / deepdive.DIR / f"{day}.md"
    if not p.exists():
        return "", ""
    notes = p.read_text("utf-8")
    title = notes.splitlines()[0].lstrip("# ").strip()
    head, _, srcs = notes.partition("## Sources")
    body = deepdive.written_md(root, day)
    return title, head.rstrip() + "\n\n" + body + ("\n\n## Sources" + srcs if srcs else "")


def _save(cfg: dict, name: str, md: str, replace: str = "") -> dict:
    from . import mailer
    return mailer.call(cfg, "savedoc", name=name, text=md, **({"replace": replace} if replace else {}))


def save_day(root: Path, cfg: dict, day: str, final: bool, log=print) -> dict:
    """Write DAY's edition (draft or published) and its deep dive to Drive. -> {"briefing": url, "deepdive": url}."""
    if not (cfg.get("drive") or {}).get("enabled", True):
        return {}
    out = {}
    try:
        md = (root / cfg["paths"]["briefings"] / f"{day}.md").read_text("utf-8")
        draft, published = names(day, md)
        r = _save(cfg, published if final else draft, briefing_md(root, cfg, day, final), replace=draft if final else "")
        out["briefing"] = r.get("url", "") if r.get("ok") else ""
        title, dmd = deepdive_md(root, cfg, day)
        if dmd:
            r = _save(cfg, deepdive_name(day, title), dmd)
            out["deepdive"] = r.get("url", "") if r.get("ok") else ""
        log(f"Drive: {'published' if final else 'draft'} edition" + (" and deep dive" if dmd else "") + " saved to Briefings")
    except Exception as e:  # noqa: BLE001 - a copy for reading; never holds the edition
        log(f"Drive copy skipped: {e}"[:200])
    return out
