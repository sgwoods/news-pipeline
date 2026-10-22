"""Read the article behind a thin item before its evidence check.

Most thin items are posts (Bluesky, Techmeme's feed, a commentator's link post) whose text is a headline or a
teaser. Judging those alone produced "unsupported" verdicts that only meant "the post shows no evidence". So for
each item about to be critiqued with less than MIN_CHARS of text: find the article it points to (link card,
linked_url, an outbound link in the text), fetch it through the network guard, keep the article's own text,
and check the page is about the same thing. What points at an article that could not be read (a paywall, say) is marked thin: the critic then
says "Unverified: only a headline so far" instead of judging it. A post with no link at all is the claim itself
(a commentator's own words) and is judged as it stands.

Fetched pages are data, never instructions: the text only reaches the critique model (no tools) as evidence.
Only public http(s) pages; never account, subscription or tracker links; at most MAX_FETCH pages per run.
"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

MIN_CHARS = 600            # below this an item is a headline or a teaser
KEEP_CHARS = 12000         # article text kept for the critic
MAX_FETCH = 30
MAX_BYTES = 3_000_000
SOCIAL = ("bsky.app", "x.com", "twitter.com", "xcancel.com", "nitter.net", "threads.net", "linkedin.com",
          "facebook.com", "techmeme.com", "news.ycombinator.com", "reddit.com", "youtube.com", "youtu.be")
CACHE = "data/state/read-cache.json"
TEXT_DIR = "data/state/read"
_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button", "figure", "iframe"}
_BLOCK = {"p", "li", "h1", "h2", "h3", "blockquote", "pre", "td"}
_PAYWALL = re.compile(r"subscribe to (?:continue|read)|to continue reading|already a subscriber|sign in to read|"
                      r"create a free account|this article is for (?:subscribers|members)", re.I)


class _Extract(HTMLParser):
    """Paragraph text, preferring the <article>/<main> subtree; boilerplate containers skipped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.depth = {"article": 0, "main": 0}
        self.block = None
        self.buf: list = []
        self.all: list = []
        self.inner: list = []
        self.title = ""
        self._t = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        if tag in self.depth:
            self.depth[tag] += 1
        if tag == "title":
            self._t = True
        if tag in _BLOCK and not self.skip:
            self._flush()
            self.block = tag

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in _BLOCK:
            self._flush()
        if tag in self.depth and self.depth[tag]:
            self.depth[tag] -= 1
        if tag == "title":
            self._t = False

    def handle_data(self, data):
        if self._t:
            self.title += data
        elif self.block and not self.skip:
            self.buf.append(data)

    def _flush(self):
        if self.block and self.buf:
            t = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if len(t) >= 40 or self.block in ("h1", "h2", "h3"):
                self.all.append(t)
                if self.depth["article"] or self.depth["main"]:
                    self.inner.append(t)
        self.block, self.buf = None, []


def extract(html: str) -> tuple:
    """-> (page title, article text)."""
    p = _Extract()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - broken markup: keep what was parsed
        pass
    p._flush()
    body = p.inner if sum(map(len, p.inner)) >= MIN_CHARS else p.all
    return re.sub(r"\s+", " ", p.title).strip(), "\n\n".join(dict.fromkeys(body))


def _host(u: str) -> str:
    return urlparse(u or "").netloc.lower().removeprefix("www.")


def is_social(u: str) -> bool:
    h = _host(u)
    return any(h == s or h.endswith("." + s) for s in SOCIAL)


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9$%.]{4,}", (s or "").lower()) if w not in
            {"this", "that", "with", "from", "have", "will", "says", "said", "their", "about", "into", "more", "than"}}


