"""Who they are (Steven, 2026-11-04): help readers keep up with the companies in the news.

- The FIRST time the briefing ever names a company: one or two sentences (at most 45 words) on what it does and how
  it differs from, or complements, the well-known players.
- A company that has been covered, but not in the last `analysis.who_they_are_days` days (default 14): a one-sentence
  reminder (at most 22 words). Reminders build on what we said before, so the description stays recognisable from
  one mention to the next, and change only where the company has (a new product, a pivot, a round).
- Covered recently: nothing; the reader already has the context.

Two model calls after the edition is written: the first names the company each item is about; code decides intro,
reminder or nothing; the second drafts the lines, given the company's earlier descriptions. Code keeps a line only if
it is short enough and every number in it is in that story's sources. Must read items get a "Who they are" field;
Worth knowing, Money and In brief items get the line in italics after the headline. Every description is kept in
data/state/companies.json (first seen, the lines used, when), which is what the next reminder builds on.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

MAX_PER_EDITION = 6
LIMITS = {"intro": (45, 2), "reminder": (22, 1)}          # words, sentences
MEMORY = "data/state/companies.json"
HOUSEHOLD = {"openai", "google", "alphabet", "microsoft", "nvidia", "apple", "meta", "amazon", "anthropic", "tesla",
             "ibm", "intel", "amd", "oracle", "samsung", "x", "xai", "deepmind", "google deepmind"}
NAME_PROMPT = """For each numbered news item, name the ONE company the headline is about (its subject), or "" if the
item is not about a single company. Use the company's usual short name.

Return ONLY JSON: {{"items": [{{"n": <number>, "company": "<name>"}}]}}

ITEMS:
{block}"""
LINE_PROMPT = """You help readers of a daily AI briefing for investors keep up with the companies in the news.
For each company below write the line asked for:
- "intro" (the first time we mention it): one or two sentences, at most 40 words: what the company does, and how it
  differs from or complements the well-known players in its space (name one or two).
- "reminder" (we covered it before, but not lately): ONE sentence, at most 20 words, that reminds the reader who it
  is. Keep it consistent with our earlier lines (given), so readers recognise it; change it only where the company
  has changed (a new product, a pivot, a round), and don't copy the earlier line word for word.
Base it on the source text; use general knowledge only for what the company plainly is. No numbers unless they are in
the source text. No hype words. If you are not sure what the company does, return "" for the line.

Return ONLY JSON: {{"items": [{{"n": <number>, "line": "<the line>"}}]}}

COMPANIES:
{block}"""
_NUM = re.compile(r"\d[\d,.]*")


def _briefings(root: Path, day: str, days: int | None = None) -> str:
    since = (dt.date.fromisoformat(day) - dt.timedelta(days=days)).isoformat() if days else ""
    out = []
    for f in sorted((Path(root) / "briefings").glob("????-??-??.md")):
        if since <= f.stem < day:
            try:
                out.append(f.read_text("utf-8"))
            except OSError:
                pass
    return "\n".join(out)


def mentioned(company: str, text: str) -> bool:
    c = company.strip()
    return len(c) >= 2 and bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(c) + r"(?![A-Za-z0-9])", text, re.I))


def mode(company: str, past: str, recent: str) -> str:
    """'intro' (never covered), 'reminder' (covered, not recently) or '' (covered recently, or a household name)."""
    if not company or company.strip().lower() in HOUSEHOLD:
        return ""
    if not mentioned(company, past):
        return "intro"
    return "" if mentioned(company, recent) else "reminder"


def check(line: str, source: str, kind: str = "intro") -> str:
    """'' when the line can go in; else why not."""
    line = " ".join((line or "").split())
    if not line:
        return "empty"
    words, sents = LIMITS[kind]
    if len(line.split()) > words:
        return "too long"
    if len(re.findall(r"[.!?](\s|$)", line)) > sents:
        return f"more than {sents} sentence{'s' if sents > 1 else ''}"
    src = (source or "").replace(",", "")
    missing = [n for n in _NUM.findall(line) if n.replace(",", "").rstrip(".") not in src]
    return f"number not in the sources: {', '.join(missing)}" if missing else ""


def load_memory(root: Path) -> dict:
    try:
        return json.loads((Path(root) / MEMORY).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def remember(root: Path, day: str, company: str, kind: str, line: str) -> None:
    mem = load_memory(root)
    key = company.strip().lower()
    e = mem.setdefault(key, {"name": company.strip(), "first": day, "lines": []})
    e["lines"] = (e.get("lines") or [])[-4:] + [{"day": day, "kind": kind, "line": line}]
    p = Path(root) / MEMORY
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mem, indent=1, ensure_ascii=False) + "\n", "utf-8")


def _items(sel: dict) -> list:
    return [(kind, s) for kind in ("must", "worth", "money", "brief") for s in sel.get(kind) or [] if s.get("headline")]


def insert(md: str, kind: str, headline_md: str, line: str) -> str:
    """Put the line next to that item; unchanged if the item can't be found."""
    lines = md.splitlines()
    end = "\n" if md.endswith("\n") else ""
    if kind == "must":
        for i, ln in enumerate(lines):
            if ln.startswith("### ") and headline_md in ln:
                for j in range(i + 1, min(i + 8, len(lines))):
                    if lines[j].startswith("- **"):
                        lines.insert(j, f"- **Who they are:** {line}")
                        return "\n".join(lines) + end
                return md
        return md
    for i, ln in enumerate(lines):
        if ln.startswith("- ") and headline_md in ln:
            if "**" in ln:                                       # worth / money: "- **n. Headline.** text (links)"
                k = ln.index("**", ln.index("**") + 2) + 2
                lines[i] = ln[:k] + f" *{line}*" + ln[k:]
            else:                                                # in brief: "- Headline (links)"
                k = ln.rfind(" (")
                k = k if k > 0 else len(ln)
                lines[i] = ln[:k] + f". *{line}*" + ln[k:]
            return "\n".join(lines) + end
    return md


