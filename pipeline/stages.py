"""LLM stages: filter → summarize (rank/tag) → critique → write briefing.

Everything a stage produces is appended to data/summaries/YYYY-MM-DD.jsonl, one record
per item, with the item's source URL, the backend/model and the prompt version used.
Re-running never overwrites: a newer record for the same item is simply appended.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path

from .archive import append_jsonl, read_jsonl  # noqa: F401 (re-exported)
from .llm import Backend, LLMError

PROMPTS = Path(__file__).parent / "prompts"
TAGS = ("FULL READ", "SUMMARY ONLY")
VERDICTS = ("holds", "mixed", "overstated", "unsupported", "unverified")   # unverified: only a headline could be read


# ---------- prompts ----------

# Full-text prompt overrides from the active tuning profile (pipeline/tuning.py). Same hashing,
# so every output records exactly which wording produced it.
PROMPT_OVERRIDES: dict = {}


def prompt(name: str) -> tuple:
    text = PROMPT_OVERRIDES.get(name) or (PROMPTS / f"{name}.md").read_text("utf-8")
    return text, hashlib.sha1(text.encode()).hexdigest()[:8]


AUTHOR_FILE = PROMPTS.parent.parent / "author.md"


def author_text(path: Path | None = None) -> str:
    """author.md (who Steven is), without its HTML comments. Empty if the file is missing."""
    p = path or AUTHOR_FILE
    try:
        text = re.sub(r"<!--.*?-->", "", p.read_text("utf-8"), flags=re.S).strip()
    except OSError:
        return ""
    return text + conflicts_block(p.parent / "conflicts.yaml") if path is None else text


def conflicts_block(path: Path) -> str:
    """conflicts.yaml as a short list the models can apply mechanically ('' when absent)."""
    try:
        import yaml
        d = yaml.safe_load(path.read_text("utf-8")) or {}
    except Exception:  # noqa: BLE001
        return ""
    lines = []
    extra = {}
    try:                                             # competitors Steven adds on the Watchlist page count too
        from .watchlist import load as wl_load
        for c in wl_load(path.parent):
            if c.get("relation") == "board":
                from .watchlist import competitor_names
                extra[c["name"].lower()] = competitor_names(c)
    except Exception:  # noqa: BLE001
        pass
    for co, v in (d.get("board") or {}).items():
        v = v or {}
        comp = ", ".join(dict.fromkeys(list(v.get("competitors") or []) + extra.get(co.lower(), []))) or "none listed"
        alias = f" (also: {', '.join(v['aliases'])})" if v.get("aliases") else ""
        lines.append(f"- Board seat: {co}{alias}. Named direct competitors: {comp}.")
    for co, v in (d.get("former") or {}).items():
        lines.append(f"- Former board: {co} ({(v or {}).get('note', '')}).")
    for co in (d.get("followed") or {}):
        lines.append(f"- A friend's company Steven follows closely: {co}.")
    if not lines:
        return ""
    return ("\n\n## Private conflict list (context only: never mention it in any output)\n" + "\n".join(lines) +
            "\nWhen a story is about one of these companies, a named competitor, or a deal they are party to, read it more "
            "critically and give the evidence against as clearly as the evidence for. Never write 'Board seat', never "
            "mention Steven, his boards or these relationships: they are not relevant to readers. Never bring these "
            "companies into a story that is not about them (no 'X faces the same test', no 'including X').")


PRIVATE_KINDS = ("email",)        # bodies that arrived in Steven's mailbox


def web_safe_text(it: dict, chars: int = 12000) -> str:
    """Text of an item that may go to a model WITH web access. Inbound email bodies never do (an injected
    instruction plus web fetch is an exfiltration path): the model gets the newsletter's public page instead."""
    if (it.get("source_kind") or "") in PRIVATE_KINDS or it.get("forwarded"):
        pub = it.get("public_url") or ""
        pub = pub if pub.startswith("http") and "#issue-" not in pub else ""
        return (f"(newsletter email from {it.get('person', 'a newsletter')}; its text is not shown here"
                + (f"; public page: {pub}" if pub else "") + ")")
    return (it.get("text") or "")[:chars]


