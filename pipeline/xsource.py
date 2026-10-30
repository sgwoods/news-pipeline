"""X / Twitter accounts via Nitter-style mirrors (public RSS), never via X's paid API.

x.yaml lists the accounts and the mirror instances. An instance is a Nitter-style base URL ({instance}/{handle}/rss)
or a template with {handle}, e.g. the local xsukax-X-RSS-Generator on Steven's Mac (2026-10-30):
"http://127.0.0.1:8787/?x={handle}&l=20". `lists:` in x.yaml adds the members of Steven's X lists (as read into
data/state/x-lists.json) as accounts of tier "list"; `delay_seconds` spaces the requests. Each run: pick the first instance whose RSS answers
for the first account, then read every account through it; record which instance worked in
data/state/x-health.json (shown on the Sources page). When no instance works the run notes it and
moves on; the weekly Claude X digest (record.py style) is the fallback for the SCRUTINY voices.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .textutil import UTC, clean_url, html_to_text, iso, item_id, parse_date

HEALTH = "data/state/x-health.json"


def load_x(root: Path) -> dict:
    import yaml
    p = root / "x.yaml"
    d = (yaml.safe_load(p.read_text("utf-8")) if p.exists() else None) or {}
    accts = []
    for a in d.get("accounts") or []:
        if isinstance(a, dict) and a.get("handle"):
            accts.append({"handle": str(a["handle"]).lstrip("@"), "name": str(a.get("name") or a["handle"]),
                          "tier": str(a.get("tier") or "follow"), "flags": [str(x) for x in (a.get("flags") or [])],
                          "why": " ".join(str(a.get("why") or "").split())})
    have = {a["handle"].lower() for a in accts}
    want = [str(n) for n in (d.get("lists") or [])]
    for lst in lists(root):                      # members of the lists Steven named, after his own accounts
        if lst.get("name") not in want:
            continue
        for m in lst.get("members") or []:
            h = str(m.get("handle") or "").lstrip("@")
            if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", h) or h.lower() in have:
                continue
            have.add(h.lower())
            accts.append({"handle": h, "name": str(m.get("name") or h), "tier": "list", "flags": [],
                          "why": f"Member of Steven's X list \"{lst['name']}\"." + (f" {m['bio']}" if m.get("bio") else "")})
    cap = int(d.get("max_accounts") or 120)
    return {"instances": [str(x).rstrip("/") for x in (d.get("instances") or [])], "accounts": accts[:cap],
            "delay": float(d.get("delay_seconds") or 0)}


def feed_url(instance: str, handle: str) -> str:
    return instance.replace("{handle}", handle) if "{handle}" in instance else f"{instance}/{handle}/rss"


def _health(root: Path) -> dict:
    try:
        return json.loads((root / HEALTH).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_health(root: Path, h: dict) -> None:
    p = root / HEALTH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(h, indent=1) + "\n", "utf-8")


def _x_url(link: str, handle: str) -> str:
    """Mirror link -> canonical x.com link (so the same tweet via two mirrors is one item)."""
    m = re.search(r"/([A-Za-z0-9_]+)/status/(\d+)", link or "")
    return f"https://x.com/{m.group(1)}/status/{m.group(2)}" if m else f"https://x.com/{handle}"


def probe(client, instance: str, handle: str) -> tuple:
    """(ok, entries or reason) for one instance."""
    import feedparser
    try:
        r = client.get(feed_url(instance, handle))
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    parsed = feedparser.parse(r.content)
    if not parsed.entries:
        return False, "no entries" if parsed.get("version") else "not a feed"
    return True, parsed.entries


def fetch(root: Path, cfg: dict, run_id: str, log, lookback_hours: int | None = None, client=None) -> dict:
    x = load_x(root)
    if not x["accounts"] or not x["instances"]:
        return {"items": [], "sources": [], "instance": ""}
    now = dt.datetime.now(UTC)
    since = now - dt.timedelta(hours=lookback_hours or (cfg.get("fetch") or {}).get("lookback_hours", 36))
    own = client is None
    if own:
        import httpx
        client = httpx.Client(follow_redirects=True, timeout=20,
                              headers={"User-Agent": (cfg.get("fetch") or {}).get("user_agent", "news-pipeline/0.1")})
    health = _health(root)
    items, per, used = [], [], ""
    try:
        # pick an instance: last known good first, then the configured order
        order = x["instances"]
        last = health.get("last_good")
        if last in order:
            order = [last] + [i for i in order if i != last]
        first = x["accounts"][0]["handle"]
        for inst in order:
            ok, res = probe(client, inst, first)
            health.setdefault("instances", {})[inst] = {"ok": ok, "at": iso(now), "note": "" if ok else str(res)}
            if ok:
                used = inst
                break
            log.info("  x mirror %s: %s", inst, res)
        if not used:
            health["last_fail"] = iso(now)
            _save_health(root, health)
            log.warning("  FAIL X: no mirror answered (%s)", ", ".join(x["instances"]))
            return {"items": [], "sources": [{"person": "X", "kind": "x", "url": x["instances"][0],
                                              "status": "error", "error": "no mirror answered"}], "instance": ""}
        health["last_good"] = used
        import time
        for k, a in enumerate(x["accounts"]):
            if k and x.get("delay"):
                time.sleep(x["delay"])           # one account at a time, spaced: a few requests a minute at most
            ok, res = probe(client, used, a["handle"])
            src_url = f"https://x.com/{a['handle']}"
            if not ok:
                per.append({"person": a["name"], "kind": "x", "url": src_url, "status": "error", "error": str(res)})
                continue
            got = []
            for e in res:
                pub = parse_date(e.get("published_parsed") or e.get("published"))
                if pub and pub < since:
                    continue
                title = (e.get("title") or "").strip()
                if title.startswith("RT by") or title.startswith("R to"):      # retweets / replies
                    continue
                text = html_to_text(e.get("summary", "") or e.get("description", "") or title)
                url = _x_url(e.get("link", ""), a["handle"])
                got.append({"id": item_id(url), "url": url, "title": (text[:90] + "…") if len(text) > 90 else text or "(post)",
                            "author": a["name"], "published": iso(pub) if pub else iso(now), "text": text,
                            "text_chars": len(text), "person": a["name"], "tier": a["tier"], "flags": a["flags"],
                            "scrutiny": a["tier"] == "scrutiny", "source_kind": "x", "source_url": src_url,
                            "source_label": "", "source_note": a["why"], "mirror": used,
                            "fetched_at": iso(now), "run_id": run_id})
            items += got
            per.append({"person": a["name"], "kind": "x", "url": src_url, "status": "ok", "new": len(got), "entries": len(res)})
            log.info("  OK   X @%s via %s: %d in window", a["handle"], used, len(got))
        _save_health(root, health)
    finally:
        if own:
            client.close()
    return {"items": items, "sources": per, "instance": used}


LISTS = "data/state/x-lists.json"       # Steven's X lists and their members, read in the browser


def lists(root: Path) -> list:
    try:
        return json.loads((root / LISTS).read_text("utf-8")).get("lists", [])
    except (OSError, json.JSONDecodeError):
        return []


def import_pull(root: Path, cfg: dict, path: Path, run_id: str = "x-pull") -> dict:
    """A JSON file of posts read from an X list page in the browser (data/raw/x-pulls/*.json):
    {"list": ..., "posts": [{url, at, who, context, text, links, quote}]} -> items. Reposts by a list
    member are kept but marked, since on a list page they are the member's signal, not their words."""
    d = json.loads(path.read_text("utf-8"))
    now = dt.datetime.now(UTC)
    known = {a["handle"].lower(): a for a in load_x(root)["accounts"]}
    members = {m["handle"].lower(): m for l in lists(root) if l["name"] == d.get("list") for m in l["members"]}
    items = []
    for p in d.get("posts") or []:
        m = re.search(r"/([A-Za-z0-9_]+)/status/(\d+)", str(p.get("url") or ""))
        if not m or not str(p.get("text") or "").strip():
            continue
        handle, url = m.group(1), f"https://x.com/{m.group(1)}/status/{m.group(2)}"
        acct = known.get(handle.lower())
        who = str(p.get("who") or "").split("@")[0].strip() or handle
        name = acct["name"] if acct else (members.get(handle.lower()) or {}).get("name") or who
        text = " ".join(str(p["text"]).split())
        if p.get("quote"):
            text += "\n\nQuoting: " + " ".join(str(p["quote"]).split())
        links = [clean_url(u) for u in (p.get("links") or []) if str(u).startswith("http") and "t.co/" not in str(u)]
        if links:
            text += "\n\nLinked: " + " ".join(links)
        ctx = str(p.get("context") or "")
        note = (acct["why"] if acct else f"Member of Steven's X list \"{d.get('list', '')}\".")
        if ctx:
            note += f" Seen as a repost ({ctx}): the reposter's interest, not their words."
        pub = parse_date(str(p.get("at") or "")) or now
        tier = acct["tier"] if acct else "list"
        items.append({"id": item_id(url), "url": url, "title": (text[:90] + "…") if len(text) > 90 else text,
                      "author": name, "published": iso(pub), "text": text, "text_chars": len(text), "person": name,
                      "tier": tier, "flags": (acct or {}).get("flags", []), "scrutiny": tier == "scrutiny",
                      "source_kind": "x", "source_url": f"https://x.com/{handle}", "source_label": "",
                      "source_note": note, "linked_url": links[0] if links else "", "via": "browser-pull",
                      "x_list": d.get("list", ""), "fetched_at": iso(now), "run_id": run_id})
    return {"items": items, "list": d.get("list", ""), "read": len(d.get("posts") or [])}


def status(root: Path) -> dict:
    x = load_x(root)
    h = _health(root)
    from .archive import read_jsonl
    counts = {}
    for r in read_jsonl(root / "data" / "index.jsonl"):
        if r.get("source_kind") == "x":
            c = counts.setdefault(r.get("person"), {"count": 0, "latest": ""})
            c["count"] += 1
            c["latest"] = max(c["latest"], (r.get("published") or "")[:10])
    return {"accounts": [{**a, **counts.get(a["name"], {"count": 0, "latest": ""})} for a in x["accounts"]],
            "instances": [{"url": i, **(h.get("instances", {}).get(i, {}))} for i in x["instances"]],
            "last_good": h.get("last_good", ""), "last_fail": h.get("last_fail", ""), "lists": lists(root)}
