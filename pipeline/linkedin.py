"""Steven's own LinkedIn posts, from LinkedIn's data export (and from Slack, when he shares one there).

LinkedIn can't be read directly (robots disallow it, the API is closed, automation risks the account),
so his history comes from the export he requests himself: Settings > Data privacy > Get a copy of your
data. The zip (or just Shares.csv from it) goes in data/inbox/ (gitignored), then:

    ./np linkedin import [PATH]     # PATH defaults to the newest zip / Shares.csv in data/inbox/
    ./np linkedin list [N]

What is read: Shares.csv (posts and reshares) and Articles/*.html (long-form articles). Nothing else in
the zip (messages, connections, contacts, ...) is opened.

Where it goes: data/public-record/linkedin-posts.jsonl, one line per post (date, link, text, the article
it shared, visibility). These are Steven's OWN words, so they are never briefed as news: they feed the
public record ("In my own words", ./np record words), public posts only. A post seen in Slack (its link
unfurls, so it is public) is stored here too and dropped from the briefing by rule.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

STORE = "data/public-record/linkedin-posts.jsonl"
INBOX = "data/inbox"
HOSTS = ("linkedin.com", "lnkd.in")


def lcfg(cfg: dict) -> dict:
    return {"names": ["Steven G. Woods", "Steven Woods"], "own_words_max": 40, "own_words_min_chars": 200,
            **(cfg.get("linkedin") or {})}


def _host(u: str) -> str:
    h = urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def is_linkedin(url: str) -> bool:
    h = _host(url)
    return any(h == x or h.endswith("." + x) for x in HOSTS)


def is_own_post(item: dict, cfg: dict) -> bool:
    """A LinkedIn link whose preview names Steven as the author ("... | Steven G. Woods")."""
    if not is_linkedin(item.get("url", "")):
        return False
    head = f"{item.get('title', '')} {(item.get('text') or '')[:400]}"
    return any(re.search(r"\|\s*" + re.escape(n) + r"\b", head) for n in lcfg(cfg)["names"])


def post_id(url: str, date: str = "", text: str = "") -> str:
    key = url or f"{date}|{text[:200]}"
    return hashlib.sha1(key.strip().lower().encode()).hexdigest()[:12]


def _public(vis: str) -> bool:
    v = (vis or "").upper()
    return "PUBLIC" in v or "ANYONE" in v


# ---------- store ----------

def load(root: Path) -> list:
    p = root / STORE
    if not p.exists():
        return []
    out = []
    for line in p.read_text("utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def add_posts(root: Path, posts: list) -> int:
    """Append posts not already stored (by id); a later copy with more text replaces nothing. -> added."""
    have = {p["id"] for p in load(root)}
    new, seen = [], set()
    for p in posts:
        if p["id"] in have or p["id"] in seen:
            continue
        seen.add(p["id"])
        new.append(p)
    if new:
        f = root / STORE
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            for p in new:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    return len(new)


def from_item(item: dict) -> dict:
    """A Slack-shared item that is Steven's own post -> a store record (public: its link unfurled)."""
    title = re.sub(r"\s*\|\s*[^|]+$", "", item.get("title", "")).strip()
    text = item.get("text", "")
    if title and text.startswith(item.get("title", "")):
        text = text[len(item.get("title", "")):].strip()
    return {"id": post_id(item["url"]), "date": (item.get("published") or "")[:10], "url": item["url"],
            "kind": "post", "text": text or title, "shared_url": "", "visibility": "PUBLIC (unfurled in Slack)",
            "origin": "slack", "imported_at": dt.datetime.now().isoformat(timespec="seconds")}


# ---------- export ----------

def _col(row: dict, *names) -> str:
    low = {k.strip().lower().replace(" ", ""): v for k, v in row.items() if k}
    for n in names:
        v = low.get(n.lower())
        if v:
            return v.strip()
    return ""


