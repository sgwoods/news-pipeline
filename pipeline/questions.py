"""Open questions from the briefings (editorial.open_questions), with a status you keep on the Questions page.

Questions live in data/stories/<day>.jsonl (editorial). Their status lives in data/questions.json:
{qid: {"status": "open|answered|dropped", "note": "...", "updated": "..."}}.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from .archive import read_jsonl

STATUSES = ("open", "answered", "dropped")


def qid(day: str, q: str) -> str:
    return hashlib.sha1(f"{day}|{q}".encode()).hexdigest()[:10]


def load_state(root: Path) -> dict:
    try:
        return json.loads((root / "data" / "questions.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def set_status(root: Path, q: str, status: str, note: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(status)
    st = load_state(root)
    st[q] = {"status": status, "note": note[:500], "updated": dt.datetime.now().isoformat(timespec="seconds")}
    p = root / "data" / "questions.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return st[q]


def all_questions(root: Path) -> list:
    """Every question from the latest story record of each day, newest day first, with its status."""
    st = load_state(root)
    out = []
    d = root / "data" / "stories"
    for f in sorted(d.glob("????-??-??.jsonl"), reverse=True) if d.exists() else []:
        rows = read_jsonl(f)
        if not rows:
            continue
        rec = rows[-1]
        numbered = {s.get("n"): s for s in rec.get("stories", []) if s.get("n")}
        for q in (rec.get("editorial") or {}).get("open_questions") or []:
            i = qid(rec["day"], q["q"])
            out.append({**q, "id": i, "day": rec["day"], **st.get(i, {"status": "open", "note": ""}),
                        "stories": [numbered[n] for n in q.get("refs", []) if n in numbered]})
    return out
