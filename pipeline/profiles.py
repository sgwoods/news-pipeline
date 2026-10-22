"""Source profiles (source_profiles.yaml): weigh sources by how they know things, not by how many there are.

Only primary and reporting sources establish a fact (a company's own post is self-reported); analysis can test
a claim; opinion, aggregators and social posts never corroborate one. Code reads the file, never rewrites it.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

FILE = Path(__file__).resolve().parent.parent / "source_profiles.yaml"
KINDS = ("primary", "reporting", "analysis", "opinion", "aggregator", "social")
EVIDENCE = ("primary", "reporting", "tested")   # can establish a fact ("tested": analysis that ran it first-hand)
UNKNOWN = {"kind": "social", "standards": "none", "stance": "neutral"}
_GOV = __import__("re").compile(r"(\.gov|\.gc\.ca|\.gov\.uk|\.europa\.eu)$")
_OWN_SITE = __import__("re").compile(r"^(blog|news|newsroom|press|investors?|ir|about)\.[a-z0-9-]+\.[a-z.]+$")


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    import yaml
    try:
        d = yaml.safe_load(Path(path).read_text("utf-8")) or {}
    except (OSError, ValueError):
        d = {}
    return {"defaults": d.get("defaults") or {}, "outlets": {k.lower(): v for k, v in (d.get("outlets") or {}).items()},
            "sources": d.get("sources") or {}}


def table(path: Path = FILE) -> dict:
    if path == FILE and not path.is_file():           # public copy: the example profiles (pipeline/export.py)
        path = FILE.with_name("source_profiles.example.yaml")
    try:
        return _load(str(path), path.stat().st_mtime)
    except OSError:
        return {"defaults": {}, "outlets": {}, "sources": {}}


def host(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def outlet(url: str, t: dict | None = None) -> dict | None:
    t = t or table()
    h = host(url)
    seg = (urlparse(url or "").path.strip("/").split("/") or [""])[0].lower()
    if seg and f"{h}/{seg}" in t["outlets"]:               # a section with its own profile (huggingface.co/blog)
        return {**t["outlets"][f"{h}/{seg}"], "site": f"{h}/{seg}"}
    while h:
        if h in t["outlets"]:
            return {**t["outlets"][h], "site": h}
        h = h.split(".", 1)[1] if "." in h else ""
    return None


def cited_url(r: dict) -> str:
    link = r.get("linked_url") or ""
    if link.startswith("http") and "bsky.app" not in link:
        return link
    return r.get("url") or ""


def profile(r: dict, t: dict | None = None) -> dict:
    """The profile of the evidence behind one record: the cited site first, then the source, then defaults."""
    t = t or table()
    url = cited_url(r)
    o = outlet(url, t)
    if o and o.get("kind") != "social":
        return {**UNKNOWN, **o, "via": r.get("person", "")}
    if url and not o and _GOV.search(host(url)):
        return {"kind": "primary", "standards": "cites", "stance": "policy", "site": host(url), "note": "government"}
    if url and not o and _OWN_SITE.match(host(url)):          # blog./news./newsroom./investors. of a company
        return {"kind": "primary", "standards": "cites", "stance": "neutral", "site": host(url),
                "note": "the company's own site: self-reported"}
    if url and not o and "bsky.app" not in url and r.get("linked_url"):
        return {"kind": "unknown", "standards": "unknown", "stance": "neutral", "site": host(url)}
    name = r.get("person") or ""
    if o and o.get("kind") == "social":           # the post itself, whoever wrote it: never a test or a report
        base = {**UNKNOWN, **o, "via": name}
        if name in t["sources"]:
            src = t["sources"][name]
            base.update({k: src[k] for k in ("stance", "interests", "note") if src.get(k)})
        base["kind"] = "social"
        base.pop("tests", None)
        return base
    if name in t["sources"]:
        return {**UNKNOWN, **t["sources"][name], "name": name}
    if o:
        return {**UNKNOWN, **o}
    d = t["defaults"].get(r.get("source_kind") or "")
    return {**UNKNOWN, **d} if d else {"kind": "unknown", "standards": "unknown", "stance": "neutral"}


def evidence(records: list, t: dict | None = None) -> dict:
    """Counts for one story: independent primary sources and reports (one per site), and the rest."""
    t = t or table()
    prim, rep, tested, other, unknown, stances = set(), set(), set(), 0, 0, {}
    for r in records:
        p = profile(r, t)
        key = p.get("site") or p.get("name") or host(cited_url(r)) or r.get("person", "")
        if p["kind"] == "primary":
            prim.add(key)
        elif p["kind"] == "reporting":
            rep.add(key)
        elif p["kind"] == "analysis" and p.get("tests"):
            tested.add(key)
        else:
            other += 1
            unknown += p["kind"] == "unknown"
        if p.get("stance") and p["stance"] != "neutral":
            stances.setdefault(p["stance"], set()).add(p.get("name") or p.get("site") or r.get("person", ""))
    return {"primary": len(prim), "reports": len(rep), "tested": len(tested), "commentary": other,
            "grounded": bool(prim or rep or tested) or (bool(records) and unknown == len(records)),   # unprofiled: not blocked
            "unprofiled": unknown, "stances": {k: sorted(v) for k, v in stances.items()}}


def evidence_label(ev: dict) -> str:
    """'primary source + 2 reports + 3 commentaries' (for the byline)."""
    parts = []
    if ev["primary"]:
        parts.append("primary source" if ev["primary"] == 1 else f"{ev['primary']} primary sources")
    if ev["reports"]:
        parts.append(f"{ev['reports']} report" + ("s" if ev["reports"] > 1 else ""))
    if ev.get("tested"):
        parts.append(f"{ev['tested']} hands-on test" + ("s" if ev["tested"] > 1 else ""))
    if ev["commentary"]:
        parts.append(f"{ev['commentary']} commentar" + ("ies" if ev["commentary"] > 1 else "y"))
    return " + ".join(parts)


def unprofiled(root: Path, days: int = 14) -> dict:
    """Sources and sites seen recently that have no profile (counts), for Steven to add to the file."""
    import datetime as dt
    import json
    t = table()
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    people, sites = {}, {}
    for d in sorted((root / "data" / "raw").glob("????-??-??")):
        if d.name < cut:
            continue
        for ln in (d / "items.jsonl").read_text("utf-8").splitlines() if (d / "items.jsonl").exists() else []:
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            u = cited_url(r)
            from .links import SHORTENERS, is_tracker
            if u.startswith("http") and not outlet(u, t) and not _OWN_SITE.match(host(u)) \
                    and host(u) not in SHORTENERS and not is_tracker(u) and not _GOV.search(host(u)):
                sites[host(u)] = sites.get(host(u), 0) + 1
            o = outlet(r.get("url", ""), t)
            if r.get("person") and r["person"] not in t["sources"] and (not o or o.get("kind") == "social"):
                people[r["person"]] = people.get(r["person"], 0) + 1
    top = lambda d: sorted(d.items(), key=lambda x: -x[1])
    return {"sites": top(sites), "sources": top(people)}


def describe(r: dict, t: dict | None = None) -> str:
    """One line for a model prompt: what kind of evidence this source is."""
    p = profile(r, t)
    bits = [f"kind={p['kind']}", f"standards={p.get('standards', 'none')}", f"stance={p.get('stance', 'neutral')}"]
    if p.get("interests"):
        bits.append(f"interests={p['interests']}")
    if p.get("tests"):
        bits.append("tests=runs things first-hand: a hands-on test it shows is evidence of how a product behaves")
    if p.get("note"):
        bits.append(f"note={p['note']}")
    if p.get("site"):
        bits.insert(0, f"site={p['site']}")
    return "; ".join(bits)
