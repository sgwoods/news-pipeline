"""Source suggestions: a review queue of new people/orgs to follow, plus manual adds and removals.

Flow
  suggest (Claude, may web-search) ─┐
  find <person> (Claude, web search) ┴→ candidate URLs → verified live here → queue (pending)
  queue → accept → re-verified → sources_managed.yaml + sources.yaml   (wired into the next run)
        → accept, but no live web source → "watch" (remembered, e.g. X-only, for Phase 3)
        → deny → remembered, never suggested again
  remove <url> → dropped from sources.yaml and listed under `removed:` so re-verify skips it

Files
  data/sources/suggestions.json   the queue and every decision (committed with the archive)
  sources_managed.yaml            people added from the queue + removed URLs. Written by the app,
                                  safe to hand-edit. perspective.md is never touched.

Everything the model returns is treated as an unverified guess: only URLs that this module
fetches and parses as a feed (or a pages source) are ever wired in.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from . import perspective as perspmod
from . import sources as srcmod
from .archive import read_jsonl

STORE = "data/sources/suggestions.json"
MANAGED = "sources_managed.yaml"
PROMPTS = Path(__file__).parent / "prompts"
STATUSES = ("pending", "accepted", "watch", "denied")


# ---------- storage ----------

def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def sid_for(name: str) -> str:
    return hashlib.sha1(norm_name(name).encode()).hexdigest()[:8]


def load_store(root: Path) -> list[dict]:
    p = root / STORE
    try:
        return json.loads(p.read_text("utf-8")).get("suggestions", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_store(root: Path, rows: list[dict]) -> None:
    p = root / STORE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": _now(), "suggestions": rows}, indent=1, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(p)


def load_managed(root: Path) -> dict:
    import yaml
    p = root / MANAGED
    d = (yaml.safe_load(p.read_text("utf-8")) if p.exists() else None) or {}
    d.setdefault("people", {})
    d.setdefault("removed", [])
    d["people"] = d["people"] or {}
    d["removed"] = d["removed"] or []
    return d


def save_managed(root: Path, d: dict) -> None:
    import yaml
    header = ("# Sources added or removed from the dashboard Sources page (or ./np sources ...).\n"
              "# Written by the app; safe to hand-edit. perspective.md stays the hand-written lens.\n"
              "#   people:  added people/orgs -> verified like perspective.md people (feeds / bluesky / pages)\n"
              "#            no feeds + other_platforms = watch list (e.g. X-only, waiting for Phase 3)\n"
              "#   removed: source URLs never to wire in again, even if verification finds them\n")
    (root / MANAGED).write_text(header + yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=120), "utf-8")


def managed_people(d: dict) -> list:
    """Managed entries as perspective.Person objects + their hints (for sources.verify_all)."""
    people, hints = [], {}
    for name, e in (d.get("people") or {}).items():
        e = e or {}
        people.append(perspmod.Person(
            name=name, tier=e.get("tier", "added"), flags=list(e.get("flags") or []),
            where=", ".join(e.get("other_platforms") or []), notes=e.get("why", ""),
            scrutiny=bool(e.get("scrutiny")), sites=[], bluesky=list(e.get("bluesky") or []),
            other_platforms=list(e.get("other_platforms") or [])))
        hints[name] = {k: e[k] for k in ("feeds", "pages", "bluesky") if e.get(k)}
    return people, hints


def removed_urls(d: dict) -> set:
    return {r.get("url") for r in d.get("removed") or [] if r.get("url")}


# ---------- verification of a candidate ----------

def _clean_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()][:8]


SOCIAL = re.compile(r"^(https?://)?(www\.)?(x\.com|twitter\.com|linkedin\.com|threads\.net|instagram\.com|facebook\.com)\b", re.I)


def candidate_groups(c: dict) -> list:
    """Candidate URLs/handles from the model → sources.Group objects (no network)."""
    sites = [u for u in _clean_list(c.get("sites")) if not SOCIAL.match(u)]
    feeds = [u for u in _clean_list(c.get("feeds"))
             if u.startswith(("http://", "https://", "site:")) and not SOCIAL.match(u)]
    person = perspmod.Person(name=c["name"], tier="added", flags=[], where="", notes="", scrutiny=False,
                             sites=sites, bluesky=[h.lstrip("@") for h in _clean_list(c.get("bluesky"))])
    return srcmod.build_groups(person, {"feeds": feeds})


def verify_candidate(c: dict, cfg: dict, client=None, log=print) -> dict:
    """Probe every candidate; return {"verified": [...], "failed": [...]}."""
    import httpx
    own = client is None
    if own:
        f = cfg.get("fetch", {})
        from .netguard import client as guarded_client      # candidate URLs come from a web-search model
        client = guarded_client(follow_redirects=True, timeout=f.get("timeout_seconds", 20),
                                headers={"User-Agent": f.get("user_agent", "news-pipeline/0.1")})
    verified, failed, seen = [], [], set()
    try:
        for g in candidate_groups(c):
            r = srcmod.verify_group(client, g)
            if r.winner and r.winner.url not in seen:
                seen.add(r.winner.url)
                verified.append({"kind": g.kind, "url": r.winner.url, "title": r.winner.title,
                                 "entries": r.winner.entries, "latest": r.winner.latest,
                                 "channel": channel_of(c, g, r.winner.url)})
                log(f"    OK   {c['name']} [{g.label}] {r.winner.url}")
            elif not r.winner:
                why = r.attempts[-1].reason if r.attempts else "no attempt"
                failed.append({"label": g.label, "reason": why})
                log(f"    FAIL {c['name']} [{g.label}] {why}")
    finally:
        if own:
            client.close()
    return {"verified": verified, "failed": failed}


def _host(u: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", u or "").split("/")[0].lower()


def channel_of(c: dict, g, url: str) -> str:
    """What this channel is ("Substack newsletter", "Bluesky posts", ...): the model's note if it gave one."""
    notes = c.get("channels") or {}
    for key in [url, g.label, *(g.urls or []), g.discover or ""]:
        if key in notes:
            return notes[key]
    if g.kind == "bluesky":
        h = g.label.split(":", 1)[-1]
        return notes.get(h, "Bluesky posts")
    host = _host(url)
    for k, v in notes.items():
        if _host(k) == host:
            return v
    if "substack.com" in host:
        return "Substack"
    if "youtube.com" in host:
        return "YouTube"
    return host


