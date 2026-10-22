"""Claim-to-source trace for the written edition (fact review 2026-10-18, P1-1). No model calls.

Every figure in the edition is looked up in the text of the sources the edition cites (the fetched items and the
articles the reader read). In the factual parts (day in brief, Top of mind, What happened, Worth knowing, In brief,
Recommended reading) a sentence whose figure appears in no source is cut: Steven's rule is "cut it and send".
In headlines it is flagged (a headline is not cut), and in the analysis (Evidence check, Our read, the other views,
Open questions) figures may be computed, so they are flagged only. The report feeds the scorecard.
"""
from __future__ import annotations

import re
from pathlib import Path

UNIT = r"(trillion|billion|million|thousand|bn|mn|tn|k|K|m|M|B|b|T)?(?![A-Za-z])"
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
DATEISH = re.compile(rf"(?:{MONTH}\s+\d{{1,2}}\b|\b\d{{1,2}}\s+{MONTH}|\bday\s+\d+\b|\b(?:Q[1-4]|H[12])\b|\b(?:Chapter|Section|Article|Title|Rule|Part|No\.)\s+\d+\b)", re.I)
FIG = re.compile(r"(?<![\w.$€£-])(~?[$€£]?)(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?" + UNIT + r"(%|\s?percent\b|x\b)?(?![\w-]*\d)")
MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
        "t": 1e12, "tn": 1e12, "trillion": 1e12}
FACTUAL = ("what happened", "day in brief", "top of mind", "worth knowing", "in brief", "recommended reading", "why it matters")
ANALYSIS = ("evidence check", "critical pass", "editor's view", "our read", "view", "open questions", "settled by", "agenda")


def values(text: str) -> list:
    """[(value, raw, kind)] for the figures in TEXT worth checking; kind is money, pct, mult or plain."""
    out = []
    text = DATEISH.sub(" ", text or "")                 # dates ("Oct 11", "from Tue Sep 29", "day 2") are not figures
    for m in FIG.finditer(text):
        cur, num, unit, suffix = m.group(1), m.group(2), (m.group(3) or ""), (m.group(4) or "").strip()
        v = float(num.replace(",", "")) * MULT.get(unit.lower(), 1)
        kind = ("money" if any(c in cur for c in "$€£") else "pct" if suffix in ("%", "percent") else "mult" if suffix == "x"
                else "plain")
        if kind == "plain" and (v < 10 or (1900 <= v <= 2100 and "." not in num)):      # small counts, years
            continue
        if v == 0:
            continue
        out.append((v, m.group(0).strip(), kind, float(num.replace(",", ""))))
    return out


