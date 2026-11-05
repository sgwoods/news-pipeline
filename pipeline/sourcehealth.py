"""Source health (Steven, 2026-11-05): every source we know about in one table, with a status and an error category,
so the ones that don't reach the archive can be fixed in priority order.

Status
    failing                the last fetch of it returned an error
    known, not ingested    configured (or a site our deep dives keep citing) but nothing of it is in the archive
    quiet                  it worked before, but nothing new for QUIET_DAYS (newsletters: NEWSLETTER_QUIET_DAYS)
    ingesting              items arriving

Category: where it comes from (X, Bluesky, Email newsletter, RSS feed, Web page, Slack) and, when it fails, why
(HTTP 403 blocked, HTTP 404 moved, rate limited, server error, timeout, unreadable feed, no X mirror answered,
never arrived, bot wall / paywall).

Priority: failing before not-ingested before quiet; then sources marked "follow closely"; then the size of the gap
(how many items or citations it would add). Read-only: nothing here fetches anything.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from urllib.parse import urlsplit

QUIET_DAYS = 21
NEWSLETTER_QUIET_DAYS = 14
STATUS_ORDER = {"failing": 0, "known, not ingested": 1, "quiet": 2, "ingesting": 3}
KIND_LABEL = {"x": "X", "bluesky": "Bluesky", "email": "Email newsletter", "rss": "RSS feed", "feed": "RSS feed",
              "atom": "RSS feed", "page": "Web page", "pages": "Web page", "sitemap": "Web page", "shared": "Slack",
              "slack": "Slack", "podcast": "Podcast", "youtube": "YouTube", "link": "Deep-dive citation"}


def kind_of(kind: str, url: str) -> str:
    k = (kind or "").lower()
    if k in KIND_LABEL:
        return KIND_LABEL[k]
    u = (url or "").lower()
    if "bsky.app" in u or u.startswith("at://"):
        return "Bluesky"
    if "x.com/" in u or "twitter.com/" in u or "nitter" in u or "xcancel" in u:
        return "X"
    if u == "slack":
        return "Slack"
    if re.search(r"(rss|feed|atom)(\.xml)?\b|\.xml$", u):
        return "RSS feed"
    return KIND_LABEL.get(k, (kind or "Web page").replace("_", " ").capitalize())


def reason(err: str) -> str:
    e = (err or "").lower()
    if not e:
        return ""
    if "mirror" in e:
        return "no X mirror answered"
    if re.search(r"\b403\b|forbidden", e):
        return "HTTP 403 blocked"
    if re.search(r"\b(404|410)\b|not found", e):
        return "HTTP 404 moved or gone"
    if re.search(r"\b429\b|rate limit|limit requests", e):
        return "rate limited"
    if re.search(r"\b5\d\d\b", e):
        return "server error"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if "unparseable" in e or "bozo" in e or "xml" in e:
        return "unreadable feed"
    if "nodename" in e or "connecterror" in e or "name or service" in e:
        return "offline / DNS"
    if "token" in e or "auth" in e or "401" in e:
        return "sign-in or token"
    return "other error"


def _days_since(day: str, today: dt.date) -> int | None:
    try:
        return (today - dt.date.fromisoformat(str(day)[:10])).days
    except ValueError:
        return None


def _row(name, kind, url, status, why, count, newest, tier, note=""):
    return {"name": name, "category": kind, "url": url, "status": status, "why": why, "items": count,
            "newest": newest or "", "tier": tier or "", "note": note}


def table(rows: list, last_status: dict, newsletters: list, x_status: dict, bluesky_cfg: dict, index_rows: list,
          dropped_links: list | None = None, today: dt.date | None = None) -> list:
    """All sources -> [{name, category, url, status, why, items, newest, tier, note, priority}], priority order.
    rows: sources.yaml entries enriched as on the Sources page ({person, kind, url, tier, last, archived, newest});
    last_status: {(person, url): newest per_source fetch record}; newsletters: mailsource.status()["newsletters"];
    x_status: xsource.status(); bluesky_cfg: config bluesky; index_rows: data/index.jsonl;
    dropped_links: URLs the deep dives dropped as unreachable (data/deepdives.jsonl sources_dropped)."""
    today = today or dt.date.today()
    out, seen = [], set()

    def judge(err_status, err, count, newest, quiet_days):
        if err_status == "error":
            return "failing", reason(err)
        if not count:
            return "known, not ingested", "never arrived" if not err_status else "nothing archived yet"
        d = _days_since(newest, today)
        if d is not None and d > quiet_days:
            return "quiet", f"nothing new for {d} days"
        return "ingesting", ""

    for s in rows:
        last = s.get("last") or {}
        st, why = judge(last.get("status"), last.get("error", ""), s.get("archived", 0), s.get("newest", ""), QUIET_DAYS)
        out.append(_row(s.get("person", ""), kind_of(s.get("kind", ""), s.get("url", "")), s.get("url", ""), st, why,
                        s.get("archived", 0), s.get("newest", ""), s.get("tier", ""), (last.get("error") or "")[:160]))
        seen.add((s.get("person"), s.get("url")))

    by_person = Counter()
    newest_by = {}
    for r in index_rows:
        p = r.get("person")
        by_person[p] += 1
        newest_by[p] = max(newest_by.get(p, ""), (r.get("published") or r.get("first_seen") or "")[:10])
    for (person, url), last in last_status.items():          # fetchers outside sources.yaml: X, Bluesky, Slack ...
        if (person, url) in seen:
            continue
        kind = kind_of(last.get("kind", ""), url)
        if kind == "Email newsletter":
            continue                                          # listed from newsletters.yaml below
        n = by_person.get(person, 0)
        st, why = judge(last.get("status"), last.get("error", ""), n or last.get("new", 0), newest_by.get(person, ""), QUIET_DAYS)
        out.append(_row(person, kind, url, st, why, n, newest_by.get(person, ""), "", (last.get("error") or "")[:160]))
        seen.add((person, url))

    for nl in newsletters or []:
        st, why = judge("", "", nl.get("count", 0), nl.get("latest", ""), NEWSLETTER_QUIET_DAYS)
        out.append(_row(nl.get("name", ""), "Email newsletter", nl.get("web") or ", ".join(nl.get("from") or []),
                        st, why, nl.get("count", 0), nl.get("latest", ""), nl.get("tier", "")))

    xs = x_status or {}
    x_down = bool(xs.get("last_fail")) and str(xs.get("last_fail", "")) > str(xs.get("last_good", ""))
    for a in xs.get("accounts") or []:
        if a.get("count") and not x_down:
            st, why = judge("", "", a["count"], a.get("latest", ""), QUIET_DAYS)
        elif x_down:
            st, why = "failing", "no X mirror answered"
        else:
            st, why = "known, not ingested", "never arrived"
        out.append(_row(a.get("name") or a.get("handle", ""), "X", f"https://x.com/{a.get('handle', '')}", st, why,
                        a.get("count", 0), a.get("latest", ""), a.get("tier", "")))

    listed = {u for (_, u) in seen}
    for u in (bluesky_cfg or {}).get("lists") or []:
        if u in listed:
            continue
        out.append(_row("Bluesky list", "Bluesky", u, "known, not ingested", "not fetched yet (new in config)", 0, "", "",
                        "goes live with the next release"))

    hosts = Counter(urlsplit(u).netloc.removeprefix("www.") for u in dropped_links or [] if u.startswith("http"))
    have_hosts = {urlsplit(r["url"]).netloc.removeprefix("www.") for r in out if str(r.get("url", "")).startswith("http")}
    for host, n in hosts.most_common():
        if n < 2 or host in have_hosts:
            continue
        out.append(_row(host, "Deep-dive citation", f"https://{host}/", "known, not ingested", "bot wall / paywall", 0, "", "",
                        f"dropped {n} times as unreachable when a deep dive cited it"))

    for r in out:
        m = re.search(r"dropped (\d+)", r["note"])
        gap = int(m.group(1)) if m else r["items"]
        r["_key"] = (STATUS_ORDER.get(r["status"], 9), 0 if "close" in r["tier"].lower() else 1, -gap, r["category"], r["name"])
    out.sort(key=lambda r: r.pop("_key"))
    for i, r in enumerate(out, 1):
        r["priority"] = i if r["status"] != "ingesting" else ""
    return out


def summary(t: list) -> dict:
    """{status: n} and {category: n} over the sources that need work."""
    bad = [r for r in t if r["status"] != "ingesting"]
    return {"status": dict(Counter(r["status"] for r in t)),
            "categories": dict(Counter(f"{r['category']} · {r['why']}" for r in bad).most_common())}