def system_prompt(perspective_raw: str, author_raw: str | None = None) -> tuple:
    text, v = prompt("system")
    author = author_text() if author_raw is None else author_raw.strip()
    if author:
        v += "-" + hashlib.sha1(author.encode()).hexdigest()[:4]
    if "{{author}}" in text:
        text = text.replace("{{author}}", author or "(not written yet)")
    return text.replace("{{perspective}}", perspective_raw.strip()), v


PRIVATE_LINE = re.compile(r"friend|colleague|my network|people i know", re.I)
_NAME = re.compile(r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?) ([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b")
_NOT_NAMES = {"Google Brain", "Google Canada", "New York", "Machine Learning", "Data Science",
              "Frontier Lab", "Google Deep"}


def _owner_not_names() -> set:
    from .owner import get as owner
    return set(owner()["not_names"])


def private_names(text: str | None = None) -> list:
    """People from Steven's network named in author.md on lines about friends/colleagues. The briefing and
    podcast are read by others, so these names never appear in output; see scrub_private()."""
    if text is None:
        priv = AUTHOR_FILE.parent / "author-private.md"
        a = (priv.read_text("utf-8") if priv.exists() else "") + "\n" + author_text()
    else:
        a = text
    names = []
    for line in a.splitlines():
        if not PRIVATE_LINE.search(line):
            continue
        body = re.sub(r"\([^)]*\)", " ", line)            # company names in parentheses are fine to say
        body = re.sub(r"\*\*[^*]*\*\*", " ", body)       # the bold label of the line
        for m in _NAME.finditer(body):
            full = f"{m.group(1)} {m.group(2)}"
            if full not in _NOT_NAMES and full not in _owner_not_names() and full not in names:
                names.append(full)
    return names


def scrub_private(text: str, names: list | None = None, allow=()) -> tuple:
    """Replace network names with a generic phrase -> (text, hits).

    A name in `allow` (someone who is a published source in today's material) is left alone: a source is
    cited by name whoever they are. A bare first name is replaced only when it is not followed by another
    capitalised word, so "Ali Ghodsi" or "Ray Dalio" stay intact."""
    names = private_names() if names is None else names
    allow = {a.lower() for a in allow}
    hits = []
    for full in names:
        if full.lower() in allow:
            continue
        first = full.split()[0]
        pat_full = r"\b" + re.escape(full) + r"\b"
        if re.search(pat_full, text):
            hits.append(full)
            text = re.sub(pat_full, "an industry expert", text)
        pat_first = r"(?<![\w-])" + re.escape(first) + r"(?![\w-])(?!\s+[A-Z][a-z])"
        if re.search(pat_first, text):
            hits.append(first)
            text = re.sub(pat_first, "an expert", text)
    # generic wording, never first person (the edition is public): "ask an industry expert"
    text = re.sub(r"\ban? (?:industry )?expert(?:,? (?:or|and) an? (?:industry )?expert)+", "industry experts", text)
    text = re.sub(r"(^|[.!?]\s+|\n[-*]?\s*)(an industry expert|an expert|industry experts)",
                  lambda m: m.group(1) + m.group(2)[0].upper() + m.group(2)[1:], text)
    return text, hits


def allowed_names(names: list, sources) -> list:
    """Network names that appear in today's source attributions (person/author fields, bylines)."""
    blob = " ".join(str(s) for s in sources).lower()
    return [n for n in names if n.lower() in blob]


_QUOTE_SPAN = re.compile(r"[\"“]([^\"”\n]{2,300})[\"”]")


def _qnorm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    return re.sub(r"\s+", " ", s).strip(" .,;:!?").lower()


def verify_quotes(md: str, texts: list) -> tuple:
    """Every phrase in quotation marks must appear word for word in the source material; otherwise the quotation
    marks are removed (the words stay, as a paraphrase). Link targets are left untouched -> (md, removed)."""
    hay = _qnorm(" ".join(texts))
    removed = []

    def fix(m: re.Match) -> str:
        q = m.group(1)
        if _qnorm(q) and _qnorm(q) in hay:
            return m.group(0)
        removed.append(q)
        return q
    out = []
    for line in md.splitlines():
        parts = re.split(r"(\]\([^)]*\))", line)            # don't touch "](url)" segments
        out.append("".join(p if p.startswith("](") else _QUOTE_SPAN.sub(fix, p) for p in parts))
    return "\n".join(out) + ("\n" if md.endswith("\n") else ""), removed


def raw_items(root: Path, ids, days: int = 21) -> dict:
    """id -> fetched item (the raw archive, most recent days first)."""
    want, out = set(ids), {}
    for f in sorted((root / "data" / "raw").glob("*/items.jsonl"), reverse=True)[:days]:
        for r in read_jsonl(f):
            if r.get("id") in want and r["id"] not in out:
                out[r["id"]] = r
        if len(out) == len(want):
            break
    return out


def source_texts(root: Path, ids, days: int = 21) -> list:
    """Title + text of the given item ids from the raw archive (most recent days first)."""
    want, out = set(ids), []
    raw = sorted((root / "data" / "raw").glob("*/items.jsonl"), reverse=True)[:days]
    for f in raw:
        for r in read_jsonl(f):
            if r.get("id") in want:
                out.append(f"{r.get('title', '')}\n{r.get('text', '')}")
                want.discard(r["id"])
        if not want:
            break
    return out


def public_author_text() -> str:
    """author.md for models with web access: without the private-network section or lines about friends."""
    keep, skip = [], False
    for ln in author_text().splitlines():
        if ln.startswith("## "):
            skip = "private" in ln.lower() or "network" in ln.lower()
        if not skip and not PRIVATE_LINE.search(ln):
            keep.append(ln)
    return "\n".join(keep).strip()


def web_system_prompt(perspective_raw: str) -> tuple:
    return system_prompt(perspective_raw, public_author_text())


def reader_block(web: bool = False) -> str:
    """For stages with their own system prompt (suggestions, deep dives): who Steven is, if written."""
    a = public_author_text() if web else author_text()
    return f"\n\nWho Steven is (the reader; not a source of facts):\n<author>\n{a}\n</author>" if a else ""


def _clean(s: str) -> str:
    # keep fetched text from closing our wrapper tags
    return re.sub(r"</?\s*(item|first_pass|perspective)\b", lambda m: m.group(0).replace("<", "‹"), s or "", flags=re.I)


EMBED_MARKERS = re.compile(r"\[contains quote post or other embedded content\]", re.I)
LOCALES = ("de fr es it pt ja ko zh ar nl ru pl tr sv da fi nb no he hi id th vi uk cs "
           "pt-br zh-cn zh-tw es-419 fr-ca en-gb en-us").split()
_LOCALE_RE = re.compile(r"^/(" + "|".join(sorted(LOCALES, key=len, reverse=True)) + r")(?=/)", re.I)


def content_text(it: dict) -> str:
    return EMBED_MARKERS.sub("", it.get("text", "") or "").strip()


def canonical_url(url: str) -> str:
    """https://x.com/de/blog/a -> https://x.com/blog/a (locale prefix removed)."""
    from urllib.parse import urlparse, urlunparse
    u = urlparse(url)
    return urlunparse(u._replace(path=_LOCALE_RE.sub("", u.path)))


_URL_IN_TEXT = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+/[^\s|)\]\"'<>]+)", re.I)