def _bare(t: str) -> list:
    return [float(n.replace(",", "")) for n in re.findall(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?", t or "")]


def corpus_values(texts: list) -> dict:
    """Source figures by kind. Money also matches the difference of two amounts in the same source
    ('from $2.8B to $6.6B' supports '$3.8B')."""
    pool = {"money": [], "pct": [], "mult": [], "plain": []}
    for t in texts:
        figs = values(t)
        money = [v for v, _, k, _b in figs if k == "money"][:60]
        pool["money"] += money + [abs(a - b) for i, a in enumerate(money) for b in money[i + 1:]]
        pool["pct"] += [v for v, _, k, _b in figs if k == "pct"]
        pool["mult"] += [v for v, _, k, _b in figs if k == "mult"]
        bare = _bare(t)
        pool["plain"] += bare + [v for v, _, k, _b in figs]       # "23K" in a source supports "23,000"
        pool["money"] += [v for v, _, k, _b in figs if k == "plain"]   # "€" or "USD" written apart
        pool["pct"] += bare                               # "22 per cent", "22 percent", tables
        pool["mult"] += bare
        pool["money"] += [x * mul for x in bare for mul in (1, 1e3, 1e6, 1e9) if x < 1e6]   # "$9 billion" etc.
    return pool


def local_derived(figs: list) -> dict:
    """Figures computed from others in the same paragraph of the edition: ratios as % and multiples, differences."""
    money = [v for v, _, k, _b in figs if k == "money"]
    nums = [v for v, _, k, _b in figs if k in ("money", "plain", "pct")]
    pct, mult = [], []
    for i, a in enumerate(nums):
        for b in nums[i + 1:]:
            if a and b:
                pct += [a / b * 100, b / a * 100, abs(a - b) / min(a, b) * 100, abs(a - b) / max(a, b) * 100]
                mult += [a / b, b / a]
    return {"money": [abs(a - b) for i, a in enumerate(money) for b in money[i + 1:]], "pct": pct, "mult": mult,
            "plain": []}


def traced(v: float, kind: str, pool: dict, local: dict | None = None, base: float | None = None) -> bool:
    cands = pool.get(kind, []) + ((local or {}).get(kind, []))
    tol = max(abs(v) * (0.02 if kind in ("pct", "mult") else 0.015), 0.006)
    if any(abs(v - c) <= tol for c in cands):
        return True
    if base is not None and base != v:              # "120B" when a source says "120 billion" or "120B"
        return any(abs(base - c) <= max(abs(base) * 0.015, 0.006) for c in pool.get("plain", []))
    return False


def corpus(root: Path, ids: list) -> list:
    """Source texts for these item ids: the fetched items and any article the reader read for them."""
    from . import reader, stages
    raw = stages.raw_items(root, list(dict.fromkeys(ids)), days=30)
    texts = []
    for it in raw.values():
        texts.append(" ".join(str(it.get(k) or "") for k in ("title", "description", "text")))
        for u in (it.get("linked_url"), it.get("public_url"), it.get("url")):
            if u:
                p = reader._text_path(root, u)
                if p.exists():
                    texts.append(p.read_text("utf-8"))
    return texts


def _outlet(u: str) -> str:
    from .factsearch import _outlet as o
    return o(u)


def _plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\((?:https?://[^)]+)\)", r"\1", s)
    return re.sub(r"https?://\S+", "", s)


def check(md: str, texts: list, cut: bool = True, find=None) -> tuple:
    """-> (md, report{cut, flagged, checked, sourced}).

    find(raw, v, kind, base, sentence) -> {"url", "outlet", "how"} | None is tried before a figure is cut or flagged
    (pipeline/factsearch.Finder). A figure it finds stays; a web find gets a link after its sentence."""
    pool = corpus_values(texts)
    report = {"cut": [], "flagged": [], "checked": 0, "sourced": []}

    def look(raw, v, k, b, snt, where):
        hit = find(raw, v, k, b, snt) if find else None
        if hit:
            report["sourced"].append({"where": where or "text", "figure": raw, "url": hit["url"],
                                      "how": hit.get("how", ""), "text": snt.strip()[:90]})
        return hit
    section, out = "", []
    for line in md.split("\n"):
        if line.startswith("## "):
            section = line[3:].strip().lower()
            out.append(line)
            continue
        if line.startswith("# ") or line.startswith("*") and line.endswith("*") and "items analyzed" in line:
            out.append(line)
            continue
        label = (re.match(r"^\s*-\s*\*\*([^*]+?):?\*\*", line) or re.match(r"^\*\*([^*]+?)\.?\*\*", line))
        label = (label.group(1).lower() if label else "")
        where = label or section
        is_head = line.startswith("### ")
        analysis = any(a in where for a in ANALYSIS) and not any(f in where for f in FACTUAL)
        body = _plain(line)
        figs = values(body)
        if not figs:
            out.append(line)
            continue
        report["checked"] += len(figs)
        local = local_derived(figs)                       # computed from figures in the same paragraph
        missing = [raw for v, raw, k, b in figs if not traced(v, k, pool, local, b)]
        if not missing:
            out.append(line)
            continue
        if is_head or analysis or not cut:
            missing = [raw for v, raw, k, b in figs if not traced(v, k, pool, local, b)
                       and not look(raw, v, k, b, body, where)]
            if not missing:
                out.append(line)
                continue
            report["flagged"] += [f"{'headline' if is_head else where or 'text'}: {m} ({body.strip()[:80]})" for m in missing]
            out.append(line)
            continue
        # factual line: cut the sentences that carry an untraced figure, keep the rest of the line
        prefix = re.match(r"^(\s*-\s*\*\*[^*]+\*\*\s*|\s*-\s*|\*\*[^*]+\*\*\s*)", line)
        head = prefix.group(1) if prefix else ""
        rest = line[len(head):]
        sents = re.split(r"(?<=[.!?])\s+(?=[A-Z(\[*])", rest)
        keep = []
        for snt in sents:
            bad, cites = [], []
            for v, raw, k, b in values(_plain(snt)):
                if traced(v, k, pool, local, b):
                    continue
                hit = look(raw, v, k, b, _plain(snt), where)
                if hit:
                    if hit.get("how") == "web" and hit["url"] not in cites:
                        cites.append(hit["url"])
                else:
                    bad.append(raw)
            if not bad and cites:
                snt = snt.rstrip() + " " + " ".join(f"([{_outlet(u)}]({u}))" for u in cites)
            if bad:
                report["cut"].append(f"{where or 'text'}: {', '.join(bad)} ({_plain(snt).strip()[:90]})")
            else:
                keep.append(snt)
        kept = " ".join(keep).strip()
        if kept and not re.fullmatch(r"\(?\[?\d+\]?\(?[^)]*\)?\)?", kept):
            out.append(head + kept)
        elif head.strip().startswith("- **") and "what happened" in where:
            out.append(head + "Details in the source.")             # keep the story's structure
        # else: the whole bullet is dropped
    return "\n".join(out), report
