"""Number check for one edition: arithmetic the copy states, and the same figure given two ways.

From the 10-16 weekly review: "$155 vs $510 ($70 cheaper)" (it is $355), Astra at "$3.26" in one item and
"~$3.32" in another. Three checks, on the written edition:
  difference  a sentence with two amounts and "$X cheaper/less/more/saves" -> X must be their difference
  change      "from A to B" with a percent nearby -> the percent must match (B-A)/A
  near-twin   the same named thing given two amounts within 15% of each other but not equal
Different figures for the same company (revenue in two quarters) are far apart and are not flagged.
"""
from __future__ import annotations

import re

_AMT = r"~?\$\s?(\d+(?:,\d{3})*(?:\.\d+)?)\s?(k|K|m|M|mn|bn|B|b|billion|million|trillion|T|tn)?\b"
AMT = re.compile(_AMT)
MULT = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9, "t": 1e12,
        "tn": 1e12, "trillion": 1e12}
DIFF = re.compile(_AMT + r"\s+(?:cheaper|less|lower|more expensive|costlier|more|saved|savings?|higher)\b", re.I)
CHANGE = re.compile(r"from\s+" + _AMT + r"\s+to\s+" + _AMT, re.I)
PCT = re.compile(r"([+-]?\d+(?:\.\d+)?)\s?%")
ENTITY = re.compile(r"([A-Z][\w.-]*(?:\s[A-Z0-9][\w.-]*){0,2})(?:'s|’s)?\s*(?:\(|at|costs?|of|is|was|:)?\s*$")
_SKIP_ENT = {"The", "A", "An", "Our", "We", "It", "This", "That", "In", "On", "At", "For", "Q1", "Q2", "Q3", "Q4"}


def value(num: str, unit: str | None) -> float:
    return float(num.replace(",", "")) * MULT.get((unit or "").lower(), 1)


def _sentences(md: str) -> list:
    text = re.sub(r"\[([^\]]+)\]\((?:https?://[^)]+)\)", r"\1", md)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z*(])|\n+", text) if s.strip()]


def check(md: str) -> list:
    issues = []
    sents = _sentences(md)
    for s in sents:
        for m in DIFF.finditer(s):
            stated = value(m.group(1), m.group(2))
            others = [value(a, u) for a, u in AMT.findall(s[:m.start()])]
            if len(others) >= 2:
                a, b = others[-2], others[-1]
                real = abs(a - b)
                if real and abs(real - stated) / real > 0.05:
                    issues.append(f"difference: '{m.group(0)}' but the amounts differ by {_fmt(real)} ({s[:90]})")
        for m in CHANGE.finditer(s):
            a, b = value(m.group(1), m.group(2)), value(m.group(3), m.group(4))
            near = PCT.findall(s[m.end(): m.end() + 40]) or PCT.findall(s[max(0, m.start() - 40): m.start()])
            if a and near:
                real = (b - a) / a * 100
                said = float(near[0])
                if abs(abs(said) - abs(real)) > max(2.0, abs(real) * 0.1):
                    issues.append(f"change: from {_fmt(a)} to {_fmt(b)} is {real:+.0f}%, the copy says {near[0]}% ({s[:90]})")
    seen = {}
    for s in sents:
        for m in AMT.finditer(s):
            em = ENTITY.search(s[max(0, m.start() - 40): m.start()])
            if not em:
                continue
            ent = em.group(1).split()[-1].strip(".")
            if ent in _SKIP_ENT or len(ent) < 3:
                continue
            seen.setdefault(ent, []).append((value(m.group(1), m.group(2)), m.group(0).strip(), s[:90]))
    for ent, vals in seen.items():
        for i, (v1, t1, s1) in enumerate(vals):
            for v2, t2, s2 in vals[i + 1:]:
                if v1 and v2 and v1 != v2 and abs(v1 - v2) / max(v1, v2) <= 0.15:
                    issues.append(f"near-twin: {ent} is '{t1}' and '{t2}' ({s1[:50]} | {s2[:50]})")
    return list(dict.fromkeys(issues))[:10]


def fix(md: str) -> tuple:
    """Correct stated differences ("$70 cheaper" -> "$355 cheaper") where both amounts are in the same sentence.
    -> (md, fixes). Changes and near-twins are only flagged: the right value needs the source."""
    fixes = []

    def one_line(line: str) -> str:
        out = line
        for m in reversed(list(DIFF.finditer(line))):
            others = [value(a, u) for a, u in AMT.findall(line[:m.start()])]
            stated = value(m.group(1), m.group(2))
            if len(others) >= 2:
                real = abs(others[-2] - others[-1])
                if real and abs(real - stated) / real > 0.05 and not m.group(2):      # plain dollars only
                    new = f"${real:,.0f}" if real >= 100 else f"${real:,.2f}"
                    start = m.start() + m.group(0).find("$")
                    end = m.start() + m.group(0).find(m.group(1)) + len(m.group(1))
                    out = out[:start] + new + out[end:]
                    fixes.append(f"{m.group(0).split()[0]} -> {new}")
        return out
    return "\n".join(one_line(ln) for ln in md.split("\n")), fixes


def _fmt(v: float) -> str:
    for d, u in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= d:
            return f"${v / d:.3g}{u}"
    return f"${v:,.2f}".rstrip("0").rstrip(".")
