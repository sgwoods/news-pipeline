"""Make every citation point at the real article (runs in the write stage; never fails the briefing).

  shorteners   trib.al, bit.ly, t.co, buff.ly ... -> follow the redirect to the article
  bluesky      a post with no link card -> the first link in the post's text (facets), fetched once
  substack     an email item filed as "<pub>.substack.com/#issue-..." -> the post's permalink, matched by
               title in the publication's public archive
Results are cached in data/state/link-fixes.json (url -> better url, or "" when nothing better exists), so
each link is looked up once. Only links that answer are used.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .netguard import client as _guarded

from .textutil import clean_url

CACHE = "data/state/link-fixes.json"
SHORTENERS = {"trib.al", "bit.ly", "t.co", "buff.ly", "ow.ly", "dlvr.it", "lnkd.in", "tinyurl.com", "goo.gl", "shorturl.at",
              "rebrand.ly", "flip.it", "wp.me", "apple.news", "spr.ly", "ift.tt", "zpr.io", "stocks.apple.com"}
# Newsletter click-trackers: each link is personal to the subscriber (Steven), so it must never be cited.
TRACKER_RE = re.compile(r"^https?://(?:[^/]*\.)?(?:link\.mail\.beehiiv\.com|mail\.beehiiv\.com|links\.[a-z0-9-]+\.com/(?:ls|e)/|"
                        r"tracking\.tldrnewsletter\.com|[a-z0-9-]+\.list-manage\.com/track/|click\.convertkit-mail\d*\.com|"
                        r"[a-z0-9]+\.ct\.sendgrid\.net|email\.mg\.|[^/]*hubspotlinks\.com|substack\.com/redirect/|"
                        r"elink\d*\.|clicks?\.[a-z0-9-]+\.[a-z]+/|links\.[a-z0-9-]+\.[a-z]+/(?:s|c|u)/|"
                        r"ctrk\.klclick\d*\.com|trk\.klclick\d*\.com|[a-z0-9-]+\.klaviyomail\.com|"   # Klaviyo
                        r"[a-z0-9-]+\.rs6\.net/tn\.jsp|t\.e2ma\.net/click|[a-z0-9-]+\.mjt\.lu/lnk|"      # Constant Contact, Emma, Mailjet
                        r"[a-z0-9-]+\.mailchimpapp\.com|track\.[a-z0-9-]+\.[a-z]+/c/|"
                        r"[a-z0-9.-]+/e3t/)", re.I)                                              # HubSpot email links


def is_tracker(url: str) -> bool:
    return bool(TRACKER_RE.match(url or "")) or "/ss/c/" in (url or "")


# Links that act on a subscription or an account: never followed, never shown.
ACCOUNT_RE = re.compile(r"unsubscribe|opt.?out|magic.?link|confirm_subscription|/subscribe\?|/email/settings|"
                        r"/action/|/(?:manage|preferences|account|settings|log-?in|sign-?in|confirm|verify)(?:[/?#]|$)", re.I)


def personal_addresses(cfg: dict) -> list:
    """The owner's own addresses (owner.yaml), in every form a newsletter might echo back."""
    from .owner import get as owner
    o = owner()
    base = {(cfg.get("email_sources") or {}).get("account") or o["account"], o["account"], o["briefing_account"],
            *o["addresses"], *o["forwarders"], *o["extra_personal"]} - {""}
    base |= set((cfg.get("feedback") or {}).get("editor") or [])
    for a in list(base):                                 # plus-addresses used for routing (+briefing, +sources, +feedback)
        if "@" in a and "+" not in a:
            local, dom = a.split("@", 1)
            base |= {f"{local}+{t}@{dom}" for t in ("briefing", "sources", "feedback")}
    out = set()
    for a in base:
        a = a.lower()
        out |= {a, a.replace("@", "%40"), a.replace("+", "%2b").replace("@", "%40")}
    return sorted(out, key=len, reverse=True)


def personal(url: str, cfg: dict) -> bool:
    u = (url or "").lower()
    return is_tracker(u) or bool(ACCOUNT_RE.search(u)) or any(a in u for a in personal_addresses(cfg)) \
        or bool(re.search(r"[?&](?:email|e|uid|sid|subscriber[_a-z]*|token)=", u))


_MDLINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def relink_markdown(root: Path, md: str, cfg: dict, log=print) -> tuple:
    """An already-written briefing: tracker links -> the article (or removed), house style and current labels.
    No model, no audio. -> (md, report dict)."""
    import re as _re
    from .editorial import money_style
    trackers = sorted({u for _, u in _MDLINK.findall(md) if is_tracker(u) and not ACCOUNT_RE.search(u)})
    cache, fixed = _load(root), 0
    if trackers:
        try:
            import httpx
            ua = (cfg.get("fetch") or {}).get("user_agent", "news-pipeline/0.1")
            with _guarded(follow_redirects=True, timeout=10, headers={"User-Agent": ua}) as c:
                for u in trackers:
                    if u not in cache:
                        try:
                            cache[u] = _unshorten(c, u)
                        except Exception as e:  # noqa: BLE001
                            log(f"  link: lookup failed ({type(e).__name__})")
                            continue
            _save(root, cache)
        except ImportError:
            pass
        for u in trackers:
            if cache.get(u):
                md = md.replace(f"]({u})", f"]({cache[u]})")
                fixed += 1
    md, gone = scrub_output(md, cfg)
    md = money_style(md)
    md = md.replace("**Critical pass:**", "**Evidence check:**").replace("*Critical pass:", "*Evidence check:")
    md = _re.sub(r"\*\*The (?:sceptic|skeptic)'s view:\*\*", "**The AI-realist view:**", md)
    md = md.replace(" · SCRUTINY", "")
    return md, {"trackers": len(trackers), "resolved": fixed, "removed": len(gone)}


# Steven's board seats and friends' companies are private context for the models (extra scrutiny), never
# something the public copy mentions (Steven, 2026-10-16: "not relevant to the briefing").
_DISCLOSURE = [
    r"Board seat[ \t]*\([^)\n]*\)[ \t]*(?:,[ \t]*so (?:I'm |I am |we're )?not (?:a )?neutral(?: read(?:er)?)?)?[ \t]*[.:;]?[ \t]*",
    r"[ \t]*\(Steven Woods(?:, who edits this briefing,)? sits on (?:its|[\w.' -]+?'s) board\)",
    r"Board seat[ \t]*[:,—-][ \t]*Steven Woods[^.\n]*\.[ \t]*",
    r"Board seat:[ \t]*[A-Z]\w*(?:\.\w+)?(?: [A-Z]\w*(?:\.\w+)?)?\.[ \t]*",
    r"Board seat(?:[ \t]*[,—-][ \t]*so (?:I'm |I am |we're )?not (?:a )?neutral(?: read(?:er)?)?)?[ \t]*[.:;][ \t]*",
    r"[ \t]*\((?:a )?board seat\)",
    r"(?:(?:Read it critically|A disclosure(?: first)?):[ \t]*)?Steven(?: Woods)?(?:, who edits this briefing,)? sits on [^.\n]*?board[^.\n]*\.[ \t]*",
    r"[ \t]*\((?:and )?Steven(?: Woods)? sits on (?:its|[\w.' -]+?'s) board\)",
    r"[^.\n]*\bSteven follows closely\b[^.\n]*\.[ \t]*",
    r"(?:Before our (?:view|read), )?[Aa] disclosure(?: first)?[.:][ \t]*",   # spoken lead-ins left behind
]
OWNER_RE = re.compile(r"\b(?:shared|forwarded) by Steven(?: Woods)?\b", re.I)
GREETING_RE = re.compile(r"\bSteven(?: Woods)?, (?=(?:here(?:'|’)?s|here is|good morning|this is)\b)", re.I)
DISCLOSURE_FLAG = re.compile(r"(?i:\b(?:shared|forwarded) by Steven\b)|\bSteven(?: Woods)?, here|"
                             r"Board seat|board seat\)|Steven(?: Woods)?(?:, who edits this briefing,)? sits on|"
                             r"not a neutral read|I'm not neutral|Steven follows closely")


