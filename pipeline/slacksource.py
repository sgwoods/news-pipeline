"""Links Steven shares in an internal Slack channel, as a source (read-only, Slack Web API, free).

The channel is internal, the briefing is not. So only the LINKS travel: each article Steven posted becomes
an item (tier "follow closely", flag SHARED) whose text is the article's own preview (Slack's unfurl), and
whose source note tells the model the article is the source. Nothing anyone else writes in Slack (their
messages, thread replies, the channel's name) is stored as text or reaches any output. Steven's own words on a
link he shares are kept as a take candidate (data/takes/slack.jsonl, decided 2026-10-22): they reach the edition
only as "Steven's take" on that story, after the takes privacy check (pipeline/takes.py), never as source text.
With `links_from: anyone` (Steven, 2026-10-22) links posted by any member count too, as the same kind of
item, credited to the linked source; who posted them is never stored (names in his network stay private).

Setup (docs/SLACK.md): accept the Slack Connect invite with you+briefing@example.com, create a Slack app
in that free workspace with user scopes channels:history, groups:history, channels:read, groups:read, install
it, put the User OAuth Token (xoxp-...) in .env as SLACK_USER_TOKEN, then ./np slack test.

config.yaml slack: {enabled, channel: cto-musings, authors: [U...] or emails, lookback_hours: 48}
"""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from .textutil import UTC, clean_url, iso, item_id

API = "https://slack.com/api"
# Links that are private by nature never leave Slack: documents, drives, internal tools, other Slack links.
PRIVATE_HOSTS = ("docs.google.com", "drive.google.com", "sheets.google.com", "slides.google.com", "notion.so",
                 "notion.site", "dropbox.com", "app.box.com", "sharepoint.com", "onedrive.live.com", "1drv.ms", "figma.com",
                 "miro.com", "airtable.com", "calendar.google.com", "meet.google.com", "zoom.us", "teams.microsoft.com",
                 "slack.com", "atlassian.net", "loom.com", "docsend.com", "app.pitch.com")


def _private_hosts() -> tuple:
    from .owner import get as owner
    return PRIVATE_HOSTS + tuple(owner()["org_domains"])


def private_link(url: str) -> bool:
    from urllib.parse import urlparse
    h = urlparse(url).netloc.lower()
    return any(h == p or h.endswith("." + p) for p in _private_hosts())
_URL = re.compile(r"<(https?://[^>|]+)(?:\|[^>]*)?>")


class SlackError(RuntimeError):
    pass


def scfg(cfg: dict) -> dict:
    return {"enabled": False, "channel": "", "authors": [], "links_from": "authors", "lookback_hours": 48,
            **(cfg.get("slack") or {})}


def token() -> str:
    from .vault import get
    return get("SLACK_USER_TOKEN").strip()


def _call(client, method: str, **params) -> dict:
    tok = token()
    if not tok:
        raise SlackError("SLACK_USER_TOKEN is not set in .env (see docs/SLACK.md)")
    r = client.get(f"{API}/{method}", params=params, headers={"Authorization": f"Bearer {tok}"})
    r.raise_for_status()
    d = r.json()
    if not d.get("ok"):
        raise SlackError(f"{method}: {d.get('error', 'not ok')}")
    return d


