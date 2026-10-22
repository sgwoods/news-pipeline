"""Fetch new items from every verified source.

Feeds: entries inside the lookback window. Page sources: URLs not seen before
(first run records a baseline instead of back-filling the whole site).
Every item carries its source URL. All fetched text is stored as data only.
"""
from __future__ import annotations

import datetime as dt

from . import pages
from .archive import Archive
from .textutil import UTC, clean_url, extract_page, html_to_text, iso, item_id, parse_date

OLD_PAGE_GRACE_DAYS = 7   # page items older than window - this are skipped as back-catalogue


def _base(src: dict, run_id: str, now: dt.datetime) -> dict:
    return {"person": src["person"], "tier": src.get("tier", ""), "flags": src.get("flags", []),
            "scrutiny": bool(src.get("scrutiny")), "source_kind": src["kind"],
            "source_url": src["url"], "source_label": src.get("label", ""),
            "fetched_at": iso(now), "run_id": run_id}


def fetch_feed(client, src, since, now, cfg, run_id, log) -> tuple:
    import feedparser
    r = client.get(src["url"])
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    parsed = feedparser.parse(r.content)
    if not parsed.entries and parsed.get("bozo"):
        raise RuntimeError(f"unparseable feed: {parsed.get('bozo_exception')}")
    items, older = [], 0
    for e in parsed.entries:
        url = clean_url(e.get("link") or "")
        if not url:
            continue
        pub = parse_date(e.get("published_parsed") or e.get("updated_parsed")
                         or e.get("published") or e.get("updated"))
        if pub and pub < since:
            older += 1
            continue
        html = ""
        if e.get("content"):
            html = max((c.get("value", "") for c in e.content), key=len)
        html = html or e.get("summary", "") or e.get("description", "")
        text = html_to_text(html)
        title = (e.get("title") or "").strip()
        if not title or title == url:          # Bluesky posts have no real title
            title = (text[:90] + "…") if len(text) > 90 else text
        it = _base(src, run_id, now)
        it.update({"id": item_id(url), "url": url, "title": title,
                   "author": e.get("author", ""), "published": iso(pub), "text": text,
                   "text_chars": len(text)})
        items.append(it)
    items = items[: cfg.get("max_items_per_source", 25)]
    return items, {"entries": len(parsed.entries), "in_window": len(items), "older": older}


def fetch_pages(client, src, since, now, cfg, run_id, archive: Archive, known: set, log) -> tuple:
    links = pages.discover(client, src)
    key = f"pages-{src['person']}-{src['url']}"
    state = archive.load_state(key)
    all_urls = {u for u, _ in links}
    if state is None:
        # First time: record a baseline; only take items with a lastmod inside the window.
        fresh = [(u, lm) for u, lm in links if parse_date(lm) and parse_date(lm) >= since]
        seen, note = set(), f"baseline recorded ({len(all_urls)} urls)"
        state = {"baseline": iso(now)}
        baseline_seen = all_urls - {u for u, _ in fresh}
    else:
        seen = set(state.get("seen", []))
        fresh = [(u, lm) for u, lm in links if u not in seen]
        note, baseline_seen = "", set()
    fresh = [(u, lm) for u, lm in fresh if item_id(u) not in known]
    cap = cfg.get("max_pages_per_source", 15)
    items, old, errors, processed = [], 0, [], set()
    for u, lm in fresh[:cap]:
        processed.add(u)
        try:
            r = client.get(u)
            if r.status_code != 200:
                errors.append(f"{u}: HTTP {r.status_code}")
                continue
            p = extract_page(r.text)
        except Exception as e:
            errors.append(f"{u}: {type(e).__name__}")
            continue
        pub = parse_date(p["published"]) or parse_date(lm)
        if pub and pub < since - dt.timedelta(days=OLD_PAGE_GRACE_DAYS):
            old += 1
            continue
        it = _base(src, run_id, now)
        it.update({"id": item_id(u), "url": u, "title": p["title"] or u, "author": p["author"],
                   "published": iso(pub), "description": p["description"],
                   "text": p["text"], "text_chars": len(p["text"])})
        items.append(it)
    # Deferred URLs (over the cap) stay unseen so the next run picks them up.
    deferred = {u for u, _ in fresh[cap:]}
    known_urls = {u for u, _ in links if item_id(u) in known}
    state["seen"] = sorted(seen | baseline_seen | processed | known_urls)
    archive.save_state(key, state)
    stats = {"urls_found": len(links), "new_urls": len(fresh), "in_window": len(items),
             "older": old, "page_errors": errors[:10]}
    if note:
        stats["note"] = note
    if deferred:
        stats["deferred"] = len(deferred)
    return items, stats


def fetch_all(sources_rows: list, cfg: dict, archive: Archive, run_id: str, log,
              lookback_hours=None) -> dict:
    import httpx
    f = cfg.get("fetch", {})
    now = dt.datetime.now(UTC)
    since = now - dt.timedelta(hours=lookback_hours or f.get("lookback_hours", 36))
    known = archive.known_ids()
    from .netguard import client as guarded_client          # page URLs come from sitemaps: public hosts only
    client = guarded_client(follow_redirects=True, timeout=f.get("timeout_seconds", 20),
                            headers={"User-Agent": f.get("user_agent", "news-pipeline/0.1")})
    all_items, per_source = [], []
    with client:
        for src in sources_rows:
            label = f"{src['person']} [{src['kind']}] {src['url']}"
            try:
                if src["kind"] == "pages":
                    items, stats = fetch_pages(client, src, since, now, f, run_id, archive, known, log)
                else:
                    items, stats = fetch_feed(client, src, since, now, f, run_id, log)
                new = [i for i in items if i["id"] not in known]
                stats.update({"status": "ok", "new": len(new)})
                all_items += new
                log.info("  OK   %s: %d new", label, len(new))
            except Exception as e:
                stats = {"status": "error", "error": f"{type(e).__name__}: {e}"[:300]}
                log.warning("  FAIL %s: %s", label, stats["error"])
            per_source.append({"person": src["person"], "kind": src["kind"], "url": src["url"], **stats})
    return {"items": all_items, "sources": per_source, "since": iso(since), "now": iso(now)}
