"""The dashboard's home screen (Steven, 2026-11-01: "pertinent information front and centre, the rest available but
not cluttering"). Four blocks, each computed from files the pipeline already writes, each safe on its own:

    needs(root, cfg, today)    what is waiting on Steven now (empty = nothing to do)
    edition(root, cfg, today)  today's edition: built, held, sent, posted, re-recorded, corrected
    tomorrow(root, today)      tomorrow's deep dive and what is up next
    health(root)               the critic score against the field, the release, sources failing
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def _jsonl(p: Path) -> list:
    out = []
    try:
        for ln in p.read_text("utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - one block failing never blanks the page
        return default


def needs(root: Path, cfg: dict, today: str, now: dt.datetime | None = None) -> list:
    """[{level: 'act'|'look', text, href}] most urgent first."""
    now = now or dt.datetime.now()
    out = []

    def gate():
        from pipeline import release
        ok, _ = release.check_approval(root)
        if not ok:
            files = release.changed_sensitive(root)[:4]
            out.append({"level": "act", "href": "/control",
                        "text": "Protected files changed outside a release (" + (", ".join(files) or "see Control")
                                + "): approve, or the next edition is held",
                        "button": {"recipe": "approve", "label": "Approve", "note": True}})
    _safe(gate, None)

    def queue():
        from pipeline import runner
        for p in sorted(runner.qdir(root, "waiting").glob("*.json")):
            j = json.loads(p.read_text("utf-8"))
            out.append({"level": "act", "href": "/control", "text": f"Approval waiting: {j.get('recipe')} ({j.get('id')})"})
        for p in sorted(runner.qdir(root, "pending").glob("*.json")):
            j = json.loads(p.read_text("utf-8"))
            if j.get("deferred"):
                out.append({"level": "look", "href": "/control",
                            "text": f"Queued, waiting: {j.get('recipe')} ({j['deferred'][:80]})"})
    _safe(queue, None)

    def sent():
        from pipeline import mailer
        built = (root / "briefings" / f"{today}.md").exists()
        if built and today not in mailer.sent_days(root) and now.hour >= 7:
            from pipeline import takes as _t
            waiting = _t.waiting(root, today)
            out.insert(0, {"level": "act", "href": f"/briefings/{today}",
                           "text": "Today's edition is waiting for your takes" if waiting else "Today's edition is built but not emailed",
                           "button": {"recipe": "takes-done", "label": "Release it now"} if waiting
                           else {"recipe": "send-held", "label": "Send it now"}})
    _safe(sent, None)

    def takes():
        st = json.loads((root / "data" / "takes" / f"{today}.json").read_text("utf-8"))
        for h in st.get("held") or []:
            out.append({"level": "act", "href": f"/briefings/{today}",
                        "text": f"Take held ({h.get('slot')}): {'; '.join(h.get('why') or [])[:90]}"})
    _safe(takes, None)

    def checks():
        from pipeline import audit
        tm = (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()
        for day, label in ((tm, "tomorrow's deep dive"), (today, "today's deep dive")):
            n = len(audit.load_deepdive_check(root, day).get("held") or [])
            if n:
                out.append({"level": "look", "href": "/deep-dives", "text": f"{n} fact-check item(s) to look at in {label}"})
                break
    _safe(checks, None)

    def feedback():
        seen = json.loads((root / "data" / "state" / "feedback-seen.json").read_text("utf-8"))
        n = sum(1 for v in (seen.values() if isinstance(seen, dict) else []) if isinstance(v, dict) and v.get("status") == "new")
        if n:
            out.append({"level": "look", "href": "/feedback", "text": f"{n} new reader feedback"})
    _safe(feedback, None)
    return out


def edition(root: Path, cfg: dict, today: str) -> dict:
    md = root / "briefings" / f"{today}.md"
    e = {"day": today, "built": md.exists(), "title": "", "top": []}
    if e["built"]:
        text = md.read_text("utf-8")
        e["title"] = next((ln[2:] for ln in text.splitlines() if ln.startswith("# ")), today)
        import re
        head = text.split("## Must read")[0]
        e["top"] = re.findall(r"^- \*\*(.+?)\*\*", head, re.M)[:5]
    sends = [r for r in _jsonl(root / "data" / "email-log.jsonl") if r.get("day") == today and r.get("ok") and not r.get("test")]
    e["email"] = {"at": sends[-1]["at"][11:16], "sent": sends[-1].get("sent")} if sends else None
    posts = [r for r in _jsonl(root / "data" / "state" / "slack-posts.jsonl") if r.get("day") == today and r.get("kind") == "main"]
    e["slack"] = posts[-1]["at"][11:16] if posts else None
    e["site"] = _safe(lambda: __import__("pipeline.shipped", fromlist=["x"]).is_shipped(root, today), False)
    e["corrections"] = [c for c in _jsonl(root / "data" / "state" / "corrections.jsonl") if c.get("day") == today]
    e["takes"] = _safe(lambda: len(json.loads((root / "data" / "takes" / f"{today}.json").read_text("utf-8"))
                                   .get("published") or []), 0)
    runs = _jsonl(root / "data" / "runs.jsonl")
    last = next((r for r in reversed(runs) if r.get("day") == today and not r.get("experiment")), None)
    e["run"] = {"status": last.get("status"), "id": last.get("run_id")} if last else None
    dd = _safe(lambda: __import__("pipeline.deepdive", fromlist=["x"]).latest(root, today), None)
    e["deepdive"] = {"title": dd.get("title"), "status": dd.get("status")} if dd else None
    # one edition flow (11-03): built -> takes -> site -> email -> Slack, and the one thing to press when it's stuck
    waiting = _safe(lambda: __import__("pipeline.takes", fromlist=["x"]).waiting(root, today), False)
    steps = [("Built", e["built"]), ("Takes", e["built"] and not waiting), ("Site", bool(e["site"])),
             ("Email", bool(e["email"])), ("Slack", bool(e["slack"]))]
    e["flow"] = [{"name": n, "done": bool(d)} for n, d in steps]
    nxt = next((n for n, d in steps if not d), "")
    e["next"] = ({"text": "Waiting for your takes (or the cutoff)", "recipe": "takes-done", "label": "Release it now"}
                 if nxt == "Takes" else
                 {"text": "Built but not published and emailed", "recipe": "send-held", "label": "Send it now"}
                 if nxt in ("Site", "Email") and e["built"] else None)
    ov = [r for r in runs if r.get("kind") == "overnight" and str(r.get("started", "")) >= f"{(dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()}T23"]
    e["overnight"] = {"runs": len(ov), "items": sum(((r.get("stages") or {}).get("filter") or {}).get("items_in", 0) or 0 for r in ov)}
    try:
        r = json.loads((root / "data" / "state" / "rehearsal.json").read_text("utf-8"))
        e["rehearsal"] = r.get("at", "")[:16].replace("T", " ")
    except (OSError, ValueError):
        e["rehearsal"] = ""
    return e


def tomorrow(root: Path, today: str) -> dict:
    from pipeline import deepdive
    tm = (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()
    rec = _safe(lambda: deepdive.latest(root, tm), None)
    sched = _safe(lambda: deepdive.scheduled_for(root, tm), None)
    up = _safe(lambda: deepdive.queued(root)[:3], [])
    return {"day": tm, "draft": {"title": rec.get("title"), "status": rec.get("status")} if rec else None,
            "planned": (sched or {}).get("topic"), "up_next": [q.get("title") or q.get("topic") for q in up]}


def health(root: Path) -> dict:
    from pipeline import critic
    h = {}
    weeks = _safe(lambda: critic.history(root), [])
    if weeks:
        w = weeks[-1]
        field = sorted([s["overall"] for s in w.get("shows", [])] + [w["ours"]["overall"]], reverse=True)
        h["score"] = {"date": w["date"], "ours": w["ours"]["overall"], "rank": field.index(w["ours"]["overall"]) + 1,
                      "of": len(field), "best": max(s["overall"] for s in w.get("shows", []) or [{"overall": 0}]),
                      "prev": weeks[-2]["ours"]["overall"] if len(weeks) > 1 else None}
    rel = _jsonl(root / "data" / "state" / "releases.jsonl")
    if rel:
        h["release"] = {"version": rel[-1].get("version"), "at": rel[-1].get("at", "")[:16].replace("T", " ")}
    runs = _jsonl(root / "data" / "runs.jsonl")
    last = next((r for r in reversed(runs) if not r.get("experiment")
                 and (r.get("stages", {}).get("fetch") or {}).get("per_source")), None)
    if last:
        per = (last.get("stages", {}).get("fetch") or {}).get("per_source") or []
        h["failing"] = [s.get("person") for s in per if s.get("status") != "ok"][:8]
        h["sources"] = len(per)
    return h
