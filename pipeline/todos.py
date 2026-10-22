"""A shared to-do list for Steven and Claude: things only Steven can do (subscribe, create a filter,
approve a source) and things Claude owes. data/todos.json, committed; shown on the dashboard To do page
and in ./np todo. Ticking one off records when and by whom.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

FILE = "data/todos.json"
GROUPS = ("newsletters", "bluesky", "x", "setup", "quality", "claude")


def _bsky_list() -> str:
    from .owner import get as owner
    return owner()["bluesky_list"]


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def tid(title: str) -> str:
    return hashlib.sha1(title.strip().lower().encode()).hexdigest()[:8]


def load(root: Path) -> list:
    try:
        return json.loads((root / FILE).read_text("utf-8")).get("todos", [])
    except (OSError, json.JSONDecodeError):
        return []


def save(root: Path, rows: list) -> None:
    p = root / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated": _now(), "todos": rows}, indent=1, ensure_ascii=False) + "\n", "utf-8")


def add(root: Path, title: str, group: str = "setup", owner: str = "steven", detail: str = "", url: str = "") -> dict:
    rows = load(root)
    t = tid(title)
    for r in rows:
        if r["id"] == t:
            return r
    row = {"id": t, "title": title.strip()[:160], "group": group if group in GROUPS else "setup", "owner": owner,
           "detail": detail.strip()[:600], "url": url.strip()[:400], "status": "open", "created": _now()}
    rows.append(row)
    save(root, rows)
    return row


def seed(root: Path, items: list) -> int:
    """Add any of these (title, group, owner, detail, url) that are not already there."""
    rows = load(root)
    have = {r["id"] for r in rows}
    n = 0
    for title, group, owner, detail, url in items:
        if tid(title) not in have:
            rows.append({"id": tid(title), "title": title, "group": group, "owner": owner, "detail": detail,
                         "url": url, "status": "open", "created": _now()})
            n += 1
    if n:
        save(root, rows)
    return n


def set_status(root: Path, t: str, status: str, note: str = "") -> dict:
    rows = load(root)
    for r in rows:
        if r["id"] == t:
            r["status"] = status
            r["done_at" if status == "done" else "updated"] = _now()
            if note:
                r["note"] = note[:300]
            save(root, rows)
            return r
    raise KeyError(t)


def grouped(root: Path) -> dict:
    out = {g: [] for g in GROUPS}
    for r in load(root):
        out.setdefault(r.get("group", "setup"), []).append(r)
    return out


def markdown(root: Path) -> str:
    L = ["# News pipeline — to do", ""]
    for g, rows in grouped(root).items():
        if not rows:
            continue
        L.append(f"## {g}")
        for r in sorted(rows, key=lambda r: (r["status"] == "done", r["created"])):
            box = "x" if r["status"] == "done" else " "
            link = f" — {r['url']}" if r.get("url") else ""
            L.append(f"- [{box}] `{r['id']}` ({r['owner']}) {r['title']}{link}")
            if r.get("detail") and r["status"] != "done":
                L.append(f"      {r['detail']}")
        L.append("")
    return "\n".join(L)


SIGNUP = "Subscribe with you+briefing@example.com (plain address if the site refuses '+'); the Gmail filter files it under AI-Briefing/Sources."
STARTER = [
    # newsletters: Steven's seven + Claude's three
    ("Subscribe: The Rundown AI (coverage-check)", "newsletters", "steven", SIGNUP, "https://www.therundown.ai/subscribe"),
    ("Subscribe: TLDR AI (wire)", "newsletters", "steven", SIGNUP, "https://tldr.tech/ai"),
    ("Subscribe: Superhuman AI (coverage-check)", "newsletters", "steven", SIGNUP, "https://www.superhuman.ai/subscribe"),
    ("Subscribe: The Batch (DeepLearning.AI)", "newsletters", "steven", SIGNUP, "https://www.deeplearning.ai/the-batch/"),
    ("Subscribe: Import AI (Jack Clark)", "newsletters", "steven", SIGNUP + " Already fetched from the web; the email is a backup.", "https://importai.substack.com/subscribe"),
    ("Subscribe: One Useful Thing (Ethan Mollick)", "newsletters", "steven", SIGNUP + " Already fetched from the web; the email is a backup.", "https://www.oneusefulthing.org/subscribe"),
    ("Subscribe: Last Week in AI", "newsletters", "steven", SIGNUP, "https://lastweekin.ai/subscribe"),
    ("Subscribe: Don't Worry About the Vase (Zvi Mowshowitz) — Claude's pick", "newsletters", "steven",
     "Long weekly synthesis with sharp, sceptical takes on every lab release and policy move. " + SIGNUP, "https://thezvi.substack.com/subscribe"),
    ("Subscribe: Exponential View (Azeem Azhar) — Claude's pick", "newsletters", "steven",
     "Weekly on AI, energy and the economy; investor-literate. " + SIGNUP, "https://www.exponentialview.co/subscribe"),
    ("Subscribe: Stratechery free weekly article (Ben Thompson) — Claude's pick", "newsletters", "steven",
     "Business strategy of the platforms; the free weekly article is enough. " + SIGNUP, "https://stratechery.com/subscribe/"),
    ("Add any new newsletters to newsletters.yaml with a bias note", "newsletters", "steven",
     "Zvi, Exponential View and Stratechery are not in newsletters.yaml yet; add from/web/tier/bias (Claude can draft them).", ""),
    # Gmail setup
    ("Gmail: create label AI-Briefing/Sources and the filter (To: you+briefing@example.com -> label, skip inbox)", "setup", "steven",
     "docs/NEWSLETTERS.md section 2.", "https://mail.google.com/mail/u/0/#settings/filters"),
    ("Gmail: create an app password and put it in .env as GMAIL_APP_PASSWORD", "setup", "steven",
     "Needs 2-Step Verification. docs/NEWSLETTERS.md section 3. Then ./np newsletters test.", "https://myaccount.google.com/apppasswords"),
    ("Run ./np newsletters fetch 7, then set email_sources.enabled: true in config.yaml", "setup", "steven", "", ""),
    # bluesky
    ("Bluesky: run ./np bluesky status and confirm the Tech of Reality list (117 members) is the one to use", "bluesky", "steven",
     "Outlets in the list (Techmeme, TechCrunch, Ars, MIT TR, The Logic) are treated as wire: they never lead a story.", _bsky_list()),
    ("Bluesky: decide on the extra starter-pack lists Claude found", "bluesky", "steven",
     "Candidates, as list URIs in config.yaml bluesky.lists: 'The AI beat' (journalists + researchers), 'Interesting AI folk' (Delip Rao, "
     "'highest chill to shill ratio'), 'Canadian AI Researchers', 'AI and Data' (Pelayo Arbués). Each adds volume; start with The AI beat + Canadian AI Researchers.", ""),
    # x
    ("X: review x.yaml (17 accounts: Steven's 11 + the SCRUTINY voices) and run ./np x status", "x", "steven",
     "Nitter-style mirrors are flaky; the status shows which instance answered. Never pay X.", ""),
    ("X: weekly Claude digest for accounts no mirror can reach", "x", "claude",
     "Like the public-record search: one web-search call per SCRUTINY account per week -> items with links.", ""),
    # quality plan (Claude)
    ("Spoken order: Top of mind + Open questions in the episode; story N of M cues by code", "quality", "claude", "", ""),
    ("Second voice for the critical read; pronunciation table", "quality", "claude", "", ""),
    ("Critique every item that reaches the briefing; importance scored by Claude", "quality", "claude", "", ""),
    ("Ratings (1-5, new to me) on briefing page and email; Quality page for the 10-16 review", "quality", "claude", "", ""),
    ("Dashboard -> Today / Library / Studio, mobile first", "quality", "claude", "", ""),
    ("Podcast: distinctive name, 3000px art, owner email in feed (before listing)", "quality", "claude", "", ""),
    ("Dashboard login before it is reachable off the Mac", "quality", "claude", "", ""),
]