def _url_key(url: str) -> str:
    u = re.sub(r"^https?://", "", url.strip().lower())
    u = u[4:] if u.startswith("www.") else u
    return u.split("?")[0].split("#")[0].rstrip("/.…")


def links_to_known_article(it: dict, known_keys: set):
    """A social post that just announces an article we already have → that article's URL key."""
    if it.get("source_kind") != "bluesky":
        return None
    for m in _URL_IN_TEXT.finditer(it.get("text", "") or ""):
        cand = _url_key(m.group(1))
        if len(cand.split("/", 1)[-1]) < 8:          # bare domain / tiny path: not an article link
            continue
        for k in known_keys:
            if k == cand or (len(cand) >= 25 and k.startswith(cand)):   # truncated links
                return k
    return None


def prefilter(items: list, known_urls: set, min_chars: int = 60, exclude=()) -> tuple:
    """Rule-based drops before any LLM call: empty items and translated duplicates.
    Returns (items_for_llm, decisions_for_dropped)."""
    decisions, rest = {}, []
    for it in items:   # URL patterns excluded in sources.yaml (e.g. digest pages archived before the rule)
        hit = next((x for x in exclude if x and x in it["url"]), None)
        if hit:
            decisions[it["id"]] = {"keep": False, "rule": True, "reason": f"excluded URL pattern {hit}"}
    items = [it for it in items if it["id"] not in decisions]
    known_keys = {_url_key(u) for u in known_urls}
    article_keys = {_url_key(u) for u in known_urls if "bsky.app" not in u}
    social_dupes = []
    for it in items:
        hit = links_to_known_article(it, article_keys)
        if hit:
            decisions[it["id"]] = {"keep": False, "rule": True,
                                   "reason": f"announces an article already archived: {hit}"}
            social_dupes.append(it["id"])
    items = [it for it in items if it["id"] not in social_dupes]
    groups = {}
    for it in items:
        groups.setdefault(canonical_url(it["url"]), []).append(it)
    for canon, group in groups.items():
        localized = [it for it in group if it["url"] != canon]
        if canon in known_urls or len(group) > 1:
            original = next((it for it in group if it["url"] == canon), None)
            keep_one = None if canon in known_urls and original is None else (original or localized[0])
            for it in group:
                if it is not keep_one:
                    decisions[it["id"]] = {"keep": False, "reason": f"translated duplicate of {canon}", "rule": True}
            if keep_one is not None:
                group = [keep_one]
            else:
                group = []
        for it in group:
            body = content_text(it)
            title = EMBED_MARKERS.sub("", it.get("title", "") or "").strip(" …")
            if len(body) < min_chars and len(title) < min_chars:
                decisions[it["id"]] = {"keep": False, "rule": True,
                                       "reason": "no substantive content (e.g. repost / embed only)"}
            else:
                rest.append(it)
    return rest, decisions


