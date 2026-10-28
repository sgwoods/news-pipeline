"""HTML → text, page metadata, URL ids, and date parsing. Stdlib only (Python 3.9+)."""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html as htmllib
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

UTC = dt.timezone.utc

_SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "iframe", "button"}
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr",
          "section", "article", "blockquote", "pre", "figure", "figcaption", "table"}
_TRACKING = re.compile(r"^(utm_|ref$|ref_|source$|mc_|fbclid|gclid|s$|r$|_bhlid$|_hsenc$|_hsmi$|mkt_tok$|vero_|ck_subscriber|"
                       r"subscriber|sid$|uid$|email$|e$|token|oly_|rb_clickid$|__s$|lctg$|isFreemail$|post_id$|publication_id$|triedRedirect$|"
                       # gift / share links identify the subscriber who shared them (NYT, WSJ, FT, Bloomberg, ...)
                       r"unlocked_article_code$|smid$|smtyp$|gift|share_?id$|shareToken$|sharing|accessToken$|giftCopy|"
                       r"user_?id$|segment_id$|campaign_id$|mbid$|cmpid$)", re.I)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    p = _Text()
    p.feed(html)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in "".join(p.parts).splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def normalize_url(url: str) -> str:
    u = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(u.query) if not _TRACKING.match(k)]
    host = u.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = u.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", urlencode(q), ""))


def clean_url(url: str) -> str:
    """Drop tracking params and fragment, keep everything else as published."""
    u = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(u.query) if not _TRACKING.match(k)]
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), ""))


def item_id(url: str) -> str:
    """Stable id for an item: hash of its normalized URL."""
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:16]


def parse_date(s) -> dt.datetime | None:
    """ISO-8601, RFC-822 or a time.struct_time → aware UTC datetime, else None."""
    if s is None or s == "":
        return None
    if hasattr(s, "tm_year"):
        return dt.datetime(*s[:6], tzinfo=UTC)
    s = str(s).strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
        if d is not None:
            return (d if d.tzinfo else d.replace(tzinfo=UTC)).astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        pass
    iso = s.replace("Z", "+00:00")
    iso = re.sub(r"(\.\d{6})\d+", r"\1", iso)          # trim sub-microsecond digits
    iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso)  # +0000 -> +00:00
    for cand in (iso, iso[:19], iso[:10]):
        try:
            d = dt.datetime.fromisoformat(cand)
            return (d if d.tzinfo else d.replace(tzinfo=UTC)).astimezone(UTC)
        except ValueError:
            continue
    return None


def iso(d: dt.datetime | None) -> str:
    return d.astimezone(UTC).isoformat(timespec="seconds") if d else ""


def _metas(html: str) -> dict:
    out = {}
    for tag in META_RE.findall(html):
        a = {k.lower(): v for k, v in ATTR_RE.findall(tag)}
        key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        if key and "content" in a and key not in out:
            out[key] = htmllib.unescape(a["content"]).strip()
    return out


def extract_page(html: str, max_chars: int = 30000) -> dict:
    """Title, description, published date and main text from an article page."""
    m = _metas(html)
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = m.get("og:title") or (htmllib.unescape(t.group(1)).strip() if t else "")
    published = (m.get("article:published_time") or m.get("og:published_time")
                 or m.get("datepublished") or m.get("date") or "")
    if not published:
        j = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        tm = re.search(r'<time[^>]*datetime=["\']([^"\']+)', html, re.I)
        published = j.group(1) if j else (tm.group(1) if tm else "")
    body_html = html
    for tag in ("article", "main"):
        blocks = re.findall(rf"<{tag}\b.*?</{tag}>", html, re.I | re.S)
        if blocks:
            body_html = max(blocks, key=len)
            break
    text = html_to_text(body_html)[:max_chars]
    return {"title": title, "description": m.get("og:description") or m.get("description", ""),
            "published": published, "author": m.get("author") or m.get("article:author", ""),
            "text": text}


# ---------- the merged top (critic 2026-10-24, #7A; v0.2.22) ----------
# With briefing.top_format "merged" the edition opens with one 5-bullet "Today in 30 seconds" section and the
# diligence question under it, instead of the day in brief paragraph plus Top of mind. Readers of the markdown
# (audio, email, takes, reports) see it in the classic shape through legacy_top(), so each needs no second parser.
TOP_MERGED = "Today in 30 seconds"
QUESTION_LEAD = "**A question worth asking in diligence this week:**"


def is_merged(md: str) -> bool:
    return f"\n## {TOP_MERGED}\n" in f"\n{md}"


def legacy_top(md: str) -> str:
    """A merged-top edition in the classic shape: the question becomes the day in brief, the section Top of mind."""
    if not is_merged(md):
        return md
    lines = md.split("\n")
    q = next((i for i, x in enumerate(lines) if x.startswith(QUESTION_LEAD)), -1)
    question = lines.pop(q)[len(QUESTION_LEAD):].strip() if q >= 0 else ""
    h = next(i for i, x in enumerate(lines) if x.strip() == f"## {TOP_MERGED}")
    lines[h] = "## Top of mind"
    if question:
        lines[h:h] = [f"**The day in brief.** A question worth asking in diligence this week: {question}", ""]
    return "\n".join(lines)
