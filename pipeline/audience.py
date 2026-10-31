"""Who gets the AI Briefing, and how (Steven, 2026-10-31): one row per person with every channel they receive it
through, for the dashboard's Subscribers page. Email: the subscriber list in the Google Sheet (mailer). Slack: the
members of the newsletter channel, read with the AI Briefing bot (conversations.members, users.info; scopes
channels:read and users:read, users:read.email to match people to their email). Podcast listeners are anonymous:
podcast apps don't say who subscribes, so the podcast shows as a count of feeds, not people. Local only: this list
never leaves the dashboard.
"""
from __future__ import annotations

API = "https://slack.com/api"
CHANNELS = ("email", "slack", "podcast")


def slack_members(cfg: dict, client=None) -> dict:
    """{"members": [{"id", "name", "email"}], "error": str}: the newsletter channel's people (bots left out)."""
    from .slackpost import pcfg, token
    p = pcfg(cfg)
    tok, ch = token(), p.get("channel_id", "")
    if not (tok and ch):
        return {"members": [], "error": "no SLACK_BOT_TOKEN or slack.post.channel_id"}
    own = client is None
    if own:
        import httpx
        client = httpx.Client(timeout=20)
    h = {"Authorization": f"Bearer {tok}"}
    out, err = [], ""
    try:
        ids, cursor = [], ""
        for _ in range(20):
            d = client.get(f"{API}/conversations.members", headers=h, params={"channel": ch, "limit": 200, "cursor": cursor}).json()
            if not d.get("ok"):
                return {"members": [], "error": f"conversations.members: {d.get('error')} (scope channels:read)"}
            ids += d.get("members", [])
            cursor = (d.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        for uid in ids:
            u = client.get(f"{API}/users.info", headers=h, params={"user": uid}).json()
            if not u.get("ok"):
                err = f"users.info: {u.get('error')} (scope users:read)"
                out.append({"id": uid, "name": uid, "email": ""})
                continue
            user = u.get("user") or {}
            if user.get("is_bot") or user.get("id") == "USLACKBOT":
                continue
            prof = user.get("profile") or {}
            out.append({"id": uid, "name": prof.get("real_name") or user.get("name") or uid,
                        "email": (prof.get("email") or "").lower()})
    finally:
        if own:
            client.close()
    return {"members": out, "error": err}


def rows(email_subs: list, slack: list) -> list:
    """One row per person: {name, email, email_status, slack (bool), channels: [...]}, matched on email."""
    by = {}
    for s in email_subs or []:
        e = str(s.get("email", "")).lower()
        if e:
            by[e] = {"name": "", "email": e, "email_status": s.get("status", ""), "slack": False}
    for m in slack or []:
        key = m.get("email") or f"slack:{m['id']}"
        r = by.setdefault(key, {"name": "", "email": m.get("email", ""), "email_status": "", "slack": False})
        r["slack"], r["name"] = True, m.get("name", "")
    out = []
    for r in by.values():
        r["channels"] = [c for c, on in (("email", r["email_status"] == "active"), ("slack", r["slack"])) if on]
        out.append(r)
    return sorted(out, key=lambda r: (-len(r["channels"]), r["name"] or r["email"]))