OWNER_PERSONS = ("Shared by Steven", "Forwarded by Steven")
_OUTLET_NAMES = {"nytimes.com": "The New York Times", "ft.com": "Financial Times", "wsj.com": "The Wall Street Journal",
                 "theinformation.com": "The Information", "thein.fo": "The Information", "techcrunch.com": "TechCrunch",
                 "theverge.com": "The Verge", "apnews.com": "AP", "bbc.com": "BBC", "bbc.co.uk": "BBC",
                 "washingtonpost.com": "The Washington Post", "theglobeandmail.com": "The Globe and Mail",
                 "technologyreview.com": "MIT Technology Review", "arstechnica.com": "Ars Technica", "cnbc.com": "CNBC"}


def outlet_name(url: str) -> str:
    h = _host(url or "")
    if h in _OUTLET_NAMES:
        return _OUTLET_NAMES[h]
    base = h.rsplit(".", 2)[-2] if h.count(".") >= 1 else h
    return base.capitalize() if base else "A reader"


def display_name(r: dict) -> str:
    """Who the item is from, for humans: a source label (e.g. Anthropic) beats the tracked-person row. Something
    Steven shared or forwarded is credited to its outlet: he is never named in public copy."""
    if r.get("source_label"):
        return r["source_label"]
    if r.get("person", "") in OWNER_PERSONS:
        return outlet_name(r.get("linked_url") or r.get("url") or "")
    return r.get("person", "")


def _host(url: str) -> str:
    from urllib.parse import urlparse
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def apply_labels(rows: list, labels_by_host: dict) -> None:
    """Fill source_label on items/records that predate labels, by matching the URL's host."""
    for r in rows:
        if not r.get("source_label"):
            lab = labels_by_host.get(_host(r.get("url", "")))
            if lab:
                r["source_label"] = lab