def apply(root: Path, day: str, md: str, sel: dict, llm, log=print, recent_days: int = 14) -> tuple:
    """-> (md, stats). Never raises: on any model error the edition is returned unchanged."""
    from . import stages
    from .editorial import _md
    items = _items(sel)
    stats = {"items": len(items), "intro": [], "reminder": [], "rejected": []}
    if not items:
        return md, stats
    raw = stages.raw_items(root, [i for _, s in items for i in s.get("ids", [])])
    texts = [" ".join(((raw.get(i) or {}).get("title", "") + " " + (raw.get(i) or {}).get("text", ""))[:2500]
                      for i in s.get("ids", [])) for _, s in items]
    try:
        names = stages._ask(llm, "You are a careful financial journalist.", NAME_PROMPT.format(
            block="\n".join(f"{n}. {s['headline']}" for n, (_, s) in enumerate(items, 1))), 800) or {}
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"{type(e).__name__}: {e}"[:160]
        log(f"who they are: skipped ({stats['error']})")
        return md, stats
    past, recent, mem = _briefings(root, day), _briefings(root, day, recent_days), load_memory(root)
    todo, seen = [], set()
    for r in names.get("items") or []:
        try:
            n = int(r.get("n"))
            kind, s = items[n - 1]
        except (TypeError, ValueError, IndexError):
            continue
        company = str(r.get("company") or "").strip()
        m = mode(company, past, recent)
        if m and company.lower() not in seen and len(todo) < MAX_PER_EDITION:
            seen.add(company.lower())
            todo.append((n, kind, s, company, m))
    if not todo:
        log("who they are: no company new or back after a while")
        return md, stats
    block = []
    for k, (n, _, s, company, m) in enumerate(todo, 1):
        earlier = [x["line"] for x in (mem.get(company.lower()) or {}).get("lines", [])][-2:]
        block.append(f"{k}. {company} ({m})\n   headline: {s['headline']}\n   source: {texts[n - 1][:1500]}"
                     + (f"\n   our earlier lines: {' | '.join(earlier)}" if earlier else ""))
    try:
        out = stages._ask(llm, "You are a careful financial journalist.", LINE_PROMPT.format(block="\n".join(block)), 2000) or {}
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"{type(e).__name__}: {e}"[:160]
        log(f"who they are: skipped ({stats['error']})")
        return md, stats
    lines = {}
    for r in out.get("items") or []:
        try:
            lines[int(r.get("n"))] = " ".join(str(r.get("line") or "").split())
        except (TypeError, ValueError):
            continue
    for k, (n, kind, s, company, m) in enumerate(todo, 1):
        line = lines.get(k, "")
        why = check(line, texts[n - 1] + " " + s["headline"], m)
        if why:
            stats["rejected"].append(f"{company}: {why}")
            continue
        new = insert(md, kind, _md(s["headline"]), line)
        if new != md:
            md = new
            stats[m].append(company)
            remember(root, day, company, m, line)
    log(f"who they are: {len(stats['intro'])} introduced, {len(stats['reminder'])} reminded"
        + (f" ({', '.join(stats['intro'] + stats['reminder'])})" if stats['intro'] or stats['reminder'] else "")
        + (f"; {len(stats['rejected'])} rejected" if stats["rejected"] else ""))
    return md, stats
