"""Resolve and verify RSS/Atom feeds for every tracked person.

Candidates come from perspective.md (domains, Bluesky handles) plus source_hints.yaml.
Each candidate group is tried until one URL returns a parseable feed with entries.
Verified feeds go to sources.yaml; everything that failed, and every person with no
feed candidates at all, goes into a report under logs/. Nothing is silently dropped.

Fetched feed content is only inspected for metadata (title, entry count, dates).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from . import pages as pagesmod
from .perspective import Person

COMMON_PATHS = ["feed", "feed/", "rss", "rss/", "rss.xml", "atom.xml",
                "feed.xml", "index.xml", "posts.atom"]

_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*["\']([^"\']*)["\']')


@dataclass
class Group:
    person: str
    kind: str                 # site | bluesky | feed | pages
    label: str
    urls: list[str]           # for pages: "sitemap:<url>" / "listing:<url>"
    discover: str | None = None   # page to scan for <link rel="alternate">
    options: dict = field(default_factory=dict)   # pages: include / exclude


@dataclass
class Attempt:
    url: str
    ok: bool
    reason: str
    title: str = ""
    entries: int = 0
    latest: str = ""


@dataclass
class GroupResult:
    group: Group
    winner: Attempt | None
    attempts: list[Attempt] = field(default_factory=list)


# ---------- candidate building (pure, no network) ----------

def bluesky_rss(handle: str) -> str:
    return f"https://bsky.app/profile/{handle.strip().lstrip('@')}/rss"


def _site_group(person: str, base: str, kind: str = "site") -> Group:
    if not base.startswith("http"):
        base = "https://" + base
    base = base.rstrip("/")
    return Group(person, kind, base, [f"{base}/{p}" for p in COMMON_PATHS], discover=base)


def build_groups(person: Person, hints: dict | None) -> list[Group]:
    hints = hints or {}
    groups: list[Group] = []
    for site in person.sites:
        groups.append(_site_group(person.name, site))
    handles = list(dict.fromkeys(person.bluesky + list(hints.get("bluesky") or [])))
    for h in handles:
        groups.append(Group(person.name, "bluesky", f"bluesky:{h}", [bluesky_rss(h)]))
    for item in hints.get("feeds") or []:
        if isinstance(item, str) and item.startswith("site:"):
            groups.append(_site_group(person.name, item[5:]))
        else:
            urls = [item] if isinstance(item, str) else list(item)
            groups.append(Group(person.name, "feed", urls[0], urls))
    for spec in hints.get("pages") or []:
        tries = list(spec.get("try") or [])
        if tries:
            groups.append(Group(person.name, "pages", f"pages:{tries[0]}", tries,
                                options={"include": spec.get("include") or ["/"],
                                         "exclude": spec.get("exclude") or [],
                                         **({"label": spec["label"]} if spec.get("label") else {})}))
    return groups


def split_page_candidate(c: str) -> tuple:
    method, _, url = c.partition(":")
    return method, url


def find_feed_links(html: str, base_url: str) -> list[str]:
    out = []
    for tag in _LINK_TAG_RE.findall(html):
        attrs = {k.lower(): v for k, v in _ATTR_RE.findall(tag)}
        if "alternate" in attrs.get("rel", "").lower() and \
                re.search(r"(rss|atom)\+xml", attrs.get("type", ""), re.I) and attrs.get("href"):
            url = urljoin(base_url + "/", attrs["href"])
            if url not in out:
                out.append(url)
    return out


# ---------- network ----------

def _probe(client, url: str) -> Attempt:
    import feedparser
    try:
        r = client.get(url)
    except Exception as e:  # network errors, TLS, timeouts
        return Attempt(url, False, f"error: {type(e).__name__}: {e}"[:200])
    if r.status_code != 200:
        return Attempt(url, False, f"HTTP {r.status_code}")
    parsed = feedparser.parse(r.content)
    n = len(parsed.entries)
    if n == 0:
        why = "not a feed" if not parsed.get("version") else "feed has no entries"
        return Attempt(str(r.url), False, why)
    latest = ""
    for e in parsed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            latest = max(latest, dt.datetime(*t[:6]).strftime("%Y-%m-%d"))
    return Attempt(str(r.url), True, "ok", parsed.feed.get("title", ""), n, latest)


def _verify_pages(client, g: Group) -> GroupResult:
    res = GroupResult(g, None)
    for c in g.urls:
        method, url = split_page_candidate(c)
        try:
            links = pagesmod.discover(client, {"method": method, "url": url, **g.options})
        except Exception as e:
            res.attempts.append(Attempt(c, False, f"{type(e).__name__}: {e}"[:200]))
            continue
        if not links:
            res.attempts.append(Attempt(c, False, "no matching article URLs"))
            continue
        latest = max((lm[:10] for _, lm in links if lm), default="")
        a = Attempt(c, True, "ok", f"e.g. {links[0][0]}", len(links), latest)
        res.attempts.append(a)
        res.winner = a
        break
    return res


def verify_group(client, g: Group) -> GroupResult:
    if g.kind == "pages":
        return _verify_pages(client, g)
    res = GroupResult(g, None)
    urls = []
    if g.discover:
        try:
            r = client.get(g.discover)
            if r.status_code == 200:
                urls += find_feed_links(r.text, str(r.url))
            else:
                res.attempts.append(Attempt(g.discover, False, f"page HTTP {r.status_code}"))
        except Exception as e:
            res.attempts.append(Attempt(g.discover, False, f"page error: {type(e).__name__}"))
    for u in urls + g.urls:
        if any(a.url == u for a in res.attempts):
            continue
        a = _probe(client, u)
        res.attempts.append(a)
        if a.ok:
            res.winner = a
            break
    return res


def verify_all(people: list[Person], hints: dict, cfg: dict, log=print) -> dict:
    import httpx
    fetch = cfg.get("fetch", {})
    from .netguard import client as guarded_client
    client = guarded_client(follow_redirects=True, timeout=fetch.get("timeout_seconds", 20),
                            headers={"User-Agent": fetch.get("user_agent", "news-pipeline/0.1")})
    results: list[GroupResult] = []
    no_candidates: list[Person] = []
    with client:
        for p in people:
            groups = build_groups(p, hints.get(p.name))
            if not groups:
                no_candidates.append(p)
                log(f"  -  {p.name}: no feed candidates ({', '.join(p.other_platforms) or 'none'})")
                continue
            for g in groups:
                r = verify_group(client, g)
                results.append(r)
                mark = "OK" if r.winner else "FAIL"
                detail = r.winner.url if r.winner else (r.attempts[-1].reason if r.attempts else "")
                log(f"  {mark:4} {p.name} [{g.label}] {detail}")
    return {"results": results, "no_candidates": no_candidates, "people": people}


# ---------- outputs ----------

def write_sources_yaml(summary: dict, path: Path) -> int:
    import yaml
    by_name = {p.name: p for p in summary["people"]}
    seen, rows = set(), []
    for r in summary["results"]:
        if not r.winner or r.winner.url in seen:
            continue
        seen.add(r.winner.url)
        p = by_name[r.group.person]
        row = {"person": p.name, "tier": p.tier, "flags": p.flags, "scrutiny": p.scrutiny,
               "kind": r.group.kind, "url": r.winner.url, "title": r.winner.title,
               "entries_seen": r.winner.entries, "latest_item": r.winner.latest}
        if r.group.kind == "pages":
            method, url = split_page_candidate(r.winner.url)
            row.update({"method": method, "url": url, **r.group.options})
        rows.append(row)
    header = ("# GENERATED by `python run.py --verify-sources`; re-running overwrites this file.\n"
              "# To add or fix a source, edit perspective.md or source_hints.yaml, then re-verify.\n")
    body = {"verified_at": dt.datetime.now().isoformat(timespec="seconds"), "sources": rows}
    path.write_text(header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True), "utf-8")
    return len(rows)


def write_report(summary: dict, path: Path) -> None:
    ok = [r for r in summary["results"] if r.winner]
    bad = [r for r in summary["results"] if not r.winner]
    L = [f"# Source verification — {dt.datetime.now():%Y-%m-%d %H:%M}", "",
         f"Verified: {len(ok)} · Failed: {len(bad)} · No candidates: {len(summary['no_candidates'])}", "",
         "## Verified", "", "| Person | Kind | Feed | Entries | Latest |", "|---|---|---|---|---|"]
    L += [f"| {r.group.person} | {r.group.kind} | {r.winner.url} | {r.winner.entries} | {r.winner.latest} |"
          for r in ok]
    L += ["", "## Failed (not wired in)", ""]
    for r in bad:
        L.append(f"- **{r.group.person}** [{r.group.label}]")
        L += [f"  - {a.url} → {a.reason}" for a in r.attempts]
    L += ["", "## No feed candidates (X / podcast only → Phase 3, or add a hint)", ""]
    L += [f"- **{p.name}** ({p.where})" for p in summary["no_candidates"]]
    path.write_text("\n".join(L) + "\n", "utf-8")