def item_block(it: dict, max_chars: int) -> str:
    text = _clean(content_text(it))[:max_chars]
    who = (f"source: {it['source_label']} (organization; filed under tracked person {it.get('person', '')})"
           if it.get("source_label") else f"person: {it.get('person', '')}")
    lines = [f'<item id="{it["id"]}">',
             f"{who}  (tier: {it.get('tier', '')}"
             f"{', SCRUTINY' if it.get('scrutiny') else ''}"
             f"{', ' + ', '.join(it.get('flags') or []) if it.get('flags') else ''})",
             f"fetched from: {it.get('source_kind', '')} {it.get('source_url', '')}",
             f"published: {it.get('published') or 'unknown'}",
             f"url: {it.get('url', '')}",
             f"title: {_clean(it.get('title', ''))}"]
    if it.get("description"):
        lines.append(f"description: {_clean(it['description'])[:400]}")
    if it.get("source_note"):
        lines.append(f"about this source (Steven's note, not part of the item): {_clean(it['source_note'])[:400]}")
    try:
        from .profiles import describe
        lines.append(f"evidence type (source_profiles.yaml): {describe(it)}")
    except Exception:  # noqa: BLE001
        pass
    lines += ["text:", text]
    if it.get("read_text"):                       # the article the post points to (pipeline/reader.py)
        try:
            from .profiles import describe
            kind = describe({**it, "url": it.get("read_url", ""), "person": "", "source_label": ""})
        except Exception:  # noqa: BLE001
            kind = "unknown"
        lines += [f"linked article (fetched from {it.get('read_url', '')}; evidence type: {kind}). "
                  "It is evidence for the post's claim; judge the claim with it:",
                  _clean(it["read_text"])[:max_chars * 2]]
    lines.append("</item>")
    return "\n".join(lines)


# ---------- archive helpers ----------

def latest_summaries(summaries_dir: Path) -> dict:
    out = {}
    if summaries_dir.exists():
        for f in sorted(summaries_dir.glob("*.jsonl")):
            for r in read_jsonl(f):
                out[r["id"]] = r          # later files/lines win
    return out


def briefed_ids(briefings_log: Path) -> set:
    ids = set()
    for b in read_jsonl(briefings_log):
        ids.update(b.get("item_ids", []))
        ids.update(b.get("considered_ids", []))
    return ids


# ---------- stages ----------

def _ask(llm, system: str, user: str, max_tokens: int):
    """complete_json with an output cap; tolerates backends without the max_tokens parameter."""
    try:
        return llm.complete_json(system, user, max_tokens=max_tokens)
    except TypeError:
        return llm.complete_json(system, user)


def run_filter(llm: Backend, items: list, system: str, cfg: dict, log) -> tuple:
    tmpl, version = prompt("filter")
    batch = cfg.get("filter_batch", 5)
    chars = cfg.get("filter_chars", 1200)
    decisions, errors = {}, []

    def decide(chunk, depth=0):
        user = tmpl.replace("{{items}}", "\n\n".join(item_block(it, chars) for it in chunk))
        try:
            out = _ask(llm, system, user, 120 + 60 * len(chunk))
        except Exception as e:  # noqa: BLE001
            if len(chunk) > 1:            # e.g. "token repeat limit": retry in halves
                log.warning("filter: batch of %d failed (%s); splitting", len(chunk), str(e)[:120])
                mid = len(chunk) // 2
                decide(chunk[:mid], depth + 1)
                decide(chunk[mid:], depth + 1)
            else:
                errors.append(f"{chunk[0]['id']}: {type(e).__name__}: {e}"[:300])
                log.warning("filter failed for %s: %s", chunk[0]["id"], e)
            return
        ids = {it["id"] for it in chunk}
        for d in out.get("decisions", []):
            if isinstance(d, dict) and d.get("id") in ids:
                keep = d.get("keep")
                keep = keep if isinstance(keep, bool) else str(keep).lower() in ("true", "yes", "1")
                decisions[d["id"]] = {"keep": keep, "reason": str(d.get("reason", ""))[:200]}

    # Long-form posts from tracked sources skip the model filter: the summarize stage scores
    # their relevance (importance 1 = left out of the briefing). Dropping them here proved too
    # aggressive (e.g. Import AI, The Batch). The filter is for short social posts.
    long_kinds = set(cfg.get("filter_skip_kinds", ["site", "feed", "pages"]))
    min_long = cfg.get("filter_skip_min_chars", 800)
    short = []
    for it in items:
        if it.get("source_kind") in long_kinds and len(content_text(it)) >= min_long:
            decisions[it["id"]] = {"keep": True, "reason": "long-form from tracked source (not filtered)"}
        else:
            short.append(it)
    for i in range(0, len(short), batch):
        decide(short[i:i + batch])
    for it in items:   # fail open: never lose an item because the model misbehaved
        decisions.setdefault(it["id"], {"keep": True, "reason": "no decision returned (kept by default)"})
    return decisions, version, errors


