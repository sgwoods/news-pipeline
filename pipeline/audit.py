"""The daily accuracy audit (critic 2026-10-24, #10D; Steven 2026-10-27).

After the edition ships, about five of its factual claims (sentences with a figure or a named fact, from Must read
"What happened" lines first) are checked against the story's own source texts by a model, claim by claim:
supported, partly, not found, or contradicted. The consistency checks' flags for the day (claims the edition's own
body or the last two weeks contradict) are counted as contradictions. The result is saved in data/audit/DAY.json;
a claim that is contradicted or only partly right sends Steven one alert, so he can decide on a correction. The
public accuracy page shows the daily counts and every correction (pipeline/shipped.py), never the model's notes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import factcheck
from .stages import _ask, _one_line, prompt

DIR = "data/audit"
N_CLAIMS = 5
_FIG = re.compile(r"[$€£]\s?\d|\d[\d,.]*\s?(?:%|percent|[BMK]\b|bn\b|billion|million|trillion)|\b(?:19|20)\d\d\b|\b\d{2,}\b")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
VERDICTS = ("supported", "partly", "not found", "contradicted")


def _plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\s*\((?:[A-Z][^()]{1,40}(?:,\s*)?)+\)", "", s)          # "(Crunchbase News, Latent Space)"
    return s.replace("**", "").replace("*", "").strip()


_ACRO = re.compile(r"\b[A-Z][A-Z0-9&]{2,6}s?\b")


def untraced_names(sent: str, corpus: str) -> list:
    """Acronyms in SENT that none of its sources contain (2026-10-30: "CDIC" for the Government of Canada)."""
    return [a for a in dict.fromkeys(_ACRO.findall(sent)) if a.rstrip("s") not in corpus and a not in corpus]


def claims(md: str, stories: list, n: int = N_CLAIMS, every: bool = False, corpus=None) -> list:
    """[{n, text, story, ids, line}]: sentences with a figure from Must read What happened lines, then Worth knowing.
    every=True (the pre-send check): every sentence of those lines and the top section, up to n, two per story lifted
    to six, with any sentence naming something its sources don't (corpus(ids) -> text) first."""
    by_head = {s.get("headline", ""): s for s in stories}
    out, seen = [], set()
    must = md.split("## Must read", 1)[1].split("\n## ", 1)[0] if "## Must read" in md else ""
    blocks = re.split(r"(?m)^### \d+\. ", must)[1:]
    pool, order = [], []
    for b in blocks:
        head = b.splitlines()[0].strip()
        s = by_head.get(head) or next((x for k, x in by_head.items() if k[:40] == head[:40]), {})
        order.append((head, s))
        m = re.search(r"- \*\*What happened:\*\* (.+)", b)
        if m:
            for sent in _SENT.split(_plain(m.group(1))):
                pool.append((0 if _FIG.search(sent) else 1, head, s, sent, m.group(0)))
    worth = md.split("## Worth knowing", 1)[1].split("\n## ", 1)[0] if "## Worth knowing" in md else ""
    for ln in worth.splitlines():
        m = re.match(r"- \*\*\d+\. (.+?)\*\* (.+)", ln)
        if m:
            head = m.group(1).rstrip(".")
            s = by_head.get(head) or next((x for k, x in by_head.items() if k[:40] == head[:40]), {})
            for sent in _SENT.split(_plain(m.group(2)))[:None if every else 1]:
                pool.append((2 if _FIG.search(sent) else 3, head, s, sent, ln))
    if every:                                    # the top section: each line cites its Must read story as [k](url)
        for name in ("Today in 30 seconds", "Top of mind"):
            if f"## {name}" in md:
                for ln in md.split(f"## {name}", 1)[1].split("\n## ", 1)[0].splitlines():
                    r = re.search(r"\[(\d+)\]\(https?://", ln)
                    if ln.startswith("- ") and r and 0 < int(r.group(1)) <= len(order):
                        head, s = order[int(r.group(1)) - 1]
                        for sent in _SENT.split(_plain(re.sub(r"^- \*\*.+?\*\*\s*", "", ln))):
                            pool.append((1, head, s, sent, ln))
                break
    if every and corpus:
        pool = [(-1 if untraced_names(x[3], " ".join(corpus(x[2].get("ids") or []))) else x[0], *x[1:]) for x in pool]
    used_story = {}
    for pri, head, s, sent, line in sorted(pool, key=lambda x: x[0]):
        sent = sent.strip()
        if len(sent.split()) < 6 or sent in seen or not s.get("ids") or used_story.get(head, 0) >= (6 if every else 2):
            continue
        seen.add(sent)
        used_story[head] = used_story.get(head, 0) + 1
        out.append({"n": len(out) + 1, "text": sent, "story": head, "ids": s["ids"], "line": line})
        if len(out) >= n:
            break
    return out