def find_channel(client, name: str) -> dict:
    name = name.lstrip("#").lower()
    cursor = None
    while True:
        d = _call(client, "conversations.list", types="public_channel,private_channel", limit=200,
                  exclude_archived="true", **({"cursor": cursor} if cursor else {}))
        for ch in d.get("channels", []):
            if ch.get("name", "").lower() == name:
                return ch
        cursor = (d.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            raise SlackError(f"channel #{name} not visible to this account (accept the invite, then join it)")


def author_ids(client, authors: list) -> set:
    """Slack user IDs (U...) as given, or looked up from email addresses (needs users:read.email)."""
    out = set()
    for a in authors or []:
        a = str(a).strip()
        if a.startswith(("U", "W")) and "@" not in a:
            out.add(a)
        elif "@" in a:
            try:
                out.add(_call(client, "users.lookupByEmail", email=a)["user"]["id"])
            except SlackError:
                pass
    return out


def _links(msg: dict) -> list:
    """(url, title, preview) for each link in a message, from Slack's unfurls first, then the text."""
    seen, out = set(), []
    for att in msg.get("attachments") or []:
        u = att.get("original_url") or att.get("title_link") or att.get("from_url") or ""
        if u.startswith("http") and "slack.com" not in u:
            seen.add(clean_url(u))
            out.append((clean_url(u), att.get("title") or "", att.get("text") or att.get("fallback") or "",
                        att.get("service_name") or ""))
    for u in _URL.findall(msg.get("text") or ""):
        cu = clean_url(u)
        if cu not in seen and "slack.com" not in cu:
            seen.add(cu)
            out.append((cu, "", "", ""))
    return out


def fetch(root: Path, cfg: dict, run_id: str, log, lookback_hours: int | None = None, client=None) -> dict:
    s = scfg(cfg)
    now = dt.datetime.now(UTC)
    since = now - dt.timedelta(hours=lookback_hours or s["lookback_hours"])
    own = client is None
    if own:
        import httpx
        client = httpx.Client(timeout=20)
    items, per = [], []
    try:
        ch = find_channel(client, s["channel"])
        who = author_ids(client, s["authors"])
        if not who:
            raise SlackError("slack.authors is empty or could not be resolved: only Steven's own posts are read")
        d = _call(client, "conversations.history", channel=ch["id"], oldest=f"{since.timestamp():.6f}", limit=200)
        anyone = s.get("links_from") == "anyone"
        msgs = [m for m in d.get("messages", []) if (m.get("user") in who or (anyone and m.get("user")))
                and m.get("subtype") in (None, "thread_broadcast", "file_share") and not m.get("bot_id")]
        take_rows = []
        for m in msgs:
            when = dt.datetime.fromtimestamp(float(m.get("ts", "0")), UTC)
            mine = m.get("user") in who
            if mine and s.get("takes", True):          # his own words on the link he shares = his take (takes.py)
                from .takes import slack_text
                words = slack_text(m.get("text", ""))
                if len(words.split()) >= 3:
                    for url, _t, _p, _s in _links(m):
                        if not private_link(url):
                            take_rows.append({"ts": m.get("ts"), "at": when.astimezone().isoformat(timespec="seconds"),
                                              "id": item_id(url), "url": url, "text": words[:1500]})
            for url, title, preview, site in _links(m):
                if private_link(url):                 # a deck or doc shared with the team stays in Slack
                    continue
                text = " ".join(x for x in (title, preview) if x).strip()
                items.append({
                    "id": item_id(url), "url": url, "title": title or url, "author": site or "",
                    "published": iso(when), "text": text, "text_chars": len(text),
                    "person": "Shared by Steven" if mine else "Shared internally",
                    "tier": "follow closely", "flags": ["SHARED"], "scrutiny": False,
                    "source_kind": "shared", "source_url": "slack", "source_label": "",
                    "source_note": ("Steven shared this link with his team as worth reading. " if mine else
                                    "Someone on Steven's team shared this link as worth reading. ") +
                                   "The article itself is the source: cite its publisher, never this note, never who "
                                   "shared it, and never mention where it was shared.",
                    "fetched_at": iso(now), "run_id": run_id})
        if take_rows:
            from .takes import add_slack
            add_slack(root, take_rows)
            log.info("  your words on %d shared link(s) kept as take candidates", len(take_rows))
        from . import linkedin                       # his own LinkedIn posts are his words, not news
        own_posts = [it for it in items if linkedin.is_own_post(it, cfg)]
        if own_posts:
            n = linkedin.add_posts(root, [linkedin.from_item(it) for it in own_posts])
            items = [it for it in items if it not in own_posts]
            log.info("  own LinkedIn post(s): %d -> public record (%d new), not briefed", len(own_posts), n)
        per.append({"person": "Links Steven shared", "kind": "shared", "url": "slack", "status": "ok",
                    "new": len(items), "messages": len(msgs)})
        log.info("  OK   shared links: %d link(s) in %d post(s)", len(items), len(msgs))
    except Exception as e:  # noqa: BLE001
        per.append({"person": "Links Steven shared", "kind": "shared", "url": "slack", "status": "error",
                    "error": f"{type(e).__name__}: {e}"[:300]})
        log.warning("  FAIL shared links (Slack): %s", e)
    finally:
        if own:
            client.close()
    return {"items": items, "sources": per}