def _norm_summary(s: dict) -> dict:
    tag = str(s.get("tag", "")).upper().strip()
    tag = tag if tag in TAGS else "SUMMARY ONLY"
    try:
        imp = max(1, min(5, int(float(s.get("importance", 3)))))
    except (TypeError, ValueError):
        imp = 3
    topics = s.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    crit = s.get("critique_needed")
    crit = crit if isinstance(crit, bool) else str(crit).lower() in ("true", "yes", "1")
    headline = re.sub(r"\s+", " ", str(s.get("headline", "") or "")).strip().strip('"“”')[:140]
    return {"headline": headline, "claim": str(s.get("claim", "")).strip(), "so_what": str(s.get("so_what", "")).strip(),
            "agenda_flag": str(s.get("agenda_flag", "")).strip(), "tag": tag, "importance": imp,
            "novelty": "repeat" if str(s.get("novelty", "")).lower() == "repeat" else "new",
            "topics": [str(t)[:40] for t in topics][:6], "critique_needed": crit}


def run_summarize(llm: Backend, items: list, system: str, cfg: dict, log) -> tuple:
    tmpl, version = prompt("summarize")
    chars = cfg.get("summary_chars", 6000)
    out, errors = {}, []
    for n, it in enumerate(items, 1):
        t0 = time.monotonic()
        try:
            s = _ask(llm, system, tmpl.replace("{{item}}", item_block(it, chars)), 900)
            out[it["id"]] = _norm_summary(s)
            from .consistency import check_roles             # "X founder ..." needs the role in the item itself
            src = " ".join(str(it.get(k) or "") for k in ("title", "text", "person", "author"))
            out[it["id"]]["agenda_flag"], rn = check_roles(out[it["id"]]["agenda_flag"], src)
            if rn:
                out[it["id"]]["agenda_note"] = rn
            bad = unverified_quotes(" ".join([out[it["id"]]["claim"], out[it["id"]]["so_what"]]), it)
            if bad:
                out[it["id"]]["unverified_quotes"] = bad
            log.info("  summarize %d/%d %.1fs %s", n, len(items), time.monotonic() - t0,
                     _one_line(it.get("title", ""))[:60])
        except Exception as e:  # noqa: BLE001
            errors.append(f"{it['id']}: {type(e).__name__}: {e}"[:300])
            log.warning("  summarize failed for %s: %s", it["id"], e)
    return out, version, errors


# Double quotes, or single quotes used as quotes (not apostrophes: must open after a space/bracket
# and close before punctuation/space).
_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{12,}?)[\"“”]|(?:^|(?<=[\s(\[]))['‘]([^'‘’]{12,}?)['’](?=[\s.,;:!?)\]]|$)")


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"“”‘’'`]", "", s or "")).strip().lower()


def unverified_quotes(generated: str, it: dict) -> list:
    """Quoted phrases (3+ words) in model output that don't appear in the item. Hallucination guard."""
    src = _norm_text(it.get("title", "") + " " + it.get("text", "") + " " + it.get("description", ""))
    out = []
    for m in _QUOTE_RE.finditer(generated or ""):
        q = m.group(1) or m.group(2) or ""
        if len(q.split()) >= 3 and _norm_text(q) not in src:
            out.append(q.strip())
    return out


def needs_critique(it: dict, s: dict) -> bool:
    return bool(it.get("scrutiny") or s.get("critique_needed") or s.get("importance", 0) >= 4)


