"""Craft metrics (Steven, 2026-11-03): pace and delivery, paragraphing, focus, repetition, measured the same way
for our editions and for the benchmark newsletters, so we can see whether our craft is improving against the field.

Measured here (code, every day, no model):
    pace_wpm         spoken words per minute of our audio (briefing and deep dive); the target band is 145-165
    para_words       median words per paragraph; long_para_pct: share of paragraphs over 110 words
    sent_words       mean words per sentence; long_sent_pct: share of sentences over 35 words (rambling proxy)
    repeats          distinct 4-word phrases used 3+ times (a phrase tic), per 1,000 words in repeat_per_1k
    filler_per_1k    stock filler ("it's worth noting", "in other words", "importantly", ...) per 1,000 words
    grade            Flesch-Kincaid grade level

Judged by the weekly critic (a model, same rubric for everyone, data/critic/<date>.json "craft"): delivery, paragraphs,
focus, clarity (walks the reader through the issue), repetition. Both feed the Quality page.

    measure(text)                 -> metrics for one text
    ours(root, cfg, day)          -> {"briefing": {...}, "script": {...}, "deepdive": {...}, "dd_script": {...}}
    field(root, days=14)          -> {source: medians} for the benchmark newsletters in our email archive
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

LONG_PARA, LONG_SENT = 110, 35
PACE = (145, 165)
FILLER = re.compile(r"\b(it'?s worth noting|it is worth noting|in other words|at the end of the day|importantly|notably|"
                    r"interestingly|needless to say|it goes without saying|the bottom line is|let'?s be clear|"
                    r"make no mistake|to be sure|in a nutshell|game[- ]changer|a lot of|basically|essentially|"
                    r"really|very)\b", re.I)
STOP = set("the a an and or of to in on for with at by from is are was were be been it its this that as but not "
           "we you they he she i our their his her them us".split())
# The benchmark newsletters we receive (names as they appear in newsletters.yaml / the archive).
BENCH = ("The AI Daily Brief (newsletter)", "The Rundown AI", "Superhuman AI", "AINews (Latent Space, swyx)",
         "Stratechery (Ben Thompson, free weekly)", "Don't Worry About the Vase (Zvi Mowshowitz)",
         "Exponential View (Azeem Azhar)", "The Batch (DeepLearning.AI)", "Import AI", "The Neuron", "TLDR AI")
OURS = "AI Briefing (us)"


def _clean(text: str) -> str:
    t = re.split(r"(?m)^#+\s*(Sources|Links|Further reading)\b", text or "")[0]   # source lists are not prose
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", "", t)                    # citation links ([4](url), [site via X](url))
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"^#+\s.*$", "", t, flags=re.M)                       # headings are not paragraphs
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", t)                    # dates in citations
    t = re.sub(r"[*_`>|]", "", t)
    return t


def paragraphs(text: str) -> list:
    out = []
    for p in re.split(r"\n\s*\n", _clean(text)):
        p = " ".join(p.split())
        if len(p.split()) >= 8 and not re.fullmatch(r"[-–•·\d. ]+.*", p[:2] + "x"):   # skip one-liners/rules
            out.append(p)
    return out


def sentences(text: str) -> list:
    t = " ".join(_clean(text).split())
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", t) if len(s.split()) >= 3]


def _syllables(w: str) -> int:
    w = re.sub(r"[^a-z]", "", w.lower())
    if not w:
        return 0
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def _title_words(text: str) -> set:
    m = re.search(r"(?m)^#\s+(.+)$", text or "")
    return set(re.findall(r"[a-z0-9']+", m.group(1).lower())) if m else set()


def repeats(text: str, n: int = 4, min_count: int = 3) -> list:
    """4-word phrases used 3+ times (content words, not the piece's own title: a deep dive may name its topic)."""
    words = re.findall(r"[a-z0-9']+", _clean(text).lower())
    grams = Counter(" ".join(words[i:i + n]) for i in range(len(words) - n + 1))
    title = _title_words(text)
    return sorted(((g, c) for g, c in grams.items()
                   if c >= min_count and sum(w not in STOP for w in g.split()) >= 2
                   and not all(w in title or w in STOP for w in g.split())), key=lambda x: -x[1])


def measure(text: str) -> dict:
    words = re.findall(r"[A-Za-z0-9'’-]+", _clean(text))
    nw = len(words)
    if nw < 50:
        return {"words": nw}
    paras = [len(p.split()) for p in paragraphs(text)] or [nw]
    sents = [len(s.split()) for s in sentences(text)] or [nw]
    syl = sum(_syllables(w) for w in words)
    rep = repeats(text)
    return {"words": nw,
            "para_words": round(statistics.median(paras)),
            "long_para_pct": round(100 * sum(p > LONG_PARA for p in paras) / len(paras)),
            "sent_words": round(statistics.mean(sents), 1),
            "long_sent_pct": round(100 * sum(s > LONG_SENT for s in sents) / len(sents)),
            "repeats": len(rep), "repeat_per_1k": round(1000 * len(rep) / nw, 2),
            "repeat_top": [f"{g} ×{c}" for g, c in rep[:5]],
            "filler_per_1k": round(1000 * len(FILLER.findall(_clean(text))) / nw, 1),
            "grade": round(0.39 * nw / len(sents) + 11.8 * syl / nw - 15.59, 1)}


def _read(p: Path) -> str:
    try:
        return p.read_text("utf-8")
    except OSError:
        return ""


def _audio(root: Path, day: str) -> dict:
    """Our briefing's audio minutes and spoken words for DAY, from the run log."""
    p = root / "data" / "runs.jsonl"
    best = {}
    for ln in _read(p).splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        a = (r.get("stages") or {}).get("audio") or {}
        if str(r.get("run_id", "")).startswith(day.replace("-", "")) and a.get("minutes") and a.get("words"):
            best = a
    return best


def _dd_record(root: Path, day: str) -> dict:
    rec = {}
    for ln in _read(root / "data" / "deepdives.jsonl").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("day") == day and r.get("status") == "published":
            rec = r
    return rec


def ours(root: Path, cfg: dict, day: str) -> dict:
    b = root / (cfg.get("paths") or {}).get("briefings", "briefings")
    out = {}
    md = _read(b / f"{day}.md")
    if md:
        out["briefing"] = measure(md)
    script = _read(b / f"{day}.spoken.txt")
    if script:
        m = measure(script)
        a = _audio(root, day)
        if a:
            m["pace_wpm"] = round(a["words"] / a["minutes"])
        out["script"] = m
    dds = _read(b / "deepdives" / f"{day}.spoken.txt") or _read(b / "deepdives" / f"{day}.script.md")
    if dds:
        m = measure(dds)
        rec = _dd_record(root, day)
        try:
            mins = float(rec.get("minutes") or 0)
        except (TypeError, ValueError):
            mins = 0
        if mins:
            m["pace_wpm"] = round(m["words"] / mins)
        out["deepdive"] = m
    return out


KEYS = ("para_words", "long_para_pct", "sent_words", "long_sent_pct", "repeat_per_1k", "filler_per_1k", "grade")


def _median(rows: list, k: str):
    v = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
    return round(statistics.median(v), 1) if v else None


def field(root: Path, days: int = 14, bench=BENCH) -> dict:
    """Medians per benchmark newsletter over its issues in our email archive (last DAYS days), plus our written
    edition over the same days, all measured by `measure`."""
    import datetime as dt
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    per = {}
    for d in sorted((root / "data" / "raw").glob("????-??-??")):
        if d.name < since:
            continue
        for ln in _read(d / "items.jsonl").splitlines():
            try:
                it = json.loads(ln)
            except ValueError:
                continue
            if it.get("source_kind") == "email" and it.get("person") in bench and (it.get("text") or ""):
                m = measure(it["text"])
                if m.get("words", 0) >= 150:
                    per.setdefault(it["person"], []).append(m)
    for f in sorted((root / "briefings").glob("????-??-??.md")):
        if f.stem >= since:
            m = measure(_read(f))
            if m.get("words", 0) >= 150:
                per.setdefault(OURS, []).append(m)
    return {name: {"issues": len(rows), **{k: _median(rows, k) for k in KEYS}} for name, rows in per.items()}


def checks(m: dict) -> list:
    """Scorecard checks for one day: [(key, label, passed, value)]."""
    out = []
    b, s, dd = m.get("briefing") or {}, m.get("script") or {}, m.get("deepdive") or {}
    if b.get("long_para_pct") is not None:
        out.append(("long_paras", f"Written paragraphs over {LONG_PARA} words", b["long_para_pct"] <= 10, b["long_para_pct"]))
    if b.get("long_sent_pct") is not None:
        out.append(("long_sents_written", f"Written sentences over {LONG_SENT} words (at most 10%)", b["long_sent_pct"] <= 10,
                    b["long_sent_pct"]))
    for name, x in (("briefing", b), ("podcast", s), ("deep dive", dd)):
        if x.get("repeats") is not None:
            out.append((f"repeats_{name.replace(' ', '')}", f"Repeated phrases in the {name} (4 words, 3+ times)",
                        x["repeats"] == 0, ", ".join(x.get("repeat_top") or []) or 0))
    for name, x in (("podcast", s), ("deep dive", dd)):
        if x.get("pace_wpm"):
            out.append((f"pace_{name.replace(' ', '')}", f"{name.capitalize()} pace {PACE[0]}-{PACE[1]} words a minute",
                        PACE[0] <= x["pace_wpm"] <= PACE[1], x["pace_wpm"]))
        if x.get("long_sent_pct") is not None:
            out.append((f"long_sents_{name.replace(' ', '')}", f"Spoken sentences over {LONG_SENT} words in the {name}",
                        x["long_sent_pct"] <= 5, x["long_sent_pct"]))
    return out
