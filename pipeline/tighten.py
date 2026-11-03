"""Tighten the written edition (Steven, 2026-11-03: "sticking to the point, not rambling", "repetition of phrases
should be avoided"). After the edition is written and before the fact check, sentences over 35 words and sentences
that repeat an over-used phrase are rewritten by the model, and every rewrite is checked by code: the same numbers,
the same links, the same quoted words, no new names, and not much longer or shorter. A rewrite that fails any check
is dropped and the original sentence stays. Measured by pipeline/craft.py (long_sent_pct, repeats).
"""
from __future__ import annotations

import re

from . import craft

MAX_WORDS = craft.LONG_SENT
LIMIT = 14                                   # sentences per edition, longest first
PROMPT = """You edit a daily AI briefing for investors. Rewrite each numbered sentence below so it reads cleanly:
- split any sentence over 35 words into two or three shorter sentences;
- where a sentence uses an over-used phrase (listed), say it differently;
- keep every fact, number, name and quotation exactly; keep every [n](url) citation exactly, attached to the same claim;
- add nothing new: no new facts, names, numbers, opinions or hedges; remove nothing that matters;
- plain words, same tone, no filler ("notably", "importantly", "it's worth noting").

Over-used phrases: {phrases}

Return ONLY JSON: {{"rewrites": [{{"i": <number>, "text": "<the rewritten sentence or sentences>"}}]}}
Leave out any sentence you cannot improve without breaking a rule.

SENTENCES:
{block}"""

_NUM = re.compile(r"\d[\d,.]*\s*(?:%|[kKmMbBtT]\b|bn\b)?")
_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
_QUOTE = re.compile(r"[\"“]([^\"”]{3,})[\"”]")
_CAP = re.compile(r"\b[A-Z][a-zA-Z0-9&.-]+")
SKIP_SECTIONS = re.compile(r"(?m)^##\s*(Sources|Recommended reading|Open questions)\b")


def _words(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", _LINK.sub("", s)))


def _prose_lines(md: str) -> list:
    """(line index, line) of editable prose: not headings, not the sources/reading lists, not tables or rules."""
    out, skip = [], False
    for i, ln in enumerate(md.splitlines()):
        if ln.startswith("## "):
            skip = bool(SKIP_SECTIONS.match(ln))
            continue
        if skip or not ln.strip() or ln.startswith(("#", "|", "---", ">", "*AI Briefing")):
            continue
        out.append((i, ln))
    return out


def _sentences(line: str) -> list:
    body = re.sub(r"^\s*-\s+(\*\*[^*]+\*\*\s*)?", "", line)        # bullet marker and bold lead stay put
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", body) if s.strip()]


def candidates(md: str) -> tuple:
    """-> ([(line_index, sentence)], over-used phrases). Long sentences first, then ones carrying a repeated phrase
    after its first use."""
    reps = [g for g, _ in craft.repeats(md)][:8]
    seen, longs, rep_hits = set(), [], []
    for i, ln in _prose_lines(md):
        for s in _sentences(ln):
            low = re.sub(r"[^a-z0-9' ]", " ", _LINK.sub("", s).lower())
            low = " ".join(low.split())
            hit = [g for g in reps if g in low]
            if _words(s) > MAX_WORDS:
                longs.append((i, s))
            elif any(g in seen for g in hit):
                rep_hits.append((i, s))
            seen.update(hit)
    longs.sort(key=lambda x: -_words(x[1]))
    return (longs + rep_hits)[:LIMIT], reps


def check(orig: str, new: str) -> str:
    """'' when the rewrite keeps the facts; else why not."""
    if not new or not new.strip():
        return "empty"
    norm = lambda xs: sorted(x.replace(",", "").replace(" ", "") for x in xs)
    if norm(_NUM.findall(_LINK.sub("", orig))) != norm(_NUM.findall(_LINK.sub("", new))):
        return "numbers changed"
    if sorted(_LINK.findall(orig)) != sorted(_LINK.findall(new)):
        return "citations changed"
    if sorted(_QUOTE.findall(orig)) != sorted(_QUOTE.findall(new)):
        return "quotation changed"
    def caps(t):                                 # capitalised words that are not just a sentence's first word
        t = re.sub(r"(^|[.!?:]\s+)[A-Z][a-z]*", r"\1", _LINK.sub("", t))
        return set(_CAP.findall(t))
    extra = {w for w in caps(new) - caps(orig) if w.lower() not in orig.lower()}
    if extra:
        return "new name: " + ", ".join(sorted(extra))[:60]
    a, b = _words(orig), _words(new)
    if b > a * 1.15 + 3 or b < a * 0.7:
        return f"length changed {a} -> {b}"
    return ""


def apply(md: str, llm, log=print) -> tuple:
    """-> (md, stats). Never raises: on any model error the edition is returned unchanged."""
    cands, reps = candidates(md)
    stats = {"candidates": len(cands), "rewritten": 0, "rejected": []}
    if not cands:
        return md, stats
    from . import stages
    block = "\n".join(f"{n}. {s}" for n, (_, s) in enumerate(cands, 1))
    try:
        out = stages._ask(llm, "You are a careful copy editor. You never change facts.",
                          PROMPT.format(phrases="; ".join(reps) or "(none)", block=block), 3000) or {}
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"{type(e).__name__}: {e}"[:160]
        log(f"tighten: skipped ({stats['error']})")
        return md, stats
    lines = md.splitlines()
    for r in out.get("rewrites") or []:
        try:
            n = int(r.get("i"))
            li, orig = cands[n - 1]
        except (TypeError, ValueError, IndexError):
            continue
        new = " ".join(str(r.get("text") or "").split())
        why = check(orig, new)
        if why:
            stats["rejected"].append(f"{n}: {why}")
            continue
        if orig in lines[li]:
            lines[li] = lines[li].replace(orig, new, 1)
            stats["rewritten"] += 1
    log(f"tighten: {stats['rewritten']} of {len(cands)} sentence(s) rewritten"
        + (f"; {len(stats['rejected'])} rejected ({'; '.join(stats['rejected'][:3])})" if stats["rejected"] else ""))
    return "\n".join(lines) + ("\n" if md.endswith("\n") else ""), stats