def run_critique(llm: Backend, items: list, summaries: dict, system: str, cfg: dict, log) -> tuple:
    tmpl, version = prompt("critique")
    chars = cfg.get("summary_chars", 6000)
    out, errors = {}, []
    for n, it in enumerate(items, 1):
        t0 = time.monotonic()
        s = summaries[it["id"]]
        if it.get("thin") and not it.get("read_text"):      # only a headline: say so instead of judging it
            out[it["id"]] = {"verdict": "unverified", "overstated": "",
                             "missing_evidence": "The full report: only the headline or a teaser could be read.",
                             "would_change_view": "Reading the underlying report or document.",
                             "one_line": "Only a headline so far; the full report could not be read.",
                             "corrected_claim": ""}
            log.info("  critique %d/%d skipped (headline only) %s", n, len(items), _one_line(it.get("title", ""))[:50])
            continue
        first = json.dumps({k: s[k] for k in ("claim", "so_what", "agenda_flag")}, ensure_ascii=False)
        try:
            c = _ask(llm, system, tmpl.replace("{{summary}}", first)
                                  .replace("{{item}}", item_block(it, chars)), 700)
            verdict = str(c.get("verdict", "")).lower().strip()
            log.info("  critique %d/%d %.1fs %s -> %s", n, len(items), time.monotonic() - t0,
                     _one_line(it.get("title", ""))[:50], verdict)
            out[it["id"]] = {"verdict": verdict if verdict in VERDICTS else "mixed",
                             "overstated": str(c.get("overstated", "")).strip(),
                             "missing_evidence": str(c.get("missing_evidence", "")).strip(),
                             "would_change_view": str(c.get("would_change_view", "")).strip(),
                             "one_line": str(c.get("one_line", "")).strip(),
                             "corrected_claim": str(c.get("corrected_claim", "") or "").strip()}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{it['id']}: {type(e).__name__}: {e}"[:300])
            log.warning("  critique failed for %s: %s", it["id"], e)
    return out, version, errors


def critique_text(c: dict) -> str:
    if not c:
        return ""
    parts = [f"{c['verdict'].upper()}."]
    for k in ("overstated", "missing_evidence", "would_change_view"):
        if c.get(k):
            parts.append(c[k])
    return " ".join(parts)


# ---------- records ----------

def build_records(items, decisions, summaries, critiques, meta: dict) -> list:
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    recs = []
    for it in items:
        d = decisions.get(it["id"], {})
        r = {"id": it["id"], "url": it.get("public_url") or it["url"], "title": it.get("title", ""), "person": it.get("person", ""),
             "source_label": it.get("source_label", ""), "source_url": it.get("source_url", ""),
             "tier": it.get("tier", ""), "scrutiny": bool(it.get("scrutiny")), "flags": it.get("flags", []),
             "source_kind": it.get("source_kind", ""), "published": it.get("published", ""),
             "first_seen_run": it.get("run_id", ""), "created": now, **meta,
             "keep": d.get("keep", True), "filter_reason": d.get("reason", "")}
        if d.get("rule"):
            r["filter_rule"] = True
        if it["id"] in summaries:
            r.update(summaries[it["id"]])
        if it.get("read_url"):                      # the article read for the evidence check is what we cite
            r["read_url"] = it["read_url"]
            r["linked_url"] = it.get("linked_url") or it["read_url"]
        if it["id"] in critiques:
            r["critique_detail"] = critiques[it["id"]]
            r["critique"] = critique_text(critiques[it["id"]])
        if r["keep"] and it["id"] not in summaries:
            continue          # summarize failed: write nothing, so the next run retries it
        recs.append(r)
    return recs


def append_records(summaries_dir: Path, day: str, recs: list) -> Path:
    path = summaries_dir / f"{day}.jsonl"
    append_jsonl(path, recs)
    return path


# ---------- briefing ----------

def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _md_title(s: str) -> str:
    return _one_line(s).replace("[", "(").replace("]", ")")


