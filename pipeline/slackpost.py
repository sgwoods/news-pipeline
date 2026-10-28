"""The morning post in the team channel (Steven, 2026-10-28): when the email goes out, one short branded post in
cto-musings: the day's leads, one of Steven's takes in his words, the deep dive, and the links, with the day's
card (pipeline/card.py) attached so it reads as the briefing, not as a text message.

Posted by the app's bot user ("AI Briefing"), never as Steven: the bot token (SLACK_BOT_TOKEN, Keychain) needs
chat:write, files:write and channels:read, and the bot must be invited to the channel. The pipeline's Slack reading
(slacksource.py) ignores bot messages, so the post is never ingested as a story. Every post goes through the
release gate like any other outbound step; staging never posts. Content is the published edition only.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

API = "https://slack.com/api"
MAX_TAKE_WORDS = 45


def pcfg(cfg: dict) -> dict:
    return {"enabled": False, "channel": (cfg.get("slack") or {}).get("channel", ""), **((cfg.get("slack") or {}).get("post") or {})}


def token() -> str:
    from .vault import get
    return get("SLACK_BOT_TOKEN")


def _api(client, method: str, tok: str, **params) -> dict:
    r = client.post(f"{API}/{method}", data=params, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    out = r.json()
    if not out.get("ok"):
        raise RuntimeError(f"slack {method}: {out.get('error', out)}")
    return out


def _notes(root: Path, day: str) -> dict:
    try:
        return json.loads((root / "data" / "commentary" / f"{day}.json").read_text("utf-8")).get("notes", {})
    except (OSError, ValueError):
        return {}


def _dd_info(root: Path, cfg: dict, day: str) -> dict:
    """{title, summary, line, take, url, minutes} of DAY's published deep dive, or {}."""
    from . import deepdive
    from .mailer import deep_dive_for
    info = deep_dive_for(root, cfg, day)
    if not info:
        return {}
    summary = info.get("summary") or ""
    line = re.split(r"(?<=[.!?])\s+", summary)[0] if summary else ""
    take = ""
    rec = deepdive.latest(root, day) or {}
    qid = (rec.get("pick") or {}).get("queue_id")
    if qid:
        it = next((x for x in deepdive.load_queue(root) if x.get("id") == qid), None)
        take = str((it or {}).get("take") or "")
    return {"title": info["title"].removeprefix("Deep dive: "), "summary": summary, "line": line, "take": take,
            "url": info["url"], "minutes": int(info.get("minutes") or 0)}


def _dd(root: Path, cfg: dict, day: str) -> tuple:
    """(title, first line of the summary, Steven's take on it, url) or ('', '', '', '')."""
    i = _dd_info(root, cfg, day)
    if not i:
        return "", "", "", ""
    return i["title"], i["line"], i["take"], i["url"]


def build(root: Path, cfg: dict, day: str) -> dict:
    """{"text": mrkdwn, "card": Path or None, "take": str}: what the post says, from the published edition."""
    from . import card
    md = (root / cfg["paths"]["briefings"] / f"{day}.md").read_text("utf-8")
    notes = _notes(root, day)
    title, line, dd_take, dd_url = _dd(root, cfg, day)
    base = ((cfg.get("publish") or {}).get("site_url") or "").rstrip("/")
    date = dt.date.fromisoformat(day).strftime("%a %b %-d")
    leads = card.leads(md, 3)
    take, where = card.pick_take(notes, dd_take)
    L = [f"*AI Briefing · {date}*"]
    if leads:
        L.append(" · ".join(leads) + ".")
    if take:
        L.append(f"> _Steven's take{' on ' + where if where and where != 'The day overall' else ''}:_ “{take}”")
    if title:
        L.append(f":headphones: *Deep dive:* {title}" + (f" — {line}" if line else ""))
    links = [f"<{base}/{day}/|Read>", f"<{base}/{day}/|Listen>" if not title else f"<{dd_url}|Listen to the deep dive>",
             f"<{base}/#email|Subscribe>"]
    L.append("  ·  ".join(links))
    out = {"text": "\n".join(L), "card": None, "take": take}
    try:
        out["card"] = card.render(root, day, md, notes, title, line, dd_take)
    except Exception as e:  # noqa: BLE001 - the text post still goes out
        out["card_error"] = f"{type(e).__name__}: {e}"[:160]
    return out


