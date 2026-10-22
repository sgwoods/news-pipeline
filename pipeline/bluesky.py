"""Bluesky lists and Steven's own posts as sources, via the public AT Protocol API (no key, no login).

config.yaml bluesky:
  lists: [https://bsky.app/profile/example.com/lists/LIST_ID]   # curated people; one tap to add someone
  own: example.com                # the owner's own posts: an interest signal, never a story's only source
  lookback_hours: 36

Posts are archived like any item (kind "bluesky"); the post's web URL is the item URL. A post that only
links to an article we already archived is dropped by the usual prefilter. Text is data, never instructions.
"""
from __future__ import annotations

import datetime as dt
import re

from .textutil import UTC, clean_url, iso, item_id, parse_date

API = "https://public.api.bsky.app/xrpc"
LIST_URL_RE = re.compile(r"bsky\.app/profile/([^/]+)/lists/([a-z0-9]+)")


def bcfg(cfg: dict) -> dict:
    return {"lists": [], "own": "", "lookback_hours": 36, "max_posts": 100, "wire_handles": [], "handles": [],
            **(cfg.get("bluesky") or {})}


def resolve(client, handle: str) -> str:
    if handle.startswith("did:"):
        return handle
    r = client.get(f"{API}/com.atproto.identity.resolveHandle", params={"handle": handle.lstrip("@")})
    r.raise_for_status()
    return r.json()["did"]


def list_uri(client, url: str) -> str:
    if url.startswith("at://"):
        return url
    m = LIST_URL_RE.search(url)
    if not m:
        raise ValueError(f"not a Bluesky list URL: {url}")
    return f"at://{resolve(client, m.group(1))}/app.bsky.graph.list/{m.group(2)}"


def list_info(client, url: str) -> dict:
    """Name, description and members of a list."""
    uri = list_uri(client, url)
    members, cursor, name, desc = [], None, "", ""
    while True:
        r = client.get(f"{API}/app.bsky.graph.getList", params={"list": uri, "limit": 100, **({"cursor": cursor} if cursor else {})})
        r.raise_for_status()
        d = r.json()
        name, desc = d.get("list", {}).get("name", name), d.get("list", {}).get("description", desc)
        members += [{"handle": x["subject"].get("handle", ""), "name": x["subject"].get("displayName") or x["subject"].get("handle", ""),
                     "did": x["subject"].get("did", "")} for x in d.get("items", [])]
        cursor = d.get("cursor")
        if not cursor:
            break
    return {"uri": uri, "url": url, "name": name, "description": desc, "members": members}


def find(client, name: str, limit: int = 4) -> list:
    """People matching a name (actor search), with follower counts so the real one stands out."""
    r = client.get(f"{API}/app.bsky.actor.searchActors", params={"q": name, "limit": limit})
    r.raise_for_status()
    out = []
    for a in r.json().get("actors", []):
        did = a.get("did", "")
        followers = ""
        try:
            p = client.get(f"{API}/app.bsky.actor.getProfile", params={"actor": did})
            followers = p.json().get("followersCount", "") if p.status_code == 200 else ""
        except Exception:  # noqa: BLE001
            pass
        out.append({"handle": a.get("handle", ""), "name": a.get("displayName") or "", "did": did, "followers": followers,
                    "bio": " ".join((a.get("description") or "").split())[:90]})
    return out


def latest_post(client, handle: str) -> str:
    """Date of the newest post (ISO date), or "" when the feed is empty."""
    r = client.get(f"{API}/app.bsky.feed.getAuthorFeed", params={"actor": handle, "filter": "posts_no_replies", "limit": 1})
    r.raise_for_status()
    feed = r.json().get("feed", [])
    if not feed:
        return ""
    d = parse_date(((feed[0].get("post") or {}).get("record") or {}).get("createdAt"))
    return iso(d)[:10] if d else ""