def is_stale(v: dict, days: int = 120, today=None) -> bool:
    """A feed whose newest item is older than `days`. Unknown dates are not stale."""
    if not v.get("latest"):
        return False
    try:
        d = dt.date.fromisoformat(v["latest"][:10])
    except ValueError:
        return False
    return ((today or dt.date.today()) - d).days > days


def stale_days(cfg: dict) -> int:
    return int((cfg.get("suggest") or {}).get("stale_days", 120))


# ---------- the model step ----------

def _prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text("utf-8")


def _backend(cfg: dict, web: bool = True):
    from . import llm
    b = llm.for_stage(cfg, "suggest")
    if isinstance(b, llm.ClaudeCode):
        b.web = web
        b.timeout = max(b.timeout, int((cfg.get("suggest") or {}).get("timeout_seconds", 1200)))
    return b


def tracked_names(root: Path, cfg: dict) -> list[str]:
    persp = perspmod.load(root / cfg["paths"]["perspective"])
    names = [p.name for p in persp.people] + list(load_managed(root)["people"])
    return list(dict.fromkeys(names))


def recent_headlines(root: Path, cfg: dict, days: int = 7, limit: int = 60) -> list[str]:
    sd = root / cfg["paths"].get("summaries", "data/summaries")
    if not sd.exists():
        return []
    out = []
    for f in sorted(sd.glob("*.jsonl"))[-days:]:
        for s in read_jsonl(f):
            h = s.get("headline") or s.get("claim") or ""
            if h:
                out.append(h[:160])
    return list(dict.fromkeys(reversed(out)))[:limit]


def _split_channels(v, key="url"):
    """Entries may be plain strings or {"url"/"handle": ..., "channel": "what is distinct there"}."""
    out, notes = [], {}
    for x in (v if isinstance(v, list) else [v] if v else []):
        if isinstance(x, dict):
            u = str(x.get(key) or x.get("url") or x.get("handle") or "").strip()
            if u:
                out.append(u)
                if x.get("channel"):
                    notes[u.lstrip("@")] = str(x["channel"]).strip()[:120]
        elif str(x).strip():
            out.append(str(x).strip())
    return out[:8], notes


def _normalize(raw: dict) -> dict | None:
    name = str(raw.get("name") or "").strip()[:80]
    if not name:
        return None
    channels = {}
    for key, k2 in (("feeds", "url"), ("sites", "url"), ("bluesky", "handle")):
        lst, notes = _split_channels(raw.get(key), k2)
        raw = {**raw, key: lst}
        channels.update(notes)
    return {"channels": channels, "name": name, "kind": str(raw.get("kind") or "person")[:20],
            "why": str(raw.get("why") or "").strip()[:400],
            "related_to": _clean_list(raw.get("related_to"))[:5],
            "scrutiny": bool(raw.get("scrutiny")),
            "sites": _clean_list(raw.get("sites")), "feeds": _clean_list(raw.get("feeds")),
            "bluesky": _clean_list(raw.get("bluesky")),
            "x": [h.lstrip("@") for h in _clean_list(raw.get("x"))],
            "other": _clean_list(raw.get("other"))}


