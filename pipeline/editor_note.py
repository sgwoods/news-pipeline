"""Steven's private evening note: tomorrow's deep dive, the new suggestions and watchlist mentions.

Sent once a day after the morning run, ONLY to email.test_to (Steven), through the same Apps Script as the
newsletter. It is a read-out: changes happen on the dashboard (Deep dives page: the top of Up next is what
airs next; Watchlist page). Nothing in it is published.
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
from pathlib import Path

STAMP = "data/state/editor-note.json"


def build(root: Path, cfg: dict, day: str, new_mentions: list | None = None) -> dict:
    from . import deepdive, watchlist
    port = (cfg.get("dashboard") or {}).get("port", 8765)
    dash = f"http://127.0.0.1:{port}"
    up = deepdive.queued(root)
    today_dd = next((r for r in reversed(deepdive.records(root)) if r.get("day") == day), None)
    sugg = sorted([x for x in deepdive.load_queue(root) if x["status"] == "suggested" and x.get("source_day") == day],
                  key=lambda x: -(x.get("strength") or 0))[:4]
    if new_mentions is None:
        since = (dt.datetime.now() - dt.timedelta(hours=24)).isoformat(timespec="seconds")
        new_mentions = [m for m in watchlist.mentions(root, 3) if m.get("found", "") >= since]
    L, H = [], []

    def sec(title):
        L.append(f"\n{title.upper()}")
        H.append(f'<h3 style="margin:18px 0 6px;font-size:15px">{htmllib.escape(title)}</h3>')

    page = "{{SCRIPT}}?action=queue&t={{OWNER}}"       # filled in by the mail script, for Steven's address only
    from urllib.parse import quote
    LABELS = {"next": "Make this next", "up": "↑ Move up", "down": "↓ Move down", "queue": "＋ Add to Up next",
              "take": "✍ Add your take", "dismiss": "✕ Dismiss", "suggest": "Suggest as a deep dive"}

    def link(op, qid="", topic=""):
        return page + (f"&pick={qid}" if qid else "") + f"&op={op}" + (f"&topic={quote(topic[:200])}" if topic else "")

    def item(text, sub="", ops=(), qid="", take="", topic=""):
        """Every topic gets its own buttons: each opens the queue page with that one change ready (one tap)."""
        links = [(LABELS[o], link(o, qid, topic)) for o in ops]
        L.append(f"- {text}" + (f"\n  {sub}" if sub else "") + (f"\n  Your take: {take}" if take else "")
                 + "".join(f"\n  {lab}: {u}" for lab, u in links))
        btns = "".join(f'<a href="{htmllib.escape(u)}" style="display:inline-block;margin:4px 6px 0 0;padding:5px 12px;'
                       f'border-radius:999px;background:{"#0b6b46" if o in ("next", "take") else "#374151"};color:#fff;'
                       f'text-decoration:none;font-size:13px">{htmllib.escape(lab)}</a>'
                       for o, (lab, u) in zip(ops, links))
        H.append(f'<p style="margin:0 0 10px"><b>{htmllib.escape(text)}</b>'
                 + (f'<br><span style="color:#555">{htmllib.escape(sub)}</span>' if sub else "")
                 + (f'<br><span style="color:#0b6b46">Your take: {htmllib.escape(take)}</span>' if take else "")
                 + (f"<br>{btns}" if btns else "") + "</p>")

    nxt = up[0] if up else None
    sec("Tomorrow's deep dive")
    if nxt:
        item(nxt["topic"], nxt.get("why_today") or nxt.get("angle", ""),
             ("take", "down", "dismiss") if len(up) > 1 else ("take", "dismiss"), nxt["id"], nxt.get("take", ""))
        if nxt.get("auto"):
            L.append("  (Claude's pick: nothing was queued. Change it below or on the queue page.)")
            H.append('<p style="margin:0 0 8px;color:#555">Claude\'s pick: nothing was queued. Change it below or on the queue page.</p>')
        H.append('<p style="margin:0 0 8px;color:#555;font-size:13px">Your take is read verbatim as "Steven\'s take" at the '
                 'end of the deep dive (site and podcast), after the same privacy check as your morning takes.</p>')
    else:
        item("Nothing queued yet", "Tomorrow's run picks the best of the morning's suggestions.")
    if len(up) > 1:
        sec("Then")
        for n, x in enumerate(up[1:8], 1):
            ops = ("next",) + (("up",) if n > 1 else ()) + (("down",) if n < len(up) - 1 else ()) + ("take", "dismiss")
            item(x["topic"], x.get("why_today", ""), ops, x["id"], x.get("take", ""))
    if sugg:
        sec("New suggestions today")
        for x in sugg:
            item(f"{x['topic']} (strength {x.get('strength', '?')})", x.get("why_today", ""),
                 ("next", "queue", "take", "dismiss"), x["id"], x.get("take", ""))
    if today_dd:
        sec("Today's deep dive")
        t = today_dd.get("title") or (today_dd.get("pick") or {}).get("topic") or "none"
        item(t, f"{today_dd.get('status')}" + (f": {today_dd.get('reason')}" if today_dd.get("reason") else ""),
             ("suggest",), topic=f"Follow-up: {t}" if t != "none" else "")
    if new_mentions:
        sec("Watchlist: new mentions")
        for m in new_mentions[:12]:
            item(f"{m['company']}: {m['title'] or m['url']}", f"{m['source']} · {m.get('via', '')} · {m['url']}",
                 ("suggest",), topic=f"{m['company']}: {m['title'] or ''}".strip(": "))
    L.append(f"\nReorder, dismiss or suggest topics (from any device): {page}")
    L.append(f"On your Mac: {dash}/deep-dives · Watchlist: {dash}/watchlist")
    H.append(f'<p style="margin:16px 0 0"><a href="{htmllib.escape(page)}" style="display:inline-block;padding:9px 16px;'
             f'border-radius:999px;background:#111;color:#fff;text-decoration:none;font-size:14px">'
             f'Reorder or suggest topics</a></p>'
             f'<p style="margin:12px 0 0;color:#555;font-size:13px">Changes apply at the next morning run. On your Mac: '
             f'<a href="{dash}/deep-dives">Deep dives</a> · <a href="{dash}/watchlist">Watchlist</a>. '
             f'Only you receive this note.</p>')
    d = dt.date.fromisoformat(day) + dt.timedelta(days=1)
    subject = f"AI Briefing · for you: tomorrow's deep dive ({d.strftime('%a %b')} {d.day})" + (f": {nxt['topic']}" if nxt else "")
    html = ('<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
            'max-width:640px;margin:0 auto;padding:16px;color:#111">' + "".join(H) + "</body></html>")
    return {"subject": subject[:150], "html": html, "text": "\n".join(L).strip()}


def sent_today(root: Path, day: str) -> bool:
    try:
        return json.loads((root / STAMP).read_text("utf-8")).get("day") == day
    except (OSError, json.JSONDecodeError):
        return False


def send(root: Path, cfg: dict, day: str, new_mentions: list | None = None, force: bool = False) -> dict:
    from .mailer import call, ecfg
    to = ecfg(cfg).get("test_to") or ""
    if not to:
        return {"ok": False, "error": "email.test_to is not set"}
    if sent_today(root, day) and not force:
        return {"ok": True, "skipped": "already sent today"}
    msg = build(root, cfg, day, new_mentions)
    from .mailer import defuse
    page = "{{SCRIPT}}?action=queue&t={{OWNER}}"
    for k in ("html", "text"):                   # content defused; only the note's own queue links keep placeholders
        msg[k] = defuse(msg[k].replace(page, "\x00PAGE\x00").replace(page.replace("&", "&amp;"), "\x00PAGEH\x00")) \
            .replace("\x00PAGE\x00", page).replace("\x00PAGEH\x00", page.replace("&", "&amp;"))
    try:                                         # the queue page shows this snapshot
        from .deepdive import snapshot
        call(cfg, "setqueue", items=json.dumps(snapshot(root), ensure_ascii=False))
    except Exception:  # noqa: BLE001 - the note still goes out; the page shows the previous snapshot
        pass
    out = call(cfg, "send", subject=msg["subject"], html=msg["html"], text=msg["text"], to=to)
    p = root / STAMP
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "ok": bool(out.get("ok"))}) + "\n")
    return {"ok": bool(out.get("ok")), "subject": msg["subject"]}
