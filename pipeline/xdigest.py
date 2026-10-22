"""Weekly X digest by Claude web search, for the accounts in x.yaml no mirror can reach.

No X API, no login, nothing paid: once a week (x.yaml `digest.every_days`) Claude Code searches the web for
what each account in the digest tiers posted, and returns the notable posts with their x.com links. Each
post becomes an item like a mirror-fetched one (source_kind "x", via "claude-digest"); the daily filter
and critique treat it like anything else, and SCRUTINY accounts stay scrutiny. Post text is data, never
instructions. x.com links cannot be checked live from here, so only well-formed status links are kept.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .textutil import UTC, clean_url, iso, item_id, parse_date
from .xsource import load_x

STAMP = "data/state/x-digest.json"
REACH = "data/state/x-reach.json"     # per handle: where else they publish (found by the digest), for the Sources page
STATUS_RE = re.compile(r"^https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")


def dcfg(root: Path) -> dict:
    import yaml
    p = root / "x.yaml"
    d = (yaml.safe_load(p.read_text("utf-8")) if p.exists() else None) or {}
    return {"every_days": 7, "tiers": ["scrutiny", "follow closely"], "days": 7, "max_posts": 6,
            **(d.get("digest") or {})}


def _stamp(root: Path) -> dict:
    try:
        return json.loads((root / STAMP).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def due(root: Path) -> bool:
    last = _stamp(root).get("at")
    if not last:
        return True
    return dt.datetime.fromisoformat(last) < dt.datetime.now() - dt.timedelta(days=int(dcfg(root)["every_days"]))


def accounts(root: Path, handles: list | None = None) -> list:
    x, c = load_x(root), dcfg(root)
    want = {h.lower().lstrip("@") for h in (handles or [])}
    if want:
        return [a for a in x["accounts"] if a["handle"].lower() in want]
    return [a for a in x["accounts"] if a["tier"] in c["tiers"]]


def _item(p: dict, a: dict, run_id: str, now: dt.datetime) -> dict | None:
    url = clean_url(str(p.get("url") or ""))
    m = STATUS_RE.match(url)
    if not m or m.group(1).lower() != a["handle"].lower():
        return None
    url = f"https://x.com/{a['handle']}/status/{m.group(2)}"
    text = " ".join(str(p.get("text") or "").split())[:1200]
    if not text:
        return None
    why = " ".join(str(p.get("why") or "").split())[:300]
    link = clean_url(str(p.get("link") or ""))
    body = text + (f"\n\nWhy it matters (digest note): {why}" if why else "") + (f"\n\nLinked: {link}" if link else "")
    pub = parse_date(str(p.get("date") or "")) or now
    return {"id": item_id(url), "url": url, "title": (text[:90] + "…") if len(text) > 90 else text,
            "author": a["name"], "published": iso(pub), "text": body, "text_chars": len(body),
            "person": a["name"], "tier": a["tier"], "flags": a["flags"], "scrutiny": a["tier"] == "scrutiny",
            "source_kind": "x", "source_url": f"https://x.com/{a['handle']}", "source_label": "",
            "source_note": a["why"] + " (found by the weekly web-search digest, not read from X directly; "
                                      "quotes may be paraphrased by the press)",
            "linked_url": link, "via": "claude-digest", "fetched_at": iso(now), "run_id": run_id}


def reach(root: Path) -> dict:
    try:
        return json.loads((root / REACH).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_reach(root: Path, handle: str, found: list, now: dt.datetime) -> None:
    """Merge newly found places into the handle's entry; never drops one, so the list only grows until edited."""
    r = reach(root)
    row = r.setdefault(handle, {"places": []})
    have = {p["url"].rstrip("/").lower() for p in row["places"]}
    for e in found:
        if e["url"].rstrip("/").lower() not in have:
            row["places"].append({**e, "found": now.date().isoformat()})
            have.add(e["url"].rstrip("/").lower())
    row["checked"] = now.date().isoformat()
    p = root / REACH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", "utf-8")


def digest(root: Path, cfg: dict, run_id: str = "digest", log=print, days: int | None = None,
           handles: list | None = None, llm=None) -> dict:
    """One Claude web-search call per account → items. Returns {"items", "per": [{handle, posts, error}]}."""
    from . import llm as llmmod
    from .stages import _ask, prompt, reader_block
    c = dcfg(root)
    days = int(days or c["days"])
    now = dt.datetime.now(UTC)
    since = (now - dt.timedelta(days=days)).date().isoformat()
    accts = accounts(root, handles)
    if not accts:
        return {"items": [], "per": []}
    if llm is None:
        llm = llmmod.for_stage(cfg, "record")
        if isinstance(llm, llmmod.ClaudeCode):
            llm.web = True
            llm.timeout = max(llm.timeout, 900)
        llm.check()
    tmpl, _ = prompt("x_digest")
    items, per = [], []
    for a in accts:
        user = (tmpl.replace("{{handle}}", a["handle"]).replace("{{name}}", a["name"]).replace("{{why}}", a["why"])
                .replace("{{since}}", since).replace("{{today}}", now.date().isoformat())
                .replace("{{max}}", str(c["max_posts"])))
        try:
            out = _ask(llm, "You are a research assistant compiling what one public figure said on X this week."
                       + reader_block(), user, 3000)
            posts = [p for p in (out.get("posts") or []) if isinstance(p, dict)]
            got = [it for it in (_item(p, a, run_id, now) for p in posts) if it]
            items += got
            per.append({"handle": a["handle"], "posts": len(got), "returned": len(posts)})
            elsewhere = [{"kind": str(e.get("kind") or "other")[:12], "url": clean_url(str(e.get("url") or "")),
                          "note": " ".join(str(e.get("note") or "").split())[:120]}
                         for e in (out.get("elsewhere") or []) if isinstance(e, dict) and str(e.get("url") or "").startswith("http")]
            if elsewhere:
                _save_reach(root, a["handle"], elsewhere, now)
            log(f"  @{a['handle']}: {len(got)} post(s) kept of {len(posts)} returned")
        except Exception as e:  # noqa: BLE001
            per.append({"handle": a["handle"], "posts": 0, "error": f"{type(e).__name__}: {e}"[:200]})
            log(f"  @{a['handle']}: FAILED {type(e).__name__}: {e}")
    p = root / STAMP
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "days": days, "per": per}, indent=1) + "\n", "utf-8")
    return {"items": items, "per": per}