def parse_shares(text: str) -> list:
    now = dt.datetime.now().isoformat(timespec="seconds")
    out = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        url = _col(row, "ShareLink", "Link", "URL")
        body = _col(row, "ShareCommentary", "Commentary", "Text")
        date = _col(row, "Date")[:10]
        if not (url or body):
            continue
        out.append({"id": post_id(url, date, body), "date": date, "url": url, "kind": "post", "text": body,
                    "shared_url": _col(row, "SharedUrl", "SharedURL"), "visibility": _col(row, "Visibility"),
                    "origin": "export", "imported_at": now})
    return out


def parse_article(name: str, html: str) -> dict:
    from .textutil import html_to_text
    t = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", t.group(1)).strip() if t else Path(name).stem
    link = re.search(r'https://www\.linkedin\.com/pulse/[^"\'<>\s]+', html)
    date = re.search(r"(20\d\d-\d\d-\d\d)", html) or re.search(r"(20\d\d-\d\d-\d\d)", name)
    text = html_to_text(html)
    url = link.group(0) if link else ""
    return {"id": post_id(url, title, text), "date": date.group(1) if date else "", "url": url, "kind": "article",
            "title": title, "text": text[:20000], "shared_url": "", "visibility": "PUBLIC",
            "origin": "export", "imported_at": dt.datetime.now().isoformat(timespec="seconds")}


def read_export(path: Path) -> list:
    """Posts and articles from an export zip, or a bare Shares.csv. Opens nothing else in the zip."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return parse_shares(path.read_text("utf-8", errors="replace"))
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            base = n.rsplit("/", 1)[-1]
            if base.lower() == "shares.csv":
                out += parse_shares(z.read(n).decode("utf-8", errors="replace"))
            elif "/articles/" in ("/" + n.lower()) and base.lower().endswith(".html"):
                out.append(parse_article(base, z.read(n).decode("utf-8", errors="replace")))
    return out


def newest_in_inbox(root: Path) -> Path | None:
    d = root / INBOX
    if not d.exists():
        return None
    cands = [p for p in d.rglob("*") if p.is_file() and (p.suffix.lower() == ".zip" or p.name.lower() == "shares.csv")]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def import_export(root: Path, path: Path | None = None) -> dict:
    path = Path(path) if path else newest_in_inbox(root)
    if not path or not path.exists():
        raise FileNotFoundError(f"no LinkedIn export found: put the zip (or Shares.csv) in {INBOX}/")
    posts = read_export(path)
    added = add_posts(root, posts)
    dates = sorted(p["date"] for p in posts if p["date"])
    return {"file": str(path), "read": len(posts), "added": added,
            "posts": sum(1 for p in posts if p["kind"] == "post"),
            "articles": sum(1 for p in posts if p["kind"] == "article"),
            "public": sum(1 for p in posts if _public(p["visibility"])),
            "with_article": sum(1 for p in posts if p.get("shared_url")),
            "from": dates[0] if dates else "", "to": dates[-1] if dates else ""}


def domains(posts: list, n: int = 10) -> list:
    c = {}
    for p in posts:
        h = _host(p.get("shared_url", ""))
        if h:
            c[h] = c.get(h, 0) + 1
    return sorted(c.items(), key=lambda x: -x[1])[:n]


def own_words_sources(root: Path, cfg: dict) -> list:
    """Public posts with enough text, newest first, in the shape record.own_words reads (with text)."""
    c = lcfg(cfg)
    rows = [p for p in load(root) if _public(p["visibility"]) and p.get("url", "").startswith("http")
            and len(p.get("text", "")) >= c["own_words_min_chars"]]
    rows.sort(key=lambda p: p.get("date", ""), reverse=True)
    return [{"source_id": f"li-{p['id']}", "title": p.get("title") or ("LinkedIn post" if p["kind"] == "post" else "LinkedIn article"),
             "source_type": "appearance", "date": {"display": p.get("date", "")}, "urls": {"canonical": p["url"]},
             "text": p["text"][:3000]} for p in rows[:c["own_words_max"]]]