def topline(llm: Backend, entries: list, system: str, log) -> tuple:
    if not entries:
        return [], ""
    tmpl, version = prompt("topline")
    listing = "\n".join(
        f"[{n}] {display_name(e)}: {_one_line(e.get('claim'))} | so what: {_one_line(e.get('so_what'))}"
        + (f" | critical pass: {_one_line(e.get('critique'))}" if e.get("critique") else "")
        for n, e in entries)
    try:
        want = min(4, len(entries))
        bullets = []
        for attempt in range(2):
            user = tmpl.replace("{{entries}}", listing)
            if attempt:
                user += f"\n\nYou returned {len(bullets)} bullet(s). Return {want} bullets."
            out = _ask(llm, system, user, 800)
            raw = out.get("bullets", [])
            if isinstance(raw, dict):
                raw = [raw]
            bullets = []
            for b in raw if isinstance(raw, list) else []:
                if isinstance(b, str) and b.strip():
                    b = {"text": b, "refs": [int(x) for x in re.findall(r"\[(\d+)\]", b)]}
                if isinstance(b, dict) and b.get("text"):
                    b["text"] = re.sub(r"\s*\[\d+\]", "", str(b["text"])).strip()
                    bullets.append(b)
            bullets = bullets[:5]
            if len(bullets) >= min(3, want):
                break
            log.info("topline attempt %d returned %d bullet(s): %s", attempt + 1, len(bullets),
                     json.dumps(out, ensure_ascii=False)[:400])
        return bullets, version
    except Exception as e:  # noqa: BLE001
        log.warning("topline failed: %s", e)
        return [], version


def render_briefing(day: str, records: list, bullets: list, meta: dict, n_dropped: int,
                    max_full: int = 6, max_worth: int = 12) -> tuple:
    """Full read (cap) → Worth knowing (cap) → Also seen one-liners. Importance-1 repeats are
    left out of the text (still archived). Links are inserted by code, never written by the model."""
    newest_first = sorted(records, key=lambda r: r.get("published") or "", reverse=True)
    ranked = sorted(newest_first, key=lambda r: (-(r.get("importance") or 0), r.get("tag") != "FULL READ"))
    repeats = [r for r in ranked if (r.get("importance") or 0) <= 1]
    kept = [r for r in ranked if (r.get("importance") or 0) > 1]
    full = [r for r in kept if r.get("tag") == "FULL READ"][:max_full]
    rest = [r for r in kept if r not in full]
    worth = [r for r in rest if (r.get("importance") or 0) >= 3][:max_worth]
    also = [r for r in rest if r not in worth]
    numbered = list(enumerate(full + worth + also, 1))
    num = {r["id"]: n for n, r in numbered}
    url = {n: r["url"] for n, r in numbered}
    people = sorted({display_name(r) for r in kept})

    L = [f"# AI briefing — {day}", "",
         f"*{len(kept)} items from {len(people)} sources · analysis: {meta.get('models', '')}*", ""]
    if bullets:
        L += ["## Top of mind", ""]
        for b in bullets:
            refs = [int(x) for x in b.get("refs", []) if str(x).isdigit() and int(x) in url]
            links = " ".join(f"[{n}]({url[n]})" for n in refs)
            L.append(f"- {_one_line(b['text'])} {links}".rstrip())
        L.append("")

    def block(r):
        n = num[r["id"]]
        badge = " · SCRUTINY" if r.get("scrutiny") else ""
        out = [f"### {n}. {_md_title(r['title'])}",
               f"**{display_name(r)}**{badge} · [source]({r['url']})"
               + (f" · {r['published'][:10]}" if r.get("published") else ""), "",
               f"- **Claim:** {_one_line(r.get('claim'))}"
               + (" *(quoted wording not found in source)*" if r.get("unverified_quotes") else ""),
               f"- **So what:** {_one_line(r.get('so_what'))}",
               f"- **Agenda:** {_one_line(r.get('agenda_flag'))}"]
        if r.get("critique"):
            out.append(f"- **Evidence check:** {_one_line(r['critique'])}")
        return out + [""]

    if full:
        L += ["## Full read", ""]
        for r in full:
            L += block(r)
    if worth:
        L += ["## Worth knowing", ""]
        for r in worth:
            L += block(r)
    if also:
        L += ["## Also seen", ""]
        for r in also:
            crit = f" *Evidence check: {r['critique_detail']['verdict']}.*" if r.get("critique_detail") else ""
            L.append(f"- **{num[r['id']]}. {display_name(r)}:** {_one_line(r.get('claim'))} "
                     f"([source]({r['url']})){crit}")
        L.append("")
    L += ["---", f"*{n_dropped} items filtered out as off-topic"
          + (f", {len(repeats)} low-relevance items and repeats of known arguments left out" if repeats else "")
          + f". Generated {meta.get('generated', '')}.*", ""]
    return "\n".join(L), [r["id"] for _, r in numbered]
