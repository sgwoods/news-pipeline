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


# ---------- scoring (weekly) ----------

_STOP = {"the", "and", "for", "with", "from", "that", "this", "its", "into", "under", "over", "after", "amid",
         "says", "said", "new", "its", "has", "have", "are", "was", "will", "about", "more", "than", "out"}


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.$-]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


def later_stories(root: Path, row: dict, limit: int = 10) -> list:
    """Stories from our own briefings after the call that share its subject (at least two words of its headline)."""
    want = _words(row.get("headline", "")) | _words(row.get("view_name", "")) - _STOP
    head = _words(row.get("headline", ""))
    out = []
    for p in sorted((Path(root) / "data" / "stories").glob("????-??-??.jsonl")):
        if p.stem <= row.get("day", ""):
            continue
        try:
            lines = [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]
        except (OSError, ValueError):
            continue
        for s in (lines[-1].get("stories") if lines else []) or []:
            text = f"{s.get('headline', '')} {s.get('what_happened', '')}"
            if len(head & _words(s.get("headline", ""))) >= 2 or len(want & _words(text)) >= 4:
                out.append({"day": p.stem, "headline": s.get("headline", ""),
                            "what": (s.get("what_happened") or "")[:400]})
    return out[-limit:]


def _save(root: Path, rows: list) -> None:
    p = Path(root) / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def load_ledger(root: Path) -> list:
    p = Path(root) / LEDGER
    rows = []
    if p.exists():
        for ln in p.read_text("utf-8").splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
    return rows


def score_due(root: Path, llm, system: str, on: str, log=print, extend_days: int = DEFAULT_CHECK_DAYS) -> list:
    """Score every open position whose check date has come. "too early" moves its check date on (at most twice)."""
    from .stages import _ask, _one_line, prompt
    tmpl, version = prompt("score_position")
    rows = load_ledger(root)
    done = []
    for r in rows:
        if r.get("status") != "open" or r.get("check", "9999") > on:
            continue
        later = later_stories(root, r)
        lines = "\n".join(f"[{i}] {x['day']} · {x['headline']}: {x['what']}" for i, x in enumerate(later, 1)) or "(none)"
        user = (tmpl.replace("{{day}}", r["day"]).replace("{{headline}}", r.get("headline", ""))
                .replace("{{view}}", r.get("view_name", "")).replace("{{position}}", r.get("position", ""))
                .replace("{{changes}}", r.get("changes_our_mind", "") or "not stated").replace("{{later}}", lines))
        try:
            out = _ask(llm, system, user, 400)
        except Exception as e:  # noqa: BLE001
            log(f"positions: scoring {r['day']} {r.get('key', '')} failed: {e}"[:200])
            continue
        v = str(out.get("verdict", "")).lower().strip()
        if v not in ("right", "wrong", "mixed", "too early"):
            continue
        refs = [int(x) for x in (out.get("refs") or []) if str(x).isdigit() and 1 <= int(x) <= len(later)]
        r.setdefault("history", []).append({"on": on, "verdict": v, "why": _one_line(str(out.get("why") or ""))[:300],
                                            "evidence": [later[i - 1] for i in refs][:4], "prompt": version})
        if v == "too early" and len([h for h in r["history"] if h["verdict"] == "too early"]) <= 2:
            r["check"] = (dt.date.fromisoformat(on) + dt.timedelta(days=extend_days)).isoformat()
        else:
            r.update({"status": "scored", "verdict": v, "scored_on": on, "why": r["history"][-1]["why"]})
        done.append(r)
    if done:
        _save(root, rows)
    return done


def weekly_due(today: dt.date) -> bool:
    return today.weekday() == 6                 # Sundays, after the email