def _excerpt(texts: list, claim: str, limit: int = 4800) -> str:
    """The parts of the source texts that share the claim's figures and names, best matches first (v0.2.33: ranked,
    and twice the room, so a detail deep in a long source still reaches the check)."""
    keys = {w.lower() for w in re.findall(r"[A-Z][\w.-]+|\d[\d,.]*", claim) if len(w) > 1}
    scored = []
    for t in texts:
        for i, para in enumerate(re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", t))):
            low = para.lower()
            hits = sum(1 for k in keys if k in low)
            if hits >= 2 or (hits == 1 and len(keys) <= 2):
                scored.append((-hits, len(scored), para[:400]))
    parts = [p for _h, _i, p in sorted(scored)]
    txt = " … ".join(dict.fromkeys(parts))
    return txt[:limit] if txt else " ".join(texts)[:limit]


def _stories(root: Path, day: str) -> list:
    try:
        rows = [json.loads(x) for x in (root / "data" / "stories" / f"{day}.jsonl").read_text("utf-8").splitlines() if x.strip()]
        return rows[-1]["stories"] if rows else []
    except (OSError, ValueError, KeyError):
        return []


def contradictions(root: Path, day: str) -> list:
    from . import consistency
    try:
        rep = consistency.audit(root, [day], log=lambda *a: None)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for d in rep.get("days", []):
        out += [f"against the last two weeks: {x}" for x in d.get("cross_day", [])]
        out += [f"against its own body: {x}" for x in d.get("header", [])]
    return [str(x)[:200] for x in out]


def run(root: Path, day: str, llm, system: str, log=print) -> dict:
    root = Path(root)
    md = (root / "briefings" / f"{day}.md").read_text("utf-8")
    cl = claims(md, _stories(root, day))
    checks, version = _check(root, cl, llm, system, log)
    rows = []
    for c in cl:
        r = {"n": c["n"], "claim": c["text"], "story": c["story"], "sources": c.get("sources", 0),
             **checks.get(c["n"], {"verdict": "unchecked", "why": "", "source": ""})}
        rows.append(r)
    con = contradictions(root, day)
    res = {"day": day, "prompt": version, "model": getattr(llm, "label", ""), "claims": rows,
           "checked": sum(1 for r in rows if r["verdict"] != "unchecked"),
           "supported": sum(1 for r in rows if r["verdict"] == "supported"),
           "issues": [r for r in rows if r["verdict"] in ("partly", "contradicted")],
           "contradictions": con}
    p = root / DIR / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    return res


def _check_each(root: Path, cl: list, judge, llm, system: str, log=print) -> dict:
    """The second judge, one claim per call (a local model answers a long batch with only its first verdict); a claim
    it leaves unanswered goes to the first model, so a fix is never applied unchecked."""
    out = {}
    for c in cl:
        r, _ = _check(root, [{**c, "n": 1}], judge, system, log)
        if 1 in r:
            out[c["n"]] = {**r[1], "by": getattr(judge, "label", "")}
    missing = [c for c in cl if c["n"] not in out]
    if missing and judge is not llm:
        r, _ = _check(root, missing, llm, system, log)
        for c in missing:
            if c["n"] in r:
                out[c["n"]] = {**r[c["n"]], "by": getattr(llm, "label", "")}
    return out


def _check(root: Path, cl: list, llm, system: str, log=print, limit: int = 4800) -> tuple:
    """({n: {verdict, why, source}}, prompt version): the model's verdict on each claim against its own sources
    (plus any pages a claim carries in "found": [{outlet, url, text}])."""
    tmpl, version = prompt("audit")
    blocks = []
    for c in cl:
        texts = (list(c["texts"]) if "texts" in c else factcheck.corpus(root, c["ids"])) + \
            [f"({f['outlet']}) {f['text']}" for f in c.get("found") or []]
        c["sources"] = len(texts)
        c["excerpt"] = _excerpt(texts, c["text"], limit)
        names = untraced_names(c["text"], " ".join(texts))
        blocks.append(f"CLAIM {c['n']} (story: {c['story']}): {c['text']}\nSOURCE EXCERPTS: {c['excerpt']}"
                      + (f"\nNOT IN ANY SOURCE: {', '.join(names)}" if names else ""))
    checks = {}
    if cl:
        try:
            out = _ask(llm, system, tmpl.replace("{{claims}}", "\n\n".join(blocks)), 300 + 120 * len(cl))
            for x in out.get("checks") or []:
                v = str(x.get("verdict", "")).lower().strip()
                if v in VERDICTS and str(x.get("n", "")).isdigit():
                    checks[int(x["n"])] = {"verdict": v, "why": _one_line(str(x.get("why") or ""))[:240],
                                           "source": _one_line(str(x.get("source") or ""))[:80]}
        except Exception as e:  # noqa: BLE001
            log(f"audit: model check failed: {type(e).__name__}: {e}"[:200])
    return checks, version


# ---- the pre-send check (Steven, 2026-10-30: "do the fact check BEFORE the email is sent") ----
PRESEND_N = 24
FIX = ("partly", "contradicted")
WIDE = 12000             # a "not found" claim is looked at again with this much of its sources
_URL = re.compile(r"\]\((https?://[^)\s]+)\)")


def _label(line: str) -> str:
    return line[:line.find("**", 3) + 2] if line.startswith("- **") and line.find("**", 3) > 0 else "- "


def _fixed_line(old: str, new: str, may_add=()) -> bool:
    """A rewrite is taken only when it stays one bullet line with the same label, keeps its links, adds at most one
    link and only from MAY_ADD (live pages found for this claim), and isn't much longer."""
    if not new or "\n" in new.strip() or not new.startswith(_label(old)):
        return False
    before, after = set(_URL.findall(old)), set(_URL.findall(new))
    added = after - before
    if not before <= after or len(added) > 1 or not added <= set(may_add):
        return False
    return len(new) <= len(old) * 1.4 + 120


def _add_source(md: str, line: str, page: dict) -> str:
    """The page a rewrite now cites joins the Sources line of the Must read block holding LINE."""
    i = md.find(line)
    if i < 0:
        return md
    j = md.find("- **Sources:**", i)
    nxt = md.find("\n### ", i)
    if j < 0 or (0 <= nxt < j) or page["url"] in md[j: md.find("\n", j)]:
        return md
    k = md.find("\n", j)
    k = len(md) if k < 0 else k
    return md[:k] + f" · [{page['outlet']}: {page.get('title') or 'source'}]({page['url']})" + md[k:]


def presend(root: Path, day: str, llm, system: str, log=print, stamp=None, finder=None, judge=None) -> dict:
    """Before the audio, the takes email and the send: check every factual claim of DAY's draft against its sources.
    - "not found" -> looked at again with far more of its sources (WIDE);
    - still not right -> a search for a live page that has it (government and regulators first; factsearch);
    - partly right or contradicted -> the line rewritten to what the sources (and any found page, which it may cite
      with one new link, added to the story's Sources too) say; then checked again by JUDGE, a second model
      (llm.stages.judge2, the local model by default), so the model that rewrote a line doesn't grade it.
    What still doesn't hold is listed for Steven in the takes email. Saves data/audit/DAY-presend.json and rewrites
    briefings/DAY.md in place (it hasn't shipped)."""
    import datetime as dt
    root = Path(root)
    judge = judge or llm
    p = root / "briefings" / f"{day}.md"
    md = p.read_text("utf-8")
    cache = {}

    def corp(ids):
        k = tuple(ids)
        if k not in cache:
            cache[k] = factcheck.corpus(root, list(ids))
        return cache[k]
    cl = claims(md, _stories(root, day), n=PRESEND_N, every=True, corpus=corp)
    checks, version = _check(root, cl, llm, system, log)
    widened = [c for c in cl if checks.get(c["n"], {}).get("verdict") == "not found"]
    if widened:                                  # 1. more of the cited sources
        wc, _ = _check(root, widened, llm, system, log, limit=WIDE)
        for c in widened:
            if c["n"] in wc:
                checks[c["n"]] = {**wc[c["n"]], "widened": True}
    searched = 0
    if finder is not None:                       # 2. a live page that has what the cited sources don't
        from . import factsearch
        for c in [c for c in cl if checks.get(c["n"], {}).get("verdict") in FIX + ("not found",)]:
            own = set(_URL.findall(c["line"]))
            c["found"] = factsearch.pages_for(finder, c["text"], skip=own)
            searched += 1
            if c["found"]:
                fc, _ = _check(root, [c], llm, system, log)
                if c["n"] in fc:
                    checks[c["n"]] = {**fc[c["n"]], "searched": True}
    bad = [c for c in cl if checks.get(c["n"], {}).get("verdict") in FIX
           or (checks.get(c["n"], {}).get("verdict") == "not found" and c.get("found"))]
    fixes, held = [], []
    tmpl, _ = prompt("audit_fix")
    by_line = {}
    for c in bad:
        by_line.setdefault(c["line"], []).append(c)
    for line, cs in by_line.items():
        if line not in md:
            continue
        found = [f for c in cs for f in c.get("found") or []]
        found = list({f["url"]: f for f in found}.values())
        cited = "\n\n".join(dict.fromkeys(_excerpt(corp(c["ids"]), c["text"], WIDE // 2) for c in cs))[:7000]
        extra = "\n\n".join(f"[{f['outlet']}]({f['url']})" + (" (primary source)" if f.get("primary") else "")
                             + f": {_excerpt([f['text']], cs[0]['text'], 2000)}" for f in found) or "(none)"
        ask = (tmpl.replace("{{line}}", line).replace("{{problems}}", "\n".join(
            f"- \"{c['text']}\": {checks[c['n']]['verdict']}: {checks[c['n']]['why']}" for c in cs))
            .replace("{{excerpts}}", cited).replace("{{found}}", extra))
        try:
            new = str((_ask(llm, system, ask, 900) or {}).get("line") or "").strip()
        except Exception as e:  # noqa: BLE001
            log(f"pre-send fix failed: {type(e).__name__}: {e}"[:200])
            new = ""
        if not _fixed_line(line, new, [f["url"] for f in found]):
            held += [{"claim": c["text"], **checks[c["n"]]} for c in cs]
            continue
        md = md.replace(line, new, 1)
        added = [f for f in found if f["url"] in set(_URL.findall(new)) - set(_URL.findall(line))]
        if any(not supports_text(f["text"], _plain(new)) for f in added):     # a new link must carry the fact itself
            held += [{"claim": c["text"], **checks[c["n"]], "why": "the page it cited doesn't carry the fix"} for c in cs]
            md = md.replace(new, line, 1) if new in md else md
            continue
        for f in added:
            md = _add_source(md, new, f)
        fixes.append({"before": line, "after": new, "why": "; ".join(checks[c["n"]]["why"] for c in cs)[:400],
                      "added_source": [{"url": f["url"], "outlet": f["outlet"]} for f in added]})
    if fixes:                                    # 3. the rewritten lines, checked again by the second judge
        again = []
        for i, f in enumerate(fixes):
            c0 = next(c for c in bad if c["line"] == f["before"])
            for sent in _SENT.split(_plain(re.sub(r"^- \*\*.+?\*\*\s*", "", f["after"]))):
                if len(sent.split()) >= 6:
                    again.append({**c0, "n": len(again) + 1, "text": sent.strip(), "fix": i})
        rc = _check_each(root, again, judge, llm, system, log)
        for a in again:
            v = rc.get(a["n"], {}).get("verdict", "unchecked")
            fixes[a["fix"]].setdefault("recheck", []).append(v)
        kept = []
        for f in fixes:                          # a rewrite stays only if every sentence of it re-checks as supported
            if all(v == "supported" for v in f.get("recheck") or ["unchecked"]):
                kept.append(f)
                continue
            md = md.replace(f["after"], f["before"], 1)
            for u in [a["url"] for a in f.get("added_source") or []]:
                md = re.sub(r" · \[[^\]]*\]\(" + re.escape(u) + r"\)", "", md, count=1)
            held.append({"claim": _plain(f["before"])[:300], "verdict": "rewrite not confirmed",
                         "why": f"second check: {', '.join(f.get('recheck') or [])}; proposed: {_plain(f['after'])[:200]}"})
        fixes = kept
    for c in cl:                                 # not found anywhere: for Steven, not cut (names, not figures)
        if checks.get(c["n"], {}).get("verdict") == "not found" and not c.get("found"):
            held.append({"claim": c["text"], **checks[c["n"]]})
    if md != p.read_text("utf-8"):
        p.write_text(md, "utf-8")
    at = (stamp or dt.datetime.now)().isoformat(timespec="seconds")
    res = {"day": day, "at": at, "prompt": version, "model": getattr(llm, "label", ""),
           "judge": getattr(judge, "label", ""), "checked": len(checks),
           "supported": sum(1 for v in checks.values() if v["verdict"] == "supported"),
           "widened": len(widened), "searched": searched, "flagged": len(bad), "fixes": fixes, "held": held}
    out = root / DIR / f"{day}-presend.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    log(f"Pre-send fact check: {res['checked']} claims, {len(fixes)} line(s) rewritten "
        f"({sum(len(f['added_source']) for f in fixes)} with a new source), {len(held)} for Steven")
    return res


# ---- the same check on the deep dive's spoken sections (Steven, 2026-10-30: "lets do the deep dive now") ----
DD_FACTUAL = ("why_today", "plainly", "evidence", "readings")     # so_what / watch are analysis, not rewritten
DD_N = 24


def dd_claims(sections: list, corpus: list, n: int = DD_N) -> list:
    """[{n, text, story (section id), texts}]: sentences of the factual sections, those naming something no source
    has first, then those with a figure, then the rest; each section at most 8."""
    hay = " ".join(corpus)
    pool = []
    for k, (sid, text) in enumerate(sections):
        base = sid.split("~", 1)[0]
        if base not in DD_FACTUAL:
            continue
        for sent in _SENT.split(text):
            sent = sent.strip()
            if len(sent.split()) < 6:
                continue
            pri = 0 if untraced_names(sent, hay) else 1 if _FIG.search(sent) else 2 if re.search(r"\b[A-Z][a-z]+\b.*\b[A-Z]", sent) else 3
            pool.append((pri, sid, sent, k))
    out, per = [], {}
    for pri, sid, sent, k in sorted(pool, key=lambda x: x[0]):
        if per.get(sid, 0) >= 8 or pri == 3:
            continue
        per[sid] = per.get(sid, 0) + 1
        out.append({"n": len(out) + 1, "text": sent, "story": sid, "turn": k, "ids": [], "texts": corpus, "line": sent})
        if len(out) >= n:
            break
    return out


def check_sections(root: Path, day: str, sections: list, corpus: list, llm, system: str, log=print, judge=None,
                   finder=None, stamp=None, ok_sentence=None, name: str = "deepdive") -> tuple:
    """The deep dive's version of presend, before it is recorded: -> (sections, report, found pages to add as
    sources). Sentences are spoken text, so a rewrite stays one plain sentence (no links, no markup; ok_sentence
    decides, e.g. the audio rules), and a page found by search joins the deep dive's Sources list instead of
    getting an inline link. Saves data/audit/DAY-deepdive.json."""
    import datetime as dt
    judge = judge or llm
    cl = dd_claims(sections, corpus)
    checks, version = _check(root, cl, llm, system, log)
    widened = [c for c in cl if checks.get(c["n"], {}).get("verdict") == "not found"]
    if widened:
        wc, _ = _check(root, widened, llm, system, log, limit=WIDE)
        for c in widened:
            if c["n"] in wc:
                checks[c["n"]] = {**wc[c["n"]], "widened": True}
    searched = 0
    if finder is not None:
        from . import factsearch
        for c in [c for c in cl if checks.get(c["n"], {}).get("verdict") in FIX + ("not found",)]:
            c["found"] = factsearch.pages_for(finder, c["text"])
            searched += 1
            if c["found"]:
                fc, _ = _check(root, [c], llm, system, log)
                if c["n"] in fc:
                    checks[c["n"]] = {**fc[c["n"]], "searched": True}
    bad = [c for c in cl if checks.get(c["n"], {}).get("verdict") in FIX
           or (checks.get(c["n"], {}).get("verdict") == "not found" and c.get("found"))]
    tmpl, _ = prompt("audit_fix_spoken")
    fixes, held, used = [], [], {}
    text_of = [t for _sid, t in sections]        # by turn: a two-voice script repeats section ids (v0.2.36)
    for c in bad:
        found = c.get("found") or []
        ask = (tmpl.replace("{{sentence}}", c["text"])
               .replace("{{problem}}", f"{checks[c['n']]['verdict']}: {checks[c['n']]['why']}")
               .replace("{{excerpts}}", _excerpt(corpus, c["text"], WIDE // 2))
               .replace("{{found}}", "\n\n".join(f"{f['outlet']}" + (" (primary source)" if f.get("primary") else "")
                                                  + f": {_excerpt([f['text']], c['text'], 2000)}" for f in found) or "(none)"))
        try:
            new = str((_ask(llm, system, ask, 500) or {}).get("sentence") or "").strip()
        except Exception as e:  # noqa: BLE001
            log(f"deep-dive fix failed: {type(e).__name__}: {e}"[:200])
            new = ""
        good = bool(new) and "\n" not in new and not re.search(r"https?://|\[|\]|\*|#", new) \
            and len(new) <= len(c["text"]) * 1.5 + 60 and (ok_sentence is None or ok_sentence(new))
        sid, k = c["story"], c["turn"]
        if not good or c["text"] not in text_of[k]:
            held.append({"claim": c["text"], "section": sid, **checks[c["n"]]})
            continue
        text_of[k] = text_of[k].replace(c["text"], new, 1)
        fixes.append({"turn": k, "section": sid, "before": c["text"], "after": new, "why": checks[c["n"]]["why"][:300],
                      "found": [f["url"] for f in found]})
    if fixes:                                    # checked again by the second judge, with any found pages
        extra = [f"({f['outlet']}) {f['text']}" for c in bad for f in c.get("found") or []]
        again = [{"n": i + 1, "text": f["after"], "story": f["section"], "ids": [], "texts": corpus + extra}
                 for i, f in enumerate(fixes)]
        rc = _check_each(root, again, judge, llm, system, log)
        for a, f in zip(again, fixes):
            f["recheck"] = rc.get(a["n"], {}).get("verdict", "unchecked")
        kept = []
        for f in fixes:                          # a rewrite stays only if the second check confirms it
            if f["recheck"] == "supported":
                kept.append(f)
                continue
            text_of[f["turn"]] = text_of[f["turn"]].replace(f["after"], f["before"], 1)
            held.append({"claim": f["before"], "section": f["section"], "verdict": "rewrite not confirmed",
                         "why": f"second check: {f['recheck']}; proposed: {f['after'][:200]}"})
        fixes = kept
        pages = {x["url"]: x for c in bad for x in c.get("found") or []}
        for f in fixes:                          # a found page joins the Sources only when the fix checked out AND
            if f["recheck"] == "supported":      # the page itself carries words of the fixed sentence (10-31: an
                for u in f["found"]:             # unrelated TechCrunch story was added because the fix was supported
                    if supports_text(pages[u]["text"], f["after"]):   # by the dive's own sources)
                        used.setdefault(u, pages[u])
    for c in cl:
        if checks.get(c["n"], {}).get("verdict") == "not found" and not c.get("found"):
            held.append({"claim": c["text"], "section": c["story"], **checks[c["n"]]})
    res = {"day": day, "at": (stamp or dt.datetime.now)().isoformat(timespec="seconds"), "prompt": version,
           "model": getattr(llm, "label", ""), "judge": getattr(judge, "label", ""), "checked": len(checks),
           "supported": sum(1 for v in checks.values() if v["verdict"] == "supported"), "widened": len(widened),
           "searched": searched, "flagged": len(bad), "fixes": fixes, "held": held,
           "added_sources": [{"url": u, "outlet": f["outlet"]} for u, f in used.items()]}
    out = Path(root) / DIR / f"{day}-{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    log(f"Deep-dive fact check: {res['checked']} sentences, {len(fixes)} rewritten, "
        f"{len(used)} new source(s), {len(held)} for Steven")
    return [(sid, text_of[k]) for k, (sid, _t) in enumerate(sections)], res, list(used.values())


def supports_text(page: str, sentence: str, n: int = 5) -> bool:
    """The page shares a run of N words with the sentence (outlet names and stopwords aside), or its quotation."""
    q = re.findall(r'"([^"]{12,})"', sentence)
    low = " ".join(re.findall(r"[a-z0-9$%.]+", (page or "").lower()))
    if any(" ".join(re.findall(r"[a-z0-9$%.]+", x.lower())) in low for x in q):
        return True
    w = re.findall(r"[a-z0-9$%.]+", sentence.lower())
    grams = {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    stop = {"according to the", "the new york times", "reported the case"}
    return any(g in low and not any(st in g for st in stop) for g in grams)


def load_deepdive_check(root: Path, day: str) -> dict:
    try:
        return json.loads((Path(root) / DIR / f"{day}-deepdive.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def load_presend(root: Path, day: str) -> dict:
    try:
        return json.loads((Path(root) / DIR / f"{day}-presend.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def load_all(root: Path) -> list:
    out = []
    for p in sorted((Path(root) / DIR).glob("????-??-??.json")):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except (OSError, ValueError):
            pass
    return out


def summary(res: dict) -> str:
    return (f"{res['checked']} claims checked, {res['supported']} supported, {len(res['issues'])} to look at, "
            f"{len(res['contradictions'])} contradiction flag(s)")
