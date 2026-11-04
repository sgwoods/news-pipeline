"""Campaigns (Steven, 2026-11-04): invite people to try the briefing and follow what happens to each invite.

A campaign is data/campaigns/<id>.json: its invite email (subject and body, with {first} and {signup} filled per
person), and the people invited. Each invite's status is worked out, never typed in, from what the pipeline already
knows:

    invited      on the list, the invite is drafted or sent, no sign-up yet
    signed up    they used the form; the confirmation click is still pending
    subscribed   confirmed: the briefing goes to them (a conversion)
    abandoned    they unsubscribed, their sign-up expired, or no sign-up 10 days after the invite
    declined     marked by hand (they said no)

Engagement per person comes from their replies to the briefing (data/feedback, matched by address). Opens are not
tracked yet (see docs: a per-reader open or click counter needs the mail script and a privacy note).
Invite addresses are private data: they live in data/ (the private backup repo), never in the public export.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

DIR = "data/campaigns"
ABANDON_DAYS = 10
STATUSES = ("invited", "signed up", "subscribed", "abandoned", "declined")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _path(root: Path, cid: str) -> Path:
    if not _ID.match(cid or ""):
        raise ValueError("campaign id: lowercase letters, digits and dashes")
    return Path(root) / DIR / f"{cid}.json"


def load(root: Path, cid: str) -> dict:
    return json.loads(_path(root, cid).read_text("utf-8"))


def save(root: Path, c: dict) -> Path:
    p = _path(root, c["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=1, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(p)
    return p


def all_ids(root: Path) -> list:
    d = Path(root) / DIR
    return sorted(p.stem for p in d.glob("*.json")) if d.exists() else []


def create(root: Path, cid: str, name: str, subject: str, body: str, signup: str, goal: int = 10) -> dict:
    if _path(root, cid).exists():
        raise ValueError(f"campaign {cid} already exists")
    c = {"id": cid, "name": name, "created": dt.date.today().isoformat(), "goal": goal,
         "invite": {"subject": subject, "body": body, "signup": signup}, "people": []}
    save(root, c)
    return c


def add_person(root: Path, cid: str, email: str, name: str = "", note: str = "") -> dict:
    c = load(root, cid)
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise ValueError("that address doesn't look right")
    if any(p["email"] == email for p in c["people"]):
        raise ValueError("already on this campaign")
    c["people"].append({"email": email, "name": name.strip()[:80], "note": note.strip()[:200],
                        "added": dt.date.today().isoformat(), "invited": "", "declined": False})
    save(root, c)
    return c


def mark(root: Path, cid: str, email: str, field: str, value) -> dict:
    """invited (date the invite went out) or declined (True/False), set from the dashboard or the chat."""
    if field not in ("invited", "declined", "note"):
        raise ValueError("can only mark invited, declined or note")
    c = load(root, cid)
    for p in c["people"]:
        if p["email"] == email.strip().lower():
            p[field] = value
            save(root, c)
            return c
    raise ValueError("not on this campaign")


def invite_text(c: dict, person: dict) -> dict:
    first = (person.get("name") or "").split(" ")[0] or "there"
    inv = c["invite"]
    fill = lambda s: s.replace("{first}", first).replace("{signup}", inv["signup"])
    return {"to": person["email"], "subject": fill(inv["subject"]), "body": fill(inv["body"])}


def status_of(person: dict, sub: dict | None, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    if person.get("declined"):
        return "declined"
    st = (sub or {}).get("status", "")
    if st == "active":
        return "subscribed"
    if st in ("unsubscribed", "expired"):
        return "abandoned"
    if st == "pending":
        return "signed up"
    sent = person.get("invited") or ""
    if sent and (today - dt.date.fromisoformat(sent[:10])).days > ABANDON_DAYS:
        return "abandoned"
    return "invited"


def report(root: Path, cid: str, subscribers: list, feedback: list, today: dt.date | None = None) -> dict:
    """The campaign with each person's status and replies, and the funnel."""
    c = load(root, cid)
    subs = {str(s.get("email", "")).lower(): s for s in subscribers or []}
    rows = []
    for p in c["people"]:
        s = subs.get(p["email"])
        replies = [f for f in feedback or [] if str(f.get("sender", "")).lower() == p["email"]]
        rows.append({**p, "status": status_of(p, s, today), "subscribed_at": str((s or {}).get("confirmed") or "")[:10],
                     "signed_up_at": str((s or {}).get("created") or "")[:10], "replies": len(replies),
                     "last_reply": max((str(f.get("received", ""))[:10] for f in replies), default="")})
    funnel = {k: sum(1 for r in rows if r["status"] == k) for k in STATUSES}
    funnel["people"] = len(rows)
    funnel["invited_sent"] = sum(1 for r in rows if r.get("invited"))
    funnel["replied"] = sum(1 for r in rows if r["replies"])
    funnel["conversion_pct"] = round(100 * funnel["subscribed"] / funnel["invited_sent"]) if funnel["invited_sent"] else None
    return {**c, "rows": rows, "funnel": funnel}