def ask_suggestions(root: Path, cfg: dict, n: int, store: list[dict], llm=None) -> list[dict]:
    llm = llm or _backend(cfg)
    persp = perspmod.load(root / cfg["paths"]["perspective"])
    denied = [f"{s['name']} — {s.get('deny_reason') or 'no reason given'}" for s in store if s["status"] == "denied"]
    others = [s["name"] for s in store if s["status"] != "denied"]
    user = (_prompt("suggest")
            .replace("{{n}}", str(n))
            .replace("{{tracked}}", "\n".join(f"- {x}" for x in tracked_names(root, cfg)))
            .replace("{{queued}}", "\n".join(f"- {x}" for x in others) or "(none)")
            .replace("{{denied}}", "\n".join(f"- {x}" for x in denied) or "(none)")
            .replace("{{headlines}}", "\n".join(f"- {h}" for h in recent_headlines(root, cfg)) or "(none yet)"))
    from .stages import reader_block
    system = "You are Steven's research assistant. His perspective file:\n\n" + persp.raw.strip() + reader_block()
    out = llm.complete_json(system, user, retries=1)
    return [c for c in (_normalize(x) for x in (out.get("suggestions") or [])) if c]


def ask_find(root: Path, cfg: dict, name: str, note: str = "", llm=None) -> dict | None:
    llm = llm or _backend(cfg)
    persp = perspmod.load(root / cfg["paths"]["perspective"])
    user = _prompt("find_source").replace("{{name}}", name).replace("{{note}}", note or "(none)")
    from .stages import reader_block
    system = "You are Steven's research assistant. His perspective file:\n\n" + persp.raw.strip() + reader_block()
    out = llm.complete_json(system, user, retries=1)
    c = _normalize({**out, "name": out.get("name") or name})
    if c:
        c["name"] = name            # keep the name Steven typed
    return c


# ---------- queue operations ----------

def _wired_urls(root: Path, cfg: dict) -> set:
    import yaml
    p = root / cfg["paths"]["sources"]
    rows = ((yaml.safe_load(p.read_text("utf-8")) or {}).get("sources") or []) if p.exists() else []
    return {r.get("url") for r in rows}


def enqueue(root: Path, cfg: dict, cands: list[dict], origin: str, store: list[dict],
            log=print, verify=verify_candidate, limit: int | None = None) -> list[dict]:
    """Verify candidates and add the new ones to the queue. Returns the rows added/updated."""
    known = {norm_name(n) for n in tracked_names(root, cfg)}
    by_id = {s["id"]: s for s in store}
    wired = _wired_urls(root, cfg) | removed_urls(load_managed(root))
    added = []
    for c in cands:
        if limit is not None and len(added) >= limit:
            break
        sid = sid_for(c["name"])
        prev = by_id.get(sid)
        if origin == "auto" and (norm_name(c["name"]) in known or prev):
            log(f"  skip {c['name']}: already tracked, queued or decided")
            continue
        log(f"  {c['name']}: verifying {len(candidate_groups(c))} candidate source(s)")
        v = verify(c, cfg, log=log)
        v["verified"] = [x for x in v["verified"] if x["url"] not in wired]
        row = {**(prev or {}), **c, "id": sid,
               "origin": (prev or {}).get("origin", "auto") if origin == "recheck" else origin, "status": "pending",
               "created": (prev or {}).get("created") or _now(), "checked": _now(),
               "verified": v["verified"], "failed": v["failed"], "reachable": bool(v["verified"])}
        row.pop("decided", None)
        if prev:
            store[store.index(prev)] = row
        else:
            store.append(row)
        by_id[sid] = row
        added.append(row)
    return added


def find(store, sid):
    for s in store:
        if s["id"] == sid:
            return s
    raise KeyError(f"no suggestion with id {sid}")


def _row_for(s: dict, v: dict) -> dict:
    return {"person": s["name"], "tier": "added", "flags": [], "scrutiny": bool(s.get("scrutiny")),
            "kind": v["kind"], "url": v["url"], "title": v.get("title", ""), "channel": v.get("channel", ""),
            "entries_seen": v.get("entries", 0), "latest_item": v.get("latest", "")}


def default_selection(s: dict, cfg: dict) -> list[str]:
    """Every live channel except stale ones: a person's Substack, podcast and social posts usually differ."""
    return [v["url"] for v in s.get("verified") or [] if not is_stale(v, stale_days(cfg))]