def _post_item(p: dict, src: dict, run_id: str, now: dt.datetime) -> dict | None:
    post = p.get("post") or p
    rec = post.get("record") or {}
    if p.get("reason"):                                  # repost by a list member: not their words
        return None
    if "reply" in rec and src.get("skip_replies", True):
        return None
    author = post.get("author") or {}
    handle, rkey = author.get("handle", ""), post.get("uri", "").rsplit("/", 1)[-1]
    url = f"https://bsky.app/profile/{handle}/post/{rkey}"
    text = (rec.get("text") or "").strip()
    emb = (post.get("embed") or {}).get("external") or ((rec.get("embed") or {}).get("external"))
    link = ""
    if not emb:                                  # a post with a plain link in its text (Techmeme does this)
        for f in rec.get("facets") or []:
            for feat in f.get("features") or []:
                u = feat.get("uri") or ""
                if u.startswith("http") and "bsky.app" not in u and not link:
                    link = clean_url(u)
    if emb:
        link = clean_url(emb.get("uri") or "")
        extra = " ".join(x for x in [emb.get("title", ""), emb.get("description", "")] if x)
        if extra:
            text = f"{text}\n\nLinked: {extra}\n{link}".strip()
    pub = parse_date(rec.get("createdAt") or post.get("indexedAt"))
    name = author.get("displayName") or handle
    tier = "wire" if handle.lower() in src.get("wire_handles", ()) else src["tier"]
    return {"id": item_id(url), "url": url, "title": (text[:90] + "…") if len(text) > 90 else text or "(post)",
            "author": name, "published": iso(pub) if pub else iso(now), "text": text, "text_chars": len(text),
            "person": src["person_prefix"] + name if src.get("person_prefix") else name,
            "tier": tier, "flags": src.get("flags", []), "scrutiny": False,
            "source_kind": "bluesky", "source_url": src["url"], "source_label": "",
            "source_note": src.get("note", ""), "linked_url": link, "handle": handle,
            "fetched_at": iso(now), "run_id": run_id}


def _feed(client, endpoint: str, params: dict, since: dt.datetime, limit: int) -> list:
    out, cursor = [], None
    while len(out) < limit:
        r = client.get(f"{API}/{endpoint}", params={**params, "limit": 50, **({"cursor": cursor} if cursor else {})})
        r.raise_for_status()
        d = r.json()
        feed = d.get("feed", [])
        if not feed:
            break
        out += feed
        last = parse_date(((feed[-1].get("post") or {}).get("record") or {}).get("createdAt"))
        cursor = d.get("cursor")
        if not cursor or (last and last < since):
            break
    return out[:limit]