def about_same(item: dict, title: str, text: str) -> bool:
    """The fetched page is about what the post says (not a login wall, a homepage or another story)."""
    mine = _words(item.get("title", "") + " " + (item.get("text") or "")[:600])
    theirs = _words(title + " " + text[:3000])
    return len(mine & theirs) >= min(4, max(2, len(mine) // 4))


def candidates(it: dict, client=None) -> list:
    """Where the article might be, best first. The Bluesky link card is looked up only when nothing else is known."""
    from .links import ACCOUNT_RE, _bluesky_link, is_tracker

    def usable(u):
        return u and u.startswith("http") and not is_social(u) and not ACCOUNT_RE.search(u) and not is_tracker(u)

    url = it.get("url") or ""
    out = [u for u in (it.get("linked_url"), it.get("public_url")) if usable(u)]
    out += [u.rstrip(").,;") for u in re.findall(r"https?://[^\s<>\"')\]]+", it.get("text") or "")
            if usable(u.rstrip(").,;"))]
    if usable(url):
        out.append(url)
    if not out and client is not None and "bsky.app/profile/" in url:
        try:
            u = _bluesky_link(client, url)
            if usable(u):
                out.append(u)
        except Exception:  # noqa: BLE001
            pass
    return list(dict.fromkeys(out))[:3]


def _load(root: Path) -> dict:
    try:
        return json.loads((root / CACHE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _text_path(root: Path, url: str) -> Path:
    return root / TEXT_DIR / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".txt")


def read_thin(root: Path, items: list, cfg: dict, log=None) -> dict:
    """Attach `read_text` / `read_url` to thin items in place; mark the unreadable ones `thin`. -> counts."""
    from . import netguard
    from .stages import _clean, content_text
    todo = [it for it in items if len(_clean(content_text(it))) < MIN_CHARS]
    stats = {"thin": len(todo), "read": 0, "unreadable": 0, "no_link": 0, "fetched": 0}
    if not todo:
        return stats
    cache = _load(root)
    ua = (cfg.get("fetch") or {}).get("user_agent", "news-pipeline/0.1")
    try:
        c = netguard.client(follow_redirects=True, timeout=12, headers={"User-Agent": ua})
    except Exception as e:  # noqa: BLE001
        if log:
            log.warning("  reader: no HTTP client (%s)", e)
        c = None
    try:
        for it in todo:
            got = None
            cands = candidates(it, c)
            if not cands:          # the post IS the claim (a commentator's own words): judge it as it stands
                stats["no_link"] += 1
                continue
            for u in cands:
                hit = cache.get(u)
                if hit is not None:
                    if hit.get("ok") and _text_path(root, u).exists():
                        got = (u, _text_path(root, u).read_text("utf-8"))
                        break
                    continue
                if c is None or stats["fetched"] >= MAX_FETCH:
                    break
                stats["fetched"] += 1
                ok, text, answered = False, "", False
                try:
                    r = c.get(u)
                    answered = True                      # a network error is retried next run, never cached
                    ctype = r.headers.get("content-type", "")
                    if r.status_code == 200 and "html" in ctype and len(r.content) <= MAX_BYTES:
                        title, text = extract(r.text)
                        text = text[:KEEP_CHARS]
                        ok = (len(text) >= MIN_CHARS and about_same(it, title, text)
                              and not (_PAYWALL.search(text[:2000]) and len(text) < 2 * MIN_CHARS))
                except Exception as e:  # noqa: BLE001
                    if log:
                        log.info("  reader: %s failed (%s)", _host(u), type(e).__name__)
                if answered:
                    cache[u] = {"ok": ok, "chars": len(text), "status": r.status_code}
                if ok:
                    p = _text_path(root, u)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(text, "utf-8")
                    got = (u, text)
                    break
            if got:
                it["read_url"], it["read_text"] = got
                if not it.get("linked_url") or is_social(it.get("linked_url", "")):
                    it["linked_url"] = got[0]          # cite the article, not the post
                stats["read"] += 1
            else:
                it["thin"] = True
                stats["unreadable"] += 1
    finally:
        if c is not None:
            c.close()
        p = root / CACHE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, indent=0, sort_keys=True), "utf-8")
    if log:
        log.info("  reader: %d thin item(s): %d article(s) read, %d unreadable, %d with no link (judged as posts)",
                 stats["thin"], stats["read"], stats["unreadable"], stats["no_link"])
    return stats