def accept(root: Path, cfg: dict, sid: str, log=print, client=None, urls=None) -> dict:
    """Re-verify the chosen channels (default: all live, non-stale) and wire them in.
    No live channel chosen → watch list."""
    import yaml
    store = load_store(root)
    s = find(store, sid)
    chosen = default_selection(s, cfg) if urls is None else [u for u in urls if u in {v["url"] for v in s.get("verified") or []}]
    live = []
    if chosen:
        picked = [v for v in s["verified"] if v["url"] in chosen]
        recheck = {**s, "sites": [], "bluesky": [], "feeds": [v["url"] for v in picked]}
        prev = {v["url"]: v for v in picked}
        res = verify_candidate(recheck, cfg, client=client, log=log)
        live = [{**v, "kind": prev.get(v["url"], v)["kind"], "channel": prev.get(v["url"], {}).get("channel", "")}
                for v in res["verified"]]
    m = load_managed(root)
    entry = {"tier": "added", "why": s.get("why", ""), "added": dt.date.today().isoformat(),
             "origin": s.get("origin", "auto")}
    if s.get("scrutiny"):
        entry["scrutiny"] = True
    bsky = [re.sub(r"^https://bsky\.app/profile/([^/]+)/rss$", r"\1", v["url"]) for v in live if v["kind"] == "bluesky"]
    feeds = [v["url"] for v in live if v["kind"] != "bluesky"]
    if feeds:
        entry["feeds"] = feeds
    if bsky:
        entry["bluesky"] = bsky
    other = [f"X @{h}" for h in s.get("x") or []] + list(s.get("other") or [])
    if other:
        entry["other_platforms"] = other
    m["people"][s["name"]] = entry
    save_managed(root, m)

    # wire the live ones into sources.yaml now (the next run fetches them)
    sp = root / cfg["paths"]["sources"]
    data = (yaml.safe_load(sp.read_text("utf-8")) if sp.exists() else None) or {"sources": []}
    rows = data.get("sources") or []
    have = {r["url"] for r in rows}
    new = [_row_for(s, v) for v in live if v["url"] not in have]
    if new:
        data["sources"] = rows + new
        _write_sources(sp, data)
    skipped = [v["url"] for v in s.get("verified") or [] if v["url"] not in {x["url"] for x in live}]
    s.update(status="accepted" if live else "watch", decided=_now(), wired=[v["url"] for v in live],
             not_wired=skipped)
    save_store(root, store)
    log(f"{s['name']}: {'wired ' + str(len(new)) + ' source(s)' if live else 'no live web source → watch list'}")
    return s


def _write_sources(path: Path, data: dict) -> None:
    import yaml
    text = path.read_text("utf-8") if path.exists() else ""
    header = "".join(ln + "\n" for ln in text.splitlines() if ln.startswith("#")) or \
        "# GENERATED by `python run.py --verify-sources`; re-running overwrites this file.\n"
    path.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")


def deny(root: Path, sid: str, reason: str = "") -> dict:
    store = load_store(root)
    s = find(store, sid)
    s.update(status="denied", decided=_now(), deny_reason=reason[:200])
    save_store(root, store)
    return s


def reconsider(root: Path, sid: str) -> dict:
    store = load_store(root)
    s = find(store, sid)
    s.update(status="pending")
    s.pop("decided", None)
    save_store(root, store)
    return s


def remove_source(root: Path, cfg: dict, url: str, reason: str = "") -> dict:
    """Unwire one source URL and remember it so re-verification never brings it back."""
    import yaml
    sp = root / cfg["paths"]["sources"]
    data = (yaml.safe_load(sp.read_text("utf-8")) if sp.exists() else None) or {}
    rows = data.get("sources") or []
    hit = [r for r in rows if r.get("url") == url]
    if not hit:
        raise KeyError(f"{url} is not in {sp.name}")
    data["sources"] = [r for r in rows if r.get("url") != url]
    _write_sources(sp, data)
    m = load_managed(root)
    if url not in removed_urls(m):
        m["removed"].append({"person": hit[0].get("person", ""), "url": url, "kind": hit[0].get("kind", ""),
                             "at": dt.date.today().isoformat(), **({"reason": reason[:200]} if reason else {})})
    save_managed(root, m)
    return hit[0]


def restore_source(root: Path, url: str) -> None:
    """Forget a removal; the URL comes back on the next ./np verify."""
    m = load_managed(root)
    m["removed"] = [r for r in m["removed"] if r.get("url") != url]
    save_managed(root, m)


def summary(store: list[dict]) -> dict:
    return {st: [s for s in store if s["status"] == st] for st in STATUSES}