def fetch(cfg: dict, run_id: str, log, lookback_hours: int | None = None, client=None, root=None) -> dict:
    """Posts from each configured list (+ Steven's own) inside the window → items + per-source stats."""
    from pathlib import Path
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    b = bcfg(cfg)
    now = dt.datetime.now(UTC)
    since = now - dt.timedelta(hours=lookback_hours or b["lookback_hours"])
    own_client = client is None
    if own_client:
        import httpx
    client = client or httpx.Client(timeout=20, headers={"User-Agent": (cfg.get("fetch") or {}).get("user_agent", "news-pipeline/0.1")})
    items, per, members = [], [], {}
    try:
        for url in b["lists"]:
            src = {"url": url, "tier": "list", "note": "From Steven's curated Bluesky list of realistic AI commentators.",
                   "wire_handles": {h.lower().lstrip("@") for h in b["wire_handles"]}}
            try:
                info = list_info(client, url)
                members[url] = info
                src["note"] = f"From Steven's Bluesky list \"{info['name']}\"" + (f": {info['description']}" if info.get("description") else ".")
                posts = _feed(client, "app.bsky.feed.getListFeed", {"list": info["uri"]}, since, b["max_posts"])
                got = [it for it in (_post_item(p, src, run_id, now) for p in posts) if it and it["published"] >= iso(since)]
                items += got
                per.append({"person": f"Bluesky list: {info['name']}", "kind": "bluesky", "url": url, "status": "ok",
                            "new": len(got), "members": len(info["members"]), "posts": len(posts)})
                log.info("  OK   Bluesky list %s: %d members, %d posts in window", info["name"], len(info["members"]), len(got))
            except Exception as e:  # noqa: BLE001
                per.append({"person": "Bluesky list", "kind": "bluesky", "url": url, "status": "error", "error": f"{type(e).__name__}: {e}"[:300]})
                log.warning("  FAIL Bluesky list %s: %s", url, e)
        # individual accounts (config bluesky.handles): people not on a list, and unofficial X mirrors.
        # `x: handle` borrows the name, tier, flags and note of that account in x.yaml.
        xaccts = {}
        if any(h.get("x") for h in b["handles"] if isinstance(h, dict)):
            try:
                from .xsource import load_x
                xaccts = {a["handle"].lower(): a for a in load_x(root)["accounts"]}
            except Exception:  # noqa: BLE001
                pass
        for h in b["handles"]:
            if not isinstance(h, dict) or not h.get("handle"):
                continue
            xa = xaccts.get(str(h.get("x") or "").lower().lstrip("@"))
            name = h.get("name") or (xa or {}).get("name") or h["handle"]
            note = h.get("note") or ""
            if xa:
                note = (xa["why"] + " " + note).strip()
            if h.get("mirror"):
                note += " Read through an unofficial Bluesky account that mirrors their X posts: the words are theirs, the account is not."
            src = {"url": f"https://bsky.app/profile/{h['handle']}", "tier": h.get("tier") or (xa or {}).get("tier") or "follow",
                   "flags": (xa or {}).get("flags", []), "note": note, "skip_replies": True, "wire_handles": set(),
                   "person_prefix": ""}
            try:
                posts = _feed(client, "app.bsky.feed.getAuthorFeed", {"actor": h["handle"], "filter": "posts_no_replies"}, since, b["max_posts"])
                got = [it for it in (_post_item(p, src, run_id, now) for p in posts) if it and it["published"] >= iso(since)]
                got = sorted(got, key=lambda it: it["published"], reverse=True)[: int(h.get("max") or b["max_posts"])]
                for it in got:
                    it["person"], it["author"] = name, name
                    it["scrutiny"] = src["tier"] == "scrutiny"
                items += got
                per.append({"person": name, "kind": "bluesky", "url": src["url"], "status": "ok", "new": len(got)})
                log.info("  OK   Bluesky @%s (%s): %d in window", h["handle"], name, len(got))
            except Exception as e:  # noqa: BLE001
                per.append({"person": name, "kind": "bluesky", "url": src["url"], "status": "error", "error": f"{type(e).__name__}: {e}"[:300]})
                log.warning("  FAIL Bluesky @%s: %s", h["handle"], e)
        if b.get("own"):
            src = {"url": f"https://bsky.app/profile/{b['own']}", "tier": "own", "person_prefix": "",
                   "note": "Posted by Steven himself. It shows what he is paying attention to; cite the linked article "
                           "or the people he is replying to as the source, never his post, and never make it a story on its own."}
            try:
                posts = _feed(client, "app.bsky.feed.getAuthorFeed", {"actor": b["own"], "filter": "posts_no_replies"}, since, b["max_posts"])
                got = [it for it in (_post_item(p, src, run_id, now) for p in posts) if it and it["published"] >= iso(since)]
                for it in got:
                    it["person"] = "Steven Woods (own posts)"
                items += got
                per.append({"person": "Steven Woods (own posts)", "kind": "bluesky", "url": src["url"], "status": "ok", "new": len(got)})
                log.info("  OK   Bluesky own posts: %d in window", len(got))
            except Exception as e:  # noqa: BLE001
                per.append({"person": "Steven Woods (own posts)", "kind": "bluesky", "url": src["url"], "status": "error",
                            "error": f"{type(e).__name__}: {e}"[:300]})
                log.warning("  FAIL Bluesky own posts: %s", e)
    finally:
        if own_client:
            client.close()
    return {"items": items, "sources": per, "lists": members}
