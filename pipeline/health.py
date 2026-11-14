"""The system status board (Steven, 2026-11-11: "an at a glance status showing what is live and is broken").

One tile per link in the chain, each green / amber / red with a timestamp and a one-line reason, from the records the
pipeline already keeps (runs.jsonl, the queue's status.json, shipped.json, the email and Slack logs, takes state,
the release approvals, the morning-check log). Nothing here calls the network: the board is what this Mac knows.
Shown at the top of the dashboard's home page, printed by `./np health`, and summed up in one line for the daily
report: "All well as of 09:40" or "2 problems: Runner, Podcast".
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

OK, WARN, BAD, OFF = "ok", "warn", "bad", "off"


def _jsonl(p: Path) -> list:
    try:
        return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def _json(p: Path, default):
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _hm(ts: str) -> str:
    return (ts or "")[11:16]


def _age_min(ts: str, now: dt.datetime) -> float | None:
    try:
        t = dt.datetime.fromisoformat(ts).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
    return (now.replace(tzinfo=None) - t).total_seconds() / 60


def tile(name: str, state: str, note: str = "", at: str = "", href: str = "", action: dict | None = None) -> dict:
    return {"name": name, "state": state, "note": note[:120], "at": at, "href": href, "action": action}


def board(root: Path, cfg: dict, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    today = now.date().isoformat()
    tiles = []
    runs = [r for r in _jsonl(root / "data" / "runs.jsonl") if not r.get("experiment")]
    today_runs = [r for r in runs if r.get("day") == today]
    editions = [r for r in today_runs if r.get("kind") != "overnight"]
    sched = [str(t) for t in (cfg.get("schedule") or {}).get("times", ["05:00"])]
    first = dt.datetime.combine(now.date(), dt.time(*(int(x) for x in sched[0].split(":"))))

    # --- Ingestion: the newest fetch (any run), its failures, and whether items keep arriving
    fetched = [r for r in runs if (r.get("stages") or {}).get("fetch", {}).get("per_source")]
    if fetched:
        f = fetched[-1]
        st = f["stages"]["fetch"]
        per = st.get("per_source") or []
        failed = [s.get("person") for s in per if s.get("status") != "ok"]
        age = _age_min(f.get("ended") or f.get("started", ""), now)
        if per and len(failed) >= max(3, len(per) // 2):
            tiles.append(tile("Ingestion", BAD, f"{len(failed)} of {len(per)} sources failed on the last fetch"
                              + (" (network?)" if len(failed) == len(per) else ""), _hm(f.get("started", "")), "/sources"))
        elif age is not None and age > 20 * 60:
            tiles.append(tile("Ingestion", WARN, f"last fetch {age / 60:.0f} h ago", _hm(f.get("started", "")), "/sources"))
        else:
            tiles.append(tile("Ingestion", OK, f"{st.get('items_new', 0)} new item(s), {len(failed)} source(s) failing",
                              _hm(f.get("started", "")), "/sources"))
    else:
        tiles.append(tile("Ingestion", WARN, "no fetch on record", "", "/sources"))

    # --- Today's run
    if editions:
        r = editions[-1]
        s = r.get("status")
        state = OK if s == "ok" else WARN if s == "partial" else BAD
        tiles.append(tile("Today's run", state, f"{s}: {r.get('run_id', '')}", _hm(r.get("started", "")), "/runs"))
    elif now < first:
        tiles.append(tile("Today's run", OFF, f"scheduled {sched[0]}", "", "/schedule"))
    elif now < first + dt.timedelta(hours=1, minutes=30):
        tiles.append(tile("Today's run", WARN, "not finished yet", "", "/runs"))
    else:
        tiles.append(tile("Today's run", BAD, f"no run today; it was due at {sched[0]}", "", "/runs",
                          {"recipe": "send-held", "label": "Run it now"}))

    # --- Edition: built → held → site → email
    md = root / "briefings" / f"{today}.md"
    try:
        from . import takes, shipped
        waiting = takes.waiting(root, today)
        tstate = takes.state(root, today)
        live = shipped.is_shipped(root, today)
    except Exception:  # noqa: BLE001
        waiting, tstate, live = False, {}, False
    sends = [x for x in _jsonl(root / "data" / "email-log.jsonl") if x.get("day") == today and x.get("ok") and not x.get("test")]
    if not md.exists():
        tiles.append(tile("Edition", OFF if now < first else WARN, "not built yet", "", "/briefings"))
    elif waiting:
        try:
            end = takes._cutoff(cfg, today, root).strftime("%H:%M")
        except Exception:  # noqa: BLE001
            end = (cfg.get("takes") or {}).get("cutoff", "")
        tiles.append(tile("Edition", OK, f"built; held for your takes until {end}", _hm(tstate.get("pending_since", "")),
                          "/briefings", {"recipe": "takes-done", "label": "Release now"}))
    elif live and sends:
        tiles.append(tile("Edition", OK, f"live and emailed to {sends[-1].get('sent', '?')}", _hm(sends[-1].get("at", "")),
                          f"/briefings/{today}"))
    elif live:
        tiles.append(tile("Edition", WARN, "page is live, email not sent", "", "/briefings",
                          {"recipe": "send-held", "label": "Send it"}))
    else:
        rel = tstate.get("released_at", "")
        age = _age_min(rel, now) if rel else None
        tiles.append(tile("Edition", BAD if age is not None and age > 20 else WARN, "built but not published",
                          _hm(rel), "/briefings", {"recipe": "send-held", "label": "Send it"}))

    # --- Podcast: today's episode exists and the public feed knows the day
    mp3 = root / "briefings" / f"{today}.mp3"
    if mp3.exists():
        tiles.append(tile("Podcast", OK if live else WARN, f"{mp3.stat().st_size // 1_000_000} MB"
                          + ("" if live else ", not on the feed yet"), dt.datetime.fromtimestamp(mp3.stat().st_mtime).strftime("%H:%M"),
                          f"/briefings/{today}"))
    else:
        tiles.append(tile("Podcast", OFF if not md.exists() else WARN, "no episode yet", "", "/briefings"))

    # --- Slack
    posts = [x for x in _jsonl(root / "data" / "state" / "slack-posts.jsonl") if x.get("day") == today and x.get("kind") == "main"]
    if posts:
        tiles.append(tile("Slack", OK, "morning post up", _hm(posts[-1].get("at", "")), "/control"))
    else:
        tiles.append(tile("Slack", OK if not sends else WARN, "not posted" + (" (edition not out)" if not sends else ""), "", "/control"))

    # --- Runner: the queue's heartbeat
    q = _json(root / "data" / "queue" / "status.json", {})
    age = _age_min(q.get("at", ""), now)
    failed_jobs = [j for j in (q.get("last") or [])[:5] if j.get("status") not in ("ok", None)]
    if age is None:
        tiles.append(tile("Runner", BAD, "no heartbeat on record", "", "/queue", {"recipe": "service-install", "label": "Restart"}))
    elif age > 5:
        tiles.append(tile("Runner", BAD, f"last tick {age:.0f} min ago", _hm(q.get("at", "")), "/queue",
                          {"recipe": "service-install", "label": "Restart"}))
    elif failed_jobs:
        tiles.append(tile("Runner", WARN, f"last job failed: {failed_jobs[0].get('recipe')} ({failed_jobs[0].get('detail', '')})",
                          _hm(q.get("at", "")), "/queue"))
    else:
        tiles.append(tile("Runner", OK, f"{len(q.get('pending') or [])} waiting", _hm(q.get("at", "")), "/queue"))

    # --- Release gate: approval current, protected live-content files awaiting approval
    try:
        from . import release
        ok, why = release.check_approval(root) if release.approvals(root) else (True, "no approvals on record")
    except Exception as e:  # noqa: BLE001
        ok, why = True, str(e)
    watch = _json(root / "data" / "state" / "protected-watch.json", {})
    pending_files = watch.get("files") or []
    rel = _jsonl(root / "data" / "state" / "releases.jsonl")
    ver = (rel[-1].get("version") if rel else "") or ""
    if not ok:                                   # the watch file only says which files; check_approval is the truth
        tiles.append(tile("Release gate", BAD, "protected files changed since the last approval: "
                          + (", ".join(pending_files)[:70] or "see release-check"), _hm(watch.get("at", "")), "/",
                          {"recipe": "approve", "label": "Approve"}))
    else:
        tiles.append(tile("Release gate", OK, f"v{ver} in production" if ver else "approval current",
                          _hm(rel[-1].get("at", "")) if rel else "", "/runs"))

    # --- Takes
    if tstate.get("pending") or tstate.get("released_at"):
        n = len(tstate.get("published") or [])
        tiles.append(tile("Takes", OK, f"{n} published" + ("; waiting for more" if waiting else ""), _hm(tstate.get("emailed_at", "")), "/briefings"))
    else:
        tiles.append(tile("Takes", OFF, "no takes email yet today", "", "/briefings"))

    # --- Morning check (v0.2.61)
    mc = [x for x in _jsonl(root / "data" / "state" / "morning.jsonl") if x.get("day") == today]
    if mc:
        m = mc[-1]
        if m.get("rebuilt") is False:
            tiles.append(tile("Morning check", BAD, "rebuild failed; the 05:00 edition stands", _hm(m.get("at", "")), "/selection"))
        elif m.get("rebuild"):
            tiles.append(tile("Morning check", OK, f"rebuilt for: {m.get('headline', '')}", _hm(m.get("at", "")), "/selection"))
        elif m.get("skipped"):
            tiles.append(tile("Morning check", OK, f"skipped: {m['skipped']}", _hm(m.get("at", "")), "/selection"))
        else:
            tiles.append(tile("Morning check", OK, f"{m.get('new_strong', 0)} strong new item(s); edition stands", _hm(m.get("at", "")), "/selection"))
    else:
        tiles.append(tile("Morning check", OFF, "not run today", "", "/selection"))

    # --- Specials
    try:
        from . import special
        sp = special.status(root)
    except Exception:  # noqa: BLE001
        sp = []
    sp_today = [x for x in sp if x["day"] == today]
    if sp_today:
        x = sp_today[0]
        tiles.append(tile("Special", OK if x["status"] in ("released", "recorded") or x["emailed"] else WARN,
                          f"{x['status']}: {x['title'][:60]}" + (" · emailed" if x["emailed"] else ""), "", "/deep-dives"))

    # --- Clock: the Mac's zone vs schedule.timezone (Steven travelling, 11-11)
    try:
        from . import clock
        note = clock.mismatch(cfg)
        if note:
            tiles.append(tile("Clock", WARN, note, "", "/schedule"))
    except Exception:  # noqa: BLE001
        pass

    problems = [t for t in tiles if t["state"] == BAD]
    warns = [t for t in tiles if t["state"] == WARN]
    if problems:
        headline = f"{len(problems)} problem{'s' if len(problems) > 1 else ''}: " + ", ".join(t["name"] for t in problems)
        if warns:
            headline += f" · {len(warns)} to watch"
    elif warns:
        headline = f"All running; {len(warns)} to watch: " + ", ".join(t["name"] for t in warns)
    else:
        headline = f"All well as of {now:%H:%M}"
    return {"tiles": tiles, "problems": len(problems), "warnings": len(warns), "headline": headline,
            "at": now.isoformat(timespec="seconds")}


def text(b: dict) -> str:
    mark = {OK: "ok  ", WARN: "WARN", BAD: "BAD ", OFF: "--  "}
    lines = [b["headline"]] + [f"  {mark[t['state']]} {t['name']:<14} {t['note']}" + (f"  ({t['at']})" if t["at"] else "")
                              for t in b["tiles"]]
    return "\n".join(lines)