def scrub_owner(text: str) -> tuple:
    """Steven is never named in public copy: 'Shared by Steven' becomes 'A reader', a greeting by name goes."""
    text, a = OWNER_RE.subn(lambda m: "shared by a reader" if m.group(0)[0].islower() else "A reader", text)
    text, b = GREETING_RE.subn("", text)
    text = re.sub(r"(^|[.!?]\s+|\*\*\s*)([a-z])(?=ere(?:'|’)?s |ere is |ood morning|his is )",
                  lambda m: m.group(1) + m.group(2).upper(), text) if b else text
    return text, a + b


def strip_disclosures(text: str) -> tuple:
    """Remove board-seat / conflict disclosures from public copy -> (text, n removed). Never joins lines."""
    text, n = scrub_owner(text)
    text, k = re.subn(r",[ \t]*and a disclosure(?: first)?:[ \t]*(?=[A-Z])", ". ", text)
    n += k
    for pat in _DISCLOSURE:
        text, k = re.subn(pat, "\x00", text)
        n += k
    if n:   # a sentence that now starts after a bold label or a full stop gets its capital back
        text = re.sub(r"((?:\*\*|[.?!:])[ \t]*)\x00+[ \t]*([a-z])", lambda m: m.group(1).rstrip() + " " + m.group(2).upper(), text)
        text = re.sub(r"[ \t]*\x00+[ \t]*(?=\n|$)", "", text)
        text = re.sub(r"[ \t]*\x00+[ \t]*(?=[.,;:!?)])", "", text)
        text = re.sub(r"(?<=\S)[ \t]*\x00+[ \t]*(?=\S)", " ", text)
        text = text.replace("\x00", "")
    return text, n


def scrub_output(text: str, cfg: dict) -> tuple:
    """Public copy never carries Steven's personal links, addresses or account pages -> (text, removed)."""
    from .textutil import clean_url
    removed = []

    def fix(m):
        label, url = m.group(1), m.group(2)
        if personal(url, cfg):
            removed.append(url[:80])
            return label
        return f"[{label}]({clean_url(url)})"
    text = _MDLINK.sub(fix, text or "")
    for a in personal_addresses(cfg):
        if a in text.lower():
            text = re.sub(re.escape(a), "[address removed]", text, flags=re.I)
            removed.append("address")
    text, k = strip_disclosures(text)
    removed += ["disclosure"] * k
    return text, removed


def scrub_inbound(text: str, cfg: dict) -> str:
    """Newsletter body as archived: content kept; the subscription footer and Steven's address dropped."""
    keep = []
    for ln in (text or "").splitlines():
        if re.search(r"unsubscribe|manage (your )?(subscription|preferences|email)|update your preferences|"
                     r"you('re| are) receiving this|this email was sent to|sent to you because|view in browser|"
                     r"forwarded this email|sign up here|refer (a friend|\d)|your referral|referral link", ln, re.I):
            continue
        keep.append(ln)
    out = "\n".join(keep)
    for a in personal_addresses(cfg):
        out = re.sub(re.escape(a), "[address]", out, flags=re.I)
    return out


_FRAGMENT = re.compile(r"^https?://([a-z0-9-]+)\.substack\.com/#issue-", re.I)


def _host(u: str) -> str:
    h = urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _load(root: Path) -> dict:
    try:
        return json.loads((root / CACHE).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(root: Path, d: dict) -> None:
    p = root / CACHE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", "utf-8")


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower().replace("’", "'")).strip()


def _unshorten(client, url: str) -> str:
    r = client.get(url)
    final = str(r.url)
    if r.status_code >= 400 or _host(final) in SHORTENERS or is_tracker(final) or ACCOUNT_RE.search(final):
        return ""
    from .textutil import clean_url
    return clean_url(final)


