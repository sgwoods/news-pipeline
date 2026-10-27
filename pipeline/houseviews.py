"""Read-only parser for house_views.md, and the positions ledger (Steven, 2026-10-27).

house_views.md is hand-edited by Steven: the lenses the briefing takes a position under ("Our read"), plus his
dated theses. Code reads it and never rewrites it (like perspective.md). Each Must read's Our read names the view
it uses; the lead story also gets a case for, a case against, the deciding question and our lean.

Every position taken is appended to data/positions/ledger.jsonl with what would change our mind and a check date
(the thesis's own, else 90 days on), so the calls can be scored later.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

FILE = "house_views.md"
LEDGER = "data/positions/ledger.jsonl"
DEFAULT_CHECK_DAYS = 90
_HEAD = re.compile(r"(?m)^## (\d+)\. (.+?)\s*$")


@dataclass
class View:
    n: int
    name: str
    view: str            # the view itself (first sentence(s), before *Apply:*)
    apply: str
    changes: str         # *Changes our mind:*
    check: str           # YYYY-MM or '' (theses only)
    words: str           # *In Steven's words:* verbatim, or ''

    @property
    def thesis(self) -> bool:
        return bool(self.check or self.words)


def _field(body: str, label: str) -> str:
    m = re.search(rf"\*{re.escape(label)}:\*\s*(.+?)(?=\s\*[A-Z][^*]{{1,30}}:\*|\Z)", body, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def parse(text: str) -> list:
    views = []
    heads = list(_HEAD.finditer(text))
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.end():end]
        body = re.split(r"(?m)^## ", body)[0].strip()
        lead = re.split(r"\s\*[A-Z][^*]{1,30}:\*", " " + body, maxsplit=1)[0]
        lead = re.sub(r"\*\*\[[^\]]*\]\*\*", "", re.sub(r"\s+", " ", lead)).strip()
        name = re.sub(r"\*\*\[[^\]]*\]\*\*", "", h.group(2)).strip()
        words = _field(body, "In Steven's words").strip('"“” ')
        views.append(View(int(h.group(1)), name, lead, _field(body, "Apply"), _field(body, "Changes our mind"),
                          _field(body, "Check").rstrip("."), words))
    return views


def load(root: Path) -> list:
    try:
        return parse((Path(root) / FILE).read_text("utf-8"))
    except OSError:
        return []


def by_number(views: list) -> dict:
    return {v.n: v for v in views}


def prompt_block(views: list) -> str:
    """The views as the editorial prompt sees them. Steven's verbatim words are context, never to be quoted."""
    if not views:
        return ""
    out = ["HOUSE VIEWS (the lenses we take positions under; numbered):"]
    for v in views:
        out.append(f"[V{v.n}] {v.name}. {v.view} Apply: {v.apply} Changes our mind: {v.changes}"
                   + (" (a dated thesis)" if v.thesis else ""))
    return "\n".join(out)


def check_date(v, day: str) -> str:
    if v is not None and re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", v.check or ""):
        return v.check if len(v.check) == 10 else v.check + "-01"
    return (dt.date.fromisoformat(day) + dt.timedelta(days=DEFAULT_CHECK_DAYS)).isoformat()


def log_positions(root: Path, day: str, sel: dict, views: list) -> int:
    """Append today's positions (one per Must read with a view) to the ledger; a rerun of the day replaces its rows."""
    vmap = by_number(views)
    rows = []
    for s in sel.get("must", []):
        n = s.get("house_view")
        if not n or not s.get("editor_view"):
            continue
        v = vmap.get(n)
        row = {"day": day, "key": s.get("key", ""), "headline": s.get("headline", ""),
               "url": (s.get("lead") or {}).get("url", ""), "view": n, "view_name": v.name if v else "",
               "position": s["editor_view"], "changes_our_mind": s.get("changes_our_mind") or (v.changes if v else ""),
               "check": check_date(v, day), "status": "open"}
        if s.get("lead_case"):
            row["lead_case"] = s["lead_case"]
        rows.append(row)
    p = Path(root) / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = []
    if p.exists():
        for ln in p.read_text("utf-8").splitlines():
            try:
                if json.loads(ln).get("day") != day:
                    keep.append(ln)
            except ValueError:
                keep.append(ln)
    keep += [json.dumps(r, ensure_ascii=False) for r in rows]
    p.write_text("\n".join(keep) + ("\n" if keep else ""), "utf-8")
    return len(rows)


def due(root: Path, on: str) -> list:
    """Open positions whose check date has come (for the scoring pass)."""
    p = Path(root) / LEDGER
    out = []
    if p.exists():
        for ln in p.read_text("utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("status") == "open" and r.get("check", "9999") <= on:
                out.append(r)
    return out
