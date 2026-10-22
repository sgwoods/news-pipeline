"""Look for a figure before the fact check cuts it (Steven, 2026-10-18: "before you redact a number you cannot
trace to source, try to find it online ... to create a URL reference").

Order: (1) the story's own linked articles that the reader has not already read, (2) a web search (Bing's public
RSS endpoints: free, no key, no account). A page counts only if the figure appears within NEAR characters of the
sentence's main name, so a stray "$3.5 trillion" elsewhere on the page does not rescue a claim.

Found -> the sentence stays and gets a link to the page (web finds only; the story's own articles are already its
sources). Every request goes to logs/news-search.jsonl. Fetched pages are data: they are only matched for numbers and
names here, never given to a model. All fetches go through netguard (public hosts only).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import factcheck

BING_NEWS = "https://www.bing.com/news/search?q={q}&format=rss&mkt=en-US"
BING_WEB = "https://www.bing.com/search?q={q}&format=rss&mkt=en-US"
MAX_FIGS = 8          # figures searched per edition
MAX_PAGES = 3         # result pages fetched per search
NEAR = 600            # characters between the figure and the main name
BLOCK = ("wikipedia.org", "reddit.com", "youtube.com", "news.google.com", "bing.com", "msn.com")
_SKIP = {"The", "A", "An", "And", "But", "Or", "In", "On", "At", "For", "Of", "To", "By", "With", "From", "As",
         "It", "Its", "This", "That", "These", "Those", "Their", "Our", "We", "They", "He", "She", "If", "When",
         "While", "After", "Before", "Up", "Down", "About", "Over", "Under", "Per", "Why", "What", "How", "Who",
         "Details", "Source", "Sources", "Read", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "US", "U.S.", "AI", "CEO"}
_MONTHS = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", re.I)


def entities(sentence: str, raw: str = "") -> list:
    """Capitalised names in a sentence ("Microsoft Copilot", "OpenAI"), nearest to the figure first."""
    out = []
    at = sentence.find(raw) if raw else -1
    for m in re.finditer(r"\b([A-Z][\w&.'-]*[\w]|[A-Z]{2,}\w*)(?:\s+([A-Z][\w&.'-]*[\w]))*", sentence):
        words = [re.sub(r"['’]s$", "", w) for w in m.group(0).split() if w not in _SKIP and not _MONTHS.match(w)]
        if words:
            out.append((abs(m.start() - at) if at >= 0 else m.start(), " ".join(words)))
    out = [e for _d, e in sorted(out, key=lambda x: x[0])]
    seen, res = set(), []
    for e in out:
        if e.lower() not in seen and len(e) > 1:
            seen.add(e.lower())
            res.append(e)
    return res[:4]


def query(sentence: str, raw: str) -> str:
    ents = entities(sentence, raw)
    m = re.match(r"~?[$€£]?([\d.,]+)\s?([A-Za-z%]*)", raw.strip())
    num = m.group(1) if m else raw
    unit = {"t": "trillion", "tn": "trillion", "b": "billion", "bn": "billion", "m": "million", "mn": "million",
            "k": "thousand", "%": "percent"}.get((m.group(2) if m else "").lower(), m.group(2) if m else "")
    return " ".join([f'"{e}"' for e in ents[:2]] + [num, unit]).strip()


def real_url(link: str) -> str:
    """Bing wraps news results in an apiclick redirect that carries the article URL as a parameter."""
    u = urlparse(link)
    if u.netloc.endswith("bing.com"):
        q = parse_qs(u.query)
        for k in ("url", "u"):
            if q.get(k):
                return unquote(q[k][0])
    return link


def parse_rss(text: str) -> list:
    try:
        root = ET.fromstring(text.encode() if isinstance(text, str) else text)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        link = real_url((it.findtext("link") or "").strip())
        if link.startswith("http"):
            out.append({"title": (it.findtext("title") or "").strip(), "url": link})
    return out


def supports(text: str, v: float, kind: str, base, ents: list) -> bool:
    """The figure appears near the main name on this page."""
    if not ents or not text:
        return False
    lo = text.lower()
    wins, start = [], 0
    key = ents[0].lower()
    while len(wins) < 20:
        p = lo.find(key, start)
        if p < 0:
            break
        wins.append(text[max(0, p - NEAR): p + len(key) + NEAR])
        start = p + 1
    if not wins:
        return False
    pool = factcheck.corpus_values(wins)
    return factcheck.traced(v, kind, pool, None, base)


class Finder:
    """find(raw, v, kind, base, sentence) -> {"url", "outlet", "how"} or None. Budgeted per edition."""

    def __init__(self, client, own_urls=(), log=None, max_figs: int = MAX_FIGS):
        self.c, self.own, self.log, self.left = client, list(dict.fromkeys(own_urls)), log, max_figs
        self.pages: dict = {}           # url -> text ("" = unreadable)
        self.requests = 0

    def _get(self, url: str):
        from .watchlist import _logreq
        self.requests += 1
        try:
            r = self.c.get(url)
        except Exception as e:  # noqa: BLE001
            _logreq("factsearch", url, None, str(e))
            return None
        _logreq("factsearch", url, r)
        return r

    def _page(self, url: str) -> str:
        if url in self.pages:
            return self.pages[url]
        from . import reader
        text = ""
        host = urlparse(url).netloc.lower()
        if not reader.is_social(url) and not any(host == b or host.endswith("." + b) for b in BLOCK):
            r = self._get(url)
            if r is not None and r.status_code == 200 and "html" in r.headers.get("content-type", "") \
                    and len(r.content) <= reader.MAX_BYTES:
                _t, text = reader.extract(r.text)
                if reader._PAYWALL.search(text[:2000]) and len(text) < 2 * reader.MIN_CHARS:
                    text = ""
        self.pages[url] = text
        return text

    def __call__(self, raw: str, v: float, kind: str, base, sentence: str):
        if self.left <= 0 or self.c is None:
            return None
        self.left -= 1
        ents = entities(sentence, raw)
        if not ents:
            return None
        for u in self.own:                                  # 1. the story's own articles
            if supports(self._page(u), v, kind, base, ents):
                return {"url": u, "outlet": _outlet(u), "how": "story"}
        q = query(sentence, raw)                            # 2. the open web
        for tmpl in (BING_NEWS, BING_WEB):
            r = self._get(tmpl.format(q=quote(q)))
            if r is None or r.status_code != 200:
                continue
            for hit in parse_rss(r.text)[:MAX_PAGES]:
                if supports(self._page(hit["url"]), v, kind, base, ents):
                    from .textutil import clean_url
                    u = clean_url(hit["url"])
                    return {"url": u, "outlet": _outlet(u), "how": "web", "query": q}
        return None


def _outlet(u: str) -> str:
    try:
        from .stages import outlet_name
        return outlet_name(u)
    except Exception:  # noqa: BLE001
        return urlparse(u).netloc.removeprefix("www.")