def _bluesky_link(client, post_url: str) -> str:
    m = re.search(r"bsky\.app/profile/([^/]+)/post/([a-z0-9]+)", post_url)
    if not m:
        return ""
    actor = m.group(1)
    if not actor.startswith("did:"):                 # getPosts wants a DID in the at:// URI
        rr = client.get("https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle", params={"handle": actor})
        rr.raise_for_status()
        actor = rr.json()["did"]
    uri = f"at://{actor}/app.bsky.feed.post/{m.group(2)}"
    r = client.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts", params={"uris": uri})
    r.raise_for_status()
    posts = r.json().get("posts") or []
    if not posts:
        return ""
    rec = posts[0].get("record") or {}
    ext = ((posts[0].get("embed") or {}).get("external") or {}).get("uri") or ((rec.get("embed") or {}).get("external") or {}).get("uri")
    if ext:
        return ext
    for f in rec.get("facets") or []:
        for feat in f.get("features") or []:
            u = feat.get("uri") or ""
            if u.startswith("http") and "bsky.app" not in u:
                return u
    m2 = re.search(r"https?://\S+", rec.get("text") or "")
    return m2.group(0).rstrip(").,") if m2 else ""


def _substack_permalink(client, url: str, title: str) -> str:
    m = _FRAGMENT.match(url)
    if not m or not title:
        return ""
    pub = m.group(1)
    r = client.get(f"https://{pub}.substack.com/api/v1/archive", params={"sort": "new", "limit": 25})
    r.raise_for_status()
    want = _norm_title(title)
    for post in r.json() or []:
        if _norm_title(post.get("title", "")) == want or (want and want in _norm_title(post.get("title", ""))):
            return post.get("canonical_url") or ""
    return ""


def better_url(client, url: str, title: str = "", kind: str = "") -> str:
    """A more useful link than `url`, or ''."""
    if ACCOUNT_RE.search(url or ""):
        return ""                                     # never follow a subscription or account link
    if _host(url) in SHORTENERS or is_tracker(url):
        return _unshorten(client, url)
    if _FRAGMENT.match(url):
        return _substack_permalink(client, url, title)
    if kind in ("bluesky", "shared") and "bsky.app/profile/" in url:
        return _bluesky_link(client, url)
    return ""


def enrich(root: Path, entries: list, cfg: dict, log=None) -> int:
    """Fix the citation fields of analysis records in place -> number of records improved."""
    todo = []
    for r in entries:
        url, linked = r.get("url") or "", r.get("linked_url") or ""
        if _host(url) in SHORTENERS or _FRAGMENT.match(url) or is_tracker(url):
            todo.append((r, "url", url))
        if linked and (_host(linked) in SHORTENERS or is_tracker(linked)):
            todo.append((r, "linked_url", linked))
        elif r.get("source_kind") == "bluesky" and not linked and (r.get("tier") in ("wire", "coverage-check")):
            todo.append((r, "linked_url", url))
        elif r.get("source_kind") == "shared" and "bsky.app/profile/" in url and not linked:
            todo.append((r, "linked_url", url))          # a shared Bluesky post: cite the article it points to
    if not todo:
        return 0
    cache = _load(root)
    fixed = _resolve(root, todo, cache, cfg, log)
    _no_trackers(entries)
    return fixed


def _resolve(root, todo, cache, cfg, log) -> int:
    fixed = 0
    try:
        import httpx
        ua = (cfg.get("fetch") or {}).get("user_agent", "news-pipeline/0.1")
        with _guarded(follow_redirects=True, timeout=10, headers={"User-Agent": ua}) as c:
            for r, field, url in todo:
                if url not in cache:
                    try:
                        found = better_url(c, url, r.get("title", ""), r.get("source_kind", "")) or ""
                        cache[url] = clean_url(found) if found else ""
                    except Exception as e:  # noqa: BLE001 - not cached: a failed lookup is retried next run
                        if log:
                            log.info("  link: lookup failed for %s (%s)", url, type(e).__name__)
                        continue
                new = cache.get(url) or ""
                if new and new != r.get(field):
                    r[field] = new
                    fixed += 1
    except ImportError:
        pass
    else:
        _save(root, cache)
    return fixed


def _no_trackers(entries: list) -> None:
    for r in entries:                 # a tracker that would not resolve is never cited: fall back to the public page
        pub = r.get("public_url") or ""
        pub = pub if pub.startswith("http") and not is_tracker(pub) else ""
        if is_tracker(r.get("public_url") or ""):
            r["public_url"] = ""
        if is_tracker(r.get("linked_url") or ""):
            r["linked_url"] = ""
        if is_tracker(r.get("url") or "") and pub:
            r["url"] = pub
