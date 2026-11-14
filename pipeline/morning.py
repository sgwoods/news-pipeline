"""The 08:00 check while the edition is held for Steven's takes (selection review 2026-11-13, R4).

On 2026-11-12 the Huang resignation broke at 07:40, the edition had been written at 05:00, and Steven re-ran fetch,
reprocess and rebrief by hand from a Terminal during the hold. This does that automatically, with a judgement in
between: a light fetch (feeds, Bluesky, X — not the newsletters), the new items analysed, and one Claude call asking
whether anything would displace the lead or enter the top three. If yes: the cutoff is extended, Steven is told, and
the edition is rebuilt (cluster, selection, editorial, write) from everything known; the holder then records the
audio and releases as usual. If no: nothing changes. Off with morning.enabled: false."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def mcfg(cfg: dict) -> dict:
    m = cfg.get("morning") or {}
    return {"enabled": bool(m.get("enabled", True)), "min_importance": int(m.get("min_importance", 4)),
            "min_minutes_left": int(m.get("min_minutes_left", 35)), "extend_minutes": int(m.get("extend_minutes", 20))}


def current_must(root: Path, day: str) -> list:
    """[(n, headline)] of today's Must reads from the latest stories record."""
    from .archive import read_jsonl
    p = root / "data" / "stories" / f"{day}.jsonl"
    if not p.exists():
        return []
    recs = read_jsonl(p)
    stories = recs[-1].get("stories", []) if recs else []
    return [(s.get("n"), s.get("headline", "")) for s in sorted((s for s in stories if s.get("section") == "must"),
                                                              key=lambda s: s.get("n", 99))]


def new_items(root: Path, paths: dict, day: str, since: dt.datetime, min_importance: int) -> list:
    """Summary rows created since `since` (this check's analysis run), kept, with importance >= min_importance."""
    from .archive import read_jsonl
    sm = Path(paths.get("summaries", root / "data" / "summaries")) / f"{day}.jsonl"
    out, seen = [], set()
    for r in (read_jsonl(sm) if sm.exists() else []):
        if r.get("id") in seen or not r.get("keep"):
            continue
        created = r.get("created") or ""
        try:
            if dt.datetime.fromisoformat(created).replace(tzinfo=None) < since.replace(tzinfo=None):
                continue
        except ValueError:
            continue
        if int(r.get("importance") or 0) < min_importance:
            continue
        seen.add(r.get("id"))
        out.append(r)
    return out


def _block(r: dict) -> str:
    v = (r.get("critique_verdict") or (r.get("critique") or {}).get("verdict") or "")
    return (f"- [{r.get('person', '')}] {r.get('headline') or r.get('title', '')} — {str(r.get('claim', ''))[:220]} "
            f"(importance {r.get('importance')}{'; critique: ' + v if v else ''}; {r.get('url', '')})")


def judge(llm, system: str, must: list, items: list, log=None) -> dict:
    """One Claude call: {rebuild, headline, why}. Any failure means no rebuild."""
    from .stages import prompt, _ask
    tmpl, version = prompt("morning")
    user = (tmpl.replace("{{must}}", "\n".join(f"{n}. {h}" for n, h in must) or "(none)")
            .replace("{{items}}", "\n".join(_block(r) for r in items)))
    try:
        out = _ask(llm, system, user, 400) or {}
    except Exception as e:  # noqa: BLE001
        if log:
            log(f"morning check: the judgement call failed ({e}); no rebuild")
        return {"rebuild": False, "why": f"call failed: {e}"[:200], "version": version}
    return {"rebuild": bool(out.get("rebuild")), "headline": str(out.get("headline", ""))[:200],
            "why": str(out.get("why", ""))[:300], "version": version}


def record(root: Path, day: str, entry: dict) -> None:
    p = root / "data" / "state" / "morning.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), **entry},
                           ensure_ascii=False) + "\n")
