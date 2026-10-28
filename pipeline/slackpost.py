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


def _dd(root: Path, cfg: dict, day: str) -> tuple:
    """(title, first line of the summary, Steven's take on it, url) or ('', '', '', '')."""
    from . import deepdive
    from .mailer import deep_dive_for
    info = deep_dive_for(root, cfg, day)
    if not info:
        return "", "", "", ""
    line = re.split(r"(?<=[.!?])\s+", info.get("summary") or "")[0] if info.get("summary") else ""
    take = ""
    rec = deepdive.latest(root, day) or {}
    qid = (rec.get("pick") or {}).get("queue_id")
    if qid:
        it = next((x for x in deepdive.load_queue(root) if x.get("id") == qid), None)
        take = str((it or {}).get("take") or "")
    return info["title"].removeprefix("Deep dive: "), line, take, info["url"]


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


def post(root: Path, cfg: dict, day: str, log=print, client=None, dry: bool = False) -> dict:
    """Post DAY's card and text to the channel. Gated (release.require); never in staging; once per day."""
    from .release import require
    p = pcfg(cfg)
    if not p.get("enabled"):
        return {"ok": False, "skipped": "slack.post.enabled is off"}
    tok = token()
    if not tok:
        return {"ok": False, "skipped": "no SLACK_BOT_TOKEN (queue the slack-setup job)"}
    stamp = root / "data" / "state" / "slack-posts.jsonl"
    if stamp.exists() and any(json.loads(x).get("day") == day for x in stamp.read_text("utf-8").splitlines() if x.strip()):
        return {"ok": False, "skipped": f"already posted for {day}"}
    msg = build(root, cfg, day)
    if dry:
        return {"ok": True, "dry": True, **msg}
    require(root, cfg, "slack post", log)
    import httpx
    client = client or httpx.Client()
    ch = channel_id(client, tok, p["channel"])
    card_path = msg.get("card")
    if card_path and Path(card_path).is_file():
        data = Path(card_path).read_bytes()
        up = _api(client, "files.getUploadURLExternal", tok, filename=f"ai-briefing-{day}.png", length=str(len(data)))
        r = client.post(up["upload_url"], content=data, timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"slack upload: HTTP {r.status_code}")
        done = client.post(f"{API}/files.completeUploadExternal", headers={"Authorization": f"Bearer {tok}"},
                           json={"files": [{"id": up["file_id"], "title": f"AI Briefing · {day}"}], "channel_id": ch,
                                 "initial_comment": msg["text"]}, timeout=30).json()
        if not done.get("ok"):
            raise RuntimeError(f"slack completeUploadExternal: {done.get('error', done)}")
        ts = ((done.get("files") or [{}])[0].get("shares") or {})
    else:
        done = _api(client, "chat.postMessage", tok, channel=ch, text=msg["text"], unfurl_links="false")
        ts = done.get("ts", "")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    with stamp.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "channel": p["channel"],
                            "card": bool(card_path), "take": bool(msg.get("take"))}) + "\n")
    log(f"Slack: posted the {day} briefing to #{p['channel'].lstrip('#')}" + (" with the card" if card_path else ""))
    return {"ok": True, "channel": ch, "card": bool(card_path)}


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
