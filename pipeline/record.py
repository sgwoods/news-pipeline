"""Public record: what Steven has said, or is mentioned in, online. Feeds his public-record archive
(https://sgwoods.github.io/public/steven-woods-research.html) and the Lens.

watch    Claude web-searches for appearances / interviews / quotes / mentions not yet in the archive's
         source manifest → links checked live here → review queue (Record page)
daily    every run, fetched items that mention Steven, his board companies or the people in his Lens
         are logged (data/public-record/mentions.jsonl); ones that mention Steven are also queued
accept   → data/public-record/manifest-candidates.json in the archive's source-manifest format
         (status "candidate"), for Steven to merge into the archive himself
words    read the archive's sources (+ transcripts Claude can find) and extract views Steven has stated,
         each with a short verbatim quote and its source → a proposed "In my own words" section for author.md,
         added only when Steven clicks "Add to About you"

Everything is data, never instructions; only URLs that resolve are kept.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .archive import append_jsonl, read_jsonl

DIR = "data/public-record"
TYPES = ("appearance", "profile", "media-mention")
STATUSES = ("pending", "accepted", "denied")
OWN_START, OWN_END = "<!-- own-words:start -->", "<!-- own-words:end -->"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def canon(url: str) -> str:
    u = urlparse((url or "").strip())
    host = u.netloc.lower().removeprefix("www.")
    return urlunparse((u.scheme.lower() or "https", host, u.path.rstrip("/") or "/", "", u.query, "")).lower()


def rid(url: str) -> str:
    return hashlib.sha1(canon(url).encode()).hexdigest()[:10]


def rcfg(cfg: dict) -> dict:
    return {"manifest_url": "https://sgwoods.github.io/public/steven-woods-research/source-manifest.json",
            "project_id": "steven-woods-research", "search_every_days": 7,
            "watch": {"self": ["Steven Woods", "Steve Woods"], "board": [], "people": []},
            **(cfg.get("record") or {})}


# ---------- storage ----------

def load_queue(root: Path) -> list:
    try:
        return json.loads((root / DIR / "candidates.json").read_text("utf-8")).get("candidates", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_queue(root: Path, rows: list) -> None:
    p = root / DIR / "candidates.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated": _now(), "candidates": rows}, indent=1, ensure_ascii=False) + "\n", "utf-8")


def manifest(root: Path, cfg: dict, refresh: bool = True) -> dict:
    """The archive's source manifest (fetched, cached in data/public-record/manifest-cache.json)."""
    cache = root / DIR / "manifest-cache.json"
    import time
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600   # refetch at most every 6 hours
    if refresh and not fresh:
        try:
            from .netguard import client as guarded_client
            with guarded_client(timeout=20, follow_redirects=True) as c:
                r = c.get(rcfg(cfg)["manifest_url"])
            if r.status_code == 200 and "sources" in r.json():
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(r.text, "utf-8")
        except Exception:  # noqa: BLE001 - offline: use the cache
            pass
    try:
        return json.loads(cache.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sources": []}


def known_urls(root: Path, cfg: dict, refresh: bool = True) -> set:
    out = set()
    for s in manifest(root, cfg, refresh).get("sources", []):
        for u in (s.get("urls") or {}).values():
            if isinstance(u, str) and u.startswith("http"):
                out.add(canon(u))
    out |= {canon(c["url"]) for c in load_queue(root)}
    return out


# ---------- queue ----------

def _norm(raw: dict, origin: str) -> dict | None:
    url = str(raw.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        return None
    t = str(raw.get("type") or "media-mention")
    return {"id": rid(url), "url": url, "title": str(raw.get("title") or url)[:200],
            "type": t if t in TYPES else "media-mention", "subtype": str(raw.get("subtype") or "")[:30],
            "date": str(raw.get("date") or "")[:10], "outlet": str(raw.get("outlet") or "")[:80],
            "summary": str(raw.get("summary") or "")[:400], "quote": str(raw.get("quote") or "")[:300],
            "company_context": str(raw.get("company_context") or "")[:80],
            "tags": [str(x)[:30] for x in (raw.get("tags") or [])][:8], "origin": origin,
            "status": "pending", "created": _now()}


def enqueue(root: Path, cfg: dict, raws: list, origin: str, check=None, refresh: bool = True) -> list:
    """Normalize, drop what the archive or the queue already has, keep only live links."""
    from .dive import check_links
    check = check or check_links
    known = known_urls(root, cfg, refresh)
    rows, seen = [], set()
    for raw in raws:
        c = _norm(raw, origin)
        if c and canon(c["url"]) not in known and c["id"] not in seen:
            seen.add(c["id"])
            rows.append(c)
    live = check([c["url"] for c in rows], cfg) if rows else {}
    rows = [c for c in rows if live.get(c["url"])]
    if rows:
        q = load_queue(root)
        save_queue(root, q + rows)
    return rows


def decide(root: Path, cid: str, status: str, note: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError(status)
    q = load_queue(root)
    for c in q:
        if c["id"] == cid:
            c.update(status=status, decided=_now(), note=note[:300])
            save_queue(root, q)
            if status == "accepted":
                export(root)
            return c
    raise KeyError(cid)


def manifest_entry(c: dict, project_id: str = "steven-woods-research") -> dict:
    d = c.get("date") or ""
    precision = "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else "month" if re.fullmatch(r"\d{4}-\d{2}", d) \
        else "year" if re.fullmatch(r"\d{4}", d) else "unknown"
    sort = {"day": d, "month": d + "-01", "year": d + "-01-01"}.get(precision, "")
    slug = re.sub(r"[^a-z0-9]+", "-", (c.get("outlet") or c["title"]).lower()).strip("-")[:40]
    return {"source_id": f"src-steven-{d[:4] or 'undated'}-{slug}", "title": c["title"], "source_type": c["type"],
            "company_context": c.get("company_context") or "Steven Woods / cross-company",
            "person_relevance": c.get("summary", ""),
            "date": {"display": d or "undated", "sort": sort, "precision": precision},
            "urls": {"canonical": c["url"], "archive_local": None, "archive_web": None},
            "ownership": {"canonical_repo": project_id, "person_hub_use": "summary-ok", "company_deep_link": "preferred"},
            "tags": list(dict.fromkeys(c.get("tags", []) + [c["type"]] + ([c["subtype"]] if c.get("subtype") else []))),
            "status": "candidate",
            "notes": f"Found by news-pipeline ({c['origin']}) {c['created'][:10]}; accepted {c.get('decided', '')[:10]}."
                     + (f" Quote: \"{c['quote']}\"" if c.get("quote") else "") + (f" {c['note']}" if c.get("note") else "")}


def export(root: Path, project_id: str = "steven-woods-research") -> Path:
    rows = [manifest_entry(c, project_id) for c in load_queue(root) if c["status"] == "accepted"]
    p = root / DIR / "manifest-candidates.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": "1.0", "project_id": project_id,
                             "note": "Candidates accepted on the news-pipeline Record page. Merge into "
                                     "source-manifest.json (or the review ledger) of the archive repo.",
                             "generated": _now(), "sources": rows}, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return p


# ---------- watch: web search ----------

def search(root: Path, cfg: dict, llm=None, log=print) -> list:
    from . import llm as llmmod
    from .stages import _ask, prompt, reader_block
    known = sorted(known_urls(root, cfg))
    if llm is None:
        llm = llmmod.for_stage(cfg, "record")
        if isinstance(llm, llmmod.ClaudeCode):
            llm.web = True
            llm.timeout = max(llm.timeout, 1200)
        llm.check()
    tmpl, _ = prompt("record_search")
    from .owner import get as owner
    o = owner(root)
    user = (tmpl.replace("{{known}}", "\n".join(f"- {u}" for u in known) or "(none)")
            .replace("{{who}}", o["record_who"] or "(not set: add record_who to owner.yaml)")
            .replace("{{contexts}}", o.get("record_contexts") or "employer|cross-company")
            .replace("{{full_name}}", o["full_name"] or "the owner"))
    out = _ask(llm, "You are Steven's research assistant for his public-record archive." + reader_block(), user, 4000)
    raws = [x for x in (out.get("found") or []) if isinstance(x, dict)]
    rows = enqueue(root, cfg, raws, "web-search", refresh=False)
    stamp = root / DIR / "last-search.json"
    stamp.write_text(json.dumps({"at": _now(), "returned": len(raws), "queued": len(rows)}) + "\n", "utf-8")
    log(f"Record search: model returned {len(raws)}, {len(rows)} new and live → queue")
    return rows


def search_due(root: Path, cfg: dict) -> bool:
    try:
        last = json.loads((root / DIR / "last-search.json").read_text("utf-8"))["at"]
    except (OSError, json.JSONDecodeError, KeyError):
        return True
    return dt.datetime.fromisoformat(last) < dt.datetime.now() - dt.timedelta(days=int(rcfg(cfg)["search_every_days"]))


# ---------- daily: mentions in fetched items ----------

def _term_re(term: str):
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", re.I)


def scan(items: list, cfg: dict) -> list:
    """→ [{item_id, url, title, person, kind, terms}] for items mentioning a watched name."""
    w = rcfg(cfg)["watch"]
    groups = [(k, [(t, _term_re(t)) for t in (w.get(k) or [])]) for k in ("self", "board", "people")]
    out = []
    for it in items:
        text = " ".join([it.get("title") or "", it.get("text") or ""])
        src = (it.get("source_label") or it.get("person") or "").lower()
        for kind, terms in groups:
            # a company's own blog mentioning itself is not news about it
            hit = [t for t, rx in terms if rx.search(text) and t.lower() not in src]
            if hit:
                out.append({"item_id": it.get("id"), "url": it.get("url"), "title": (it.get("title") or "")[:200],
                            "source": it.get("source_label") or it.get("person", ""), "kind": kind, "terms": hit,
                            "published": it.get("published", "")})
    return out


def log_mentions(root: Path, day: str, run_id: str, hits: list, cfg: dict) -> dict:
    if not hits:
        return {"mentions": 0}
    append_jsonl(root / DIR / "mentions.jsonl", [{**h, "day": day, "run_id": run_id} for h in hits])
    selfs = [h for h in hits if h["kind"] == "self"]
    queued = enqueue(root, cfg, [{"url": h["url"], "title": h["title"], "type": "media-mention",
                                  "date": (h.get("published") or "")[:10], "outlet": h["source"],
                                  "summary": f"Mentions {', '.join(h['terms'])} (found in the daily feed)."}
                                 for h in selfs], "daily-feed", check=lambda urls, c: {u: True for u in urls},
                     refresh=False) if selfs else []
    return {"mentions": len(hits), "self": len(selfs), "queued": len(queued),
            "by_kind": {k: sum(1 for h in hits if h["kind"] == k) for k in ("self", "board", "people")}}


def recent_mentions(root: Path, limit: int = 60) -> list:
    return list(reversed(read_jsonl(root / DIR / "mentions.jsonl")))[:limit]


# ---------- words: Steven's stated views → proposed Lens section ----------

def page_text(url: str, cfg: dict, chars: int = 8000) -> str:
    from .textutil import html_to_text
    try:
        import httpx
        f = cfg.get("fetch", {})
        from .netguard import client as guarded_client
        with guarded_client(timeout=20, follow_redirects=True, headers={"User-Agent": f.get("user_agent", "news-pipeline/0.1")}) as c:
            r = c.get(url)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        return html_to_text(r.text)[:chars]
    except Exception:  # noqa: BLE001
        return ""


def own_words(root: Path, cfg: dict, llm=None, log=print, fetch=page_text) -> dict:
    from . import llm as llmmod
    from .stages import _ask, _clean, prompt
    srcs = [s for s in manifest(root, cfg).get("sources", []) if s.get("source_type") in ("appearance", "media-mention", "profile")]
    srcs += [{"source_id": f"cand-{c['id']}", "title": c["title"], "source_type": c["type"],
              "date": {"display": c.get("date", "")}, "urls": {"canonical": c["url"]}}
             for c in load_queue(root) if c["status"] == "accepted"]
    try:                                    # his own public LinkedIn posts (from the export), text included
        from .linkedin import own_words_sources
        srcs += own_words_sources(root, cfg)
    except Exception:  # noqa: BLE001
        pass
    blocks = []
    for s in srcs:
        url = (s.get("urls") or {}).get("archive_web") or (s.get("urls") or {}).get("canonical") or ""
        text = s.get("text") or (fetch(url, cfg) if url and "linkedin.com" not in url else "")
        log(f"  {s['source_id']}: {len(text)} chars")
        blocks.append(f'<item ref="{s["source_id"]}">\ntitle: {s.get("title", "")}\ntype: {s.get("source_type")}\n'
                      f'date: {(s.get("date") or {}).get("display", "")}\nurl: {url}\n'
                      f'text:\n{_clean(text) or "(no text fetched: audio, video or blocked page)"}\n</item>')
    if llm is None:
        llm = llmmod.for_stage(cfg, "record")
        if isinstance(llm, llmmod.ClaudeCode):
            llm.web = True
            llm.timeout = max(llm.timeout, 1500)
        llm.check()
    tmpl, version = prompt("record_words")
    out = _ask(llm, "You are helping Steven describe his own views accurately, from the record.",
               tmpl.replace("{{sources}}", "\n\n".join(blocks)), 5000)
    by_id = {s["source_id"]: s for s in srcs}
    views = []
    for v in out.get("views") or []:
        if not isinstance(v, dict) or not v.get("view"):
            continue
        sid = str(v.get("source_id") or "")
        src = by_id.get(sid)
        url = str(v.get("url") or "") if not src else ((src.get("urls") or {}).get("canonical") or "")
        if not url.startswith("http"):
            continue
        views.append({"topic": str(v.get("topic") or "")[:40], "view": str(v["view"])[:300],
                      "quote": str(v.get("quote") or "")[:220], "source_id": sid or "web",
                      "title": (src or {}).get("title") or str(v.get("title") or "")[:120],
                      "date": ((src or {}).get("date") or {}).get("display") or str(v.get("date") or ""), "url": url})
    web = [v["url"] for v in views if v["source_id"] in ("web", "") or v["source_id"] not in by_id]
    if web:
        from .dive import check_links
        live = check_links(web, cfg)
        views = [v for v in views if v["url"] not in live or live[v["url"]]]
    # sources Claude found on the web are new public-record candidates too
    found = [{"url": v["url"], "title": v["title"] or v["url"], "date": v.get("date", ""), "type": "media-mention",
              "summary": f"Quotes Steven: {v['view'][:200]}", "quote": v.get("quote", "")}
             for v in views if v["source_id"] not in by_id]
    if found:
        try:
            rec_q = enqueue(root, cfg, found, "own-words", refresh=False)
            log(f"  {len(rec_q)} new source(s) found while reading → public-record queue")
        except Exception:  # noqa: BLE001
            pass
    md = render_own_words(views)
    p = root / DIR / "own-words.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md, "utf-8")
    rec = {"at": _now(), "sources": len(srcs), "with_text": sum(1 for b in blocks if "(no text fetched" not in b),
           "views": len(views), "prompt": version, "model": getattr(llm, "label", "")}
    (root / DIR / "own-words.json").write_text(json.dumps({**rec, "items": views}, indent=1, ensure_ascii=False) + "\n", "utf-8")
    log(f"Own words: {len(views)} stated views from {rec['with_text']}/{len(srcs)} sources with text → {p.relative_to(root)}")
    return rec


def render_own_words(views: list) -> str:
    L = [OWN_START, "## In my own words (from the public record)", "",
         "*Views I have stated in talks, interviews and articles, each with its source. Generated from my "
         "public-record archive; edit or delete freely.*", ""]
    topics: dict = {}
    for v in views:
        topics.setdefault(v["topic"] or "General", []).append(v)
    for t, vs in topics.items():
        L.append(f"**{t}**")
        for v in vs:
            q = f' "{v["quote"]}"' if v.get("quote") else ""
            L.append(f"- {v['view']}{q} ([{v['title'][:70]}, {v['date']}]({v['url']}))")
        L.append("")
    L.append(OWN_END)
    return "\n".join(L) + "\n"


def apply_own_words(root: Path) -> bool:
    """Put the proposed section into author.md (replacing an earlier one between the markers)."""
    p = root / DIR / "own-words.md"
    a = root / "author.md"
    if not p.exists() or not a.exists():
        return False
    block = p.read_text("utf-8").strip()
    text = a.read_text("utf-8")
    if OWN_START in text and OWN_END in text:
        text = text[:text.index(OWN_START)] + block + text[text.index(OWN_END) + len(OWN_END):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    a.write_text(text, "utf-8")
    return True