def channel_id(client, tok: str, name: str) -> str:
    cursor = ""
    for _ in range(20):
        r = _api(client, "conversations.list", tok, types="public_channel,private_channel", limit="200", cursor=cursor)
        for c in r.get("channels", []):
            if c.get("name") == name.lstrip("#"):
                return c["id"]
        cursor = (r.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    raise RuntimeError(f"channel {name} not found (is the bot invited to it?)")


def build_dd(root: Path, cfg: dict, day: str) -> dict:
    """The thread reply for the deep dive: {"text", "card"} or {} when there is none."""
    from . import card
    i = _dd_info(root, cfg, day)
    if not i:
        return {}
    take = i["take"]
    if take and len(take.split()) > 60:
        take = " ".join(take.split()[:60]) + "\u2026"
    L = [f":headphones: *Deep dive · {i['title']}*" + (f"  ·  {i['minutes']} min" if i["minutes"] else "")]
    if i["summary"]:
        L.append(i["summary"])
    if take:
        L.append(f"> _Steven's take:_ \u201c{take}\u201d")
    L.append(f"<{i['url']}|Read the deep dive>  ·  <{i['url']}|Listen>")
    out = {"text": "\n".join(L), "card": None}
    try:
        out["card"] = card.render_dd(root, day, i["title"], i["summary"], i["take"], i["minutes"])
    except Exception as e:  # noqa: BLE001
        out["card_error"] = f"{type(e).__name__}: {e}"[:160]
    return out


def _share_ts(done: dict) -> str:
    """The message ts of a file share (files.completeUploadExternal), for threading under it."""
    try:
        shares = (done.get("files") or [{}])[0].get("shares") or {}
        for kind in ("public", "private"):
            for rows in (shares.get(kind) or {}).values():
                if rows and rows[0].get("ts"):
                    return str(rows[0]["ts"])
    except (AttributeError, TypeError):
        pass
    return ""


def _send(client, tok: str, ch: str, text: str, card_path, title: str, thread_ts: str = "") -> str:
    """Post text with the card as a file share (or text alone); -> the message ts ('' if unknown)."""
    if card_path and Path(card_path).is_file():
        data = Path(card_path).read_bytes()
        up = _api(client, "files.getUploadURLExternal", tok, filename=Path(card_path).name, length=str(len(data)))
        r = client.post(up["upload_url"], content=data, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"slack upload: HTTP {r.status_code}")
        body = {"files": [{"id": up["file_id"], "title": title}], "channel_id": ch, "initial_comment": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        done = client.post(f"{API}/files.completeUploadExternal", headers={"Authorization": f"Bearer {tok}"},
                           json=body, timeout=30).json()
        if not done.get("ok"):
            raise RuntimeError(f"slack completeUploadExternal: {done.get('error', done)}")
        return _share_ts(done)
    params = {"channel": ch, "text": text, "unfurl_links": "false"}
    if thread_ts:
        params["thread_ts"] = thread_ts
    return str(_api(client, "chat.postMessage", tok, **params).get("ts", ""))


def _stamps(root: Path) -> list:
    p = root / "data" / "state" / "slack-posts.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]


def _stamp(root: Path, row: dict) -> None:
    p = root / "data" / "state" / "slack-posts.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def post_dd(root: Path, cfg: dict, day: str, log=print, client=None) -> dict:
    """The deep-dive reply in the morning post's thread (once per day; needs that post's ts)."""
    from .release import require
    p = pcfg(cfg)
    if not p.get("enabled"):
        return {"ok": False, "skipped": "slack.post.enabled is off"}
    tok = token()
    if not tok:
        return {"ok": False, "skipped": "no SLACK_BOT_TOKEN"}
    rows = _stamps(root)
    main = next((r for r in rows if r.get("day") == day and r.get("kind", "main") == "main"), None)
    if not main:
        return {"ok": False, "skipped": f"no morning post for {day} yet"}
    if any(r.get("day") == day and r.get("kind") == "deepdive" for r in rows):
        return {"ok": False, "skipped": f"deep dive already posted for {day}"}
    msg = build_dd(root, cfg, day)
    if not msg:
        return {"ok": False, "skipped": f"no published deep dive for {day}"}
    require(root, cfg, "slack post", log)
    import httpx
    client = client or httpx.Client()
    ch = main.get("channel_id") or channel_id(client, tok, p["channel"])
    ts = _send(client, tok, ch, msg["text"], msg.get("card"), f"AI Briefing · deep dive · {day}", thread_ts=main.get("ts", ""))
    _stamp(root, {"day": day, "kind": "deepdive", "at": dt.datetime.now().isoformat(timespec="seconds"),
                  "channel": p["channel"], "channel_id": ch, "ts": ts, "card": bool(msg.get("card")),
                  "thread": bool(main.get("ts"))})
    log(f"Slack: posted the {day} deep dive" + (" in the thread" if main.get("ts") else " (no thread: the morning post's ts is unknown)"))
    return {"ok": True, "ts": ts}


def post(root: Path, cfg: dict, day: str, log=print, client=None, dry: bool = False) -> dict:
    """Post DAY's card and text to the channel, then the deep dive as a reply in its thread. Gated
    (release.require); never in staging; once per day."""
    from .release import require
    p = pcfg(cfg)
    if not p.get("enabled"):
        return {"ok": False, "skipped": "slack.post.enabled is off"}
    tok = token()
    if not tok:
        return {"ok": False, "skipped": "no SLACK_BOT_TOKEN (queue the slack-setup job)"}
    if any(r.get("day") == day and r.get("kind", "main") == "main" for r in _stamps(root)):
        dd = post_dd(root, cfg, day, log, client)                  # the reply may still be due
        return {"ok": False, "skipped": f"already posted for {day}", "deepdive": dd}
    msg = build(root, cfg, day)
    if dry:
        return {"ok": True, "dry": True, **msg, "deepdive": build_dd(root, cfg, day)}
    require(root, cfg, "slack post", log)
    import httpx
    client = client or httpx.Client()
    ch = channel_id(client, tok, p["channel"])
    ts = _send(client, tok, ch, msg["text"], msg.get("card"), f"AI Briefing · {day}")
    _stamp(root, {"day": day, "kind": "main", "at": dt.datetime.now().isoformat(timespec="seconds"), "channel": p["channel"],
                  "channel_id": ch, "ts": ts, "card": bool(msg.get("card")), "take": bool(msg.get("take"))})
    log(f"Slack: posted the {day} briefing to #{p['channel'].lstrip('#')}" + (" with the card" if msg.get("card") else ""))
    dd = post_dd(root, cfg, day, log, client)
    return {"ok": True, "channel": ch, "ts": ts, "card": bool(msg.get("card")), "deepdive": dd}


def set_token(ask=None) -> str:
    """The slack-setup job: a Mac dialog (hidden answer) stores the bot token in the Keychain, then auth.test."""
    import subprocess
    from .vault import set_keychain

    def ask_hidden(prompt: str) -> str:
        script = ['on run argv', 'set r to display dialog (item 1 of argv) default answer "" with hidden answer '
                  'with title "AI Briefing · Slack posts" buttons {"Cancel", "Save"} default button "Save" '
                  'cancel button "Cancel"', 'return text returned of r', 'end run']
        r = subprocess.run(["osascript"] + sum((["-e", s] for s in script), []) + [prompt],
                           capture_output=True, text=True, timeout=600)
        return r.stdout.strip() if r.returncode == 0 else ""
    tok = (ask or ask_hidden)("Paste the Slack app's Bot User OAuth Token (starts with xoxb-). It stays in this Mac's "
                              "Keychain. Scopes needed: chat:write, files:write, channels:read; invite the bot to the channel.")
    if not tok.startswith("xoxb-") or len(tok) < 20:
        return "not saved: that isn't a bot token (xoxb-...)"
    if not set_keychain("SLACK_BOT_TOKEN", tok):
        return "not saved: the Keychain refused it"
    try:
        import httpx
        who = _api(httpx.Client(), "auth.test", tok)
        return f"saved: posting as {who.get('user', '?')} in {who.get('team', '?')}"
    except Exception as e:  # noqa: BLE001
        return f"saved, but auth.test failed: {e}"[:200]
