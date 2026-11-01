"""One chart a day (quality review, 2026-10-31: no charts or images in the edition). After the edition is written,
one Must read whose sources carry a comparable set of numbers gets a small bar chart: the model proposes it, code
checks that every value appears in that story's own source text, and the chart is drawn as plain HTML bars (it
works in the email and on the site; no images). No chart is better than a wrong one: any doubt -> no chart.

    data/charts/<day>.json  {"story": n, "title", "unit", "source", "bars": [{"label", "value"}]}
"""
from __future__ import annotations

import html as htmllib
import json
import re
from pathlib import Path

DIR = "data/charts"
PROMPT = """From the stories below, pick the ONE whose sources give 3 to 6 numbers that compare well as bars in the
same unit (amounts raised or spent, prices, shares, scores on one benchmark, counts). Use only numbers written in
that story's text, exactly as given. If no story has such a set, return {"story": 0}.

Return ONLY JSON: {"story": <its number>, "title": "the point of the chart in at most 10 words",
"unit": "$B | $M | % | x | a short unit word", "bars": [{"label": "at most 4 words", "value": <number>}]}

STORIES:
"""


def _num(v) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def found(value, text: str) -> bool:
    """The value is written in the text (16.3 matches "$16.3B", "16.3 billion"; 1200 matches "1,200")."""
    n = _num(value)
    plain = text.replace(",", "")
    return bool(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", plain))


def check(c: dict, texts: dict) -> str:
    """'' when the chart is usable, else why not."""
    try:
        n = int(str(c.get("story", 0)).strip().lstrip("#") or 0)   # models return 2, "2" or "#2"
    except ValueError:
        return f"story is not a number ({str(c.get('story'))[:20]})"
    bars = c.get("bars") or []
    if not n:
        return "no story with comparable numbers"
    if n not in texts:
        return f"story {n} is not a Must read"
    if not 3 <= len(bars) <= 6:
        return "needs 3-6 bars"
    try:
        vals = [float(b["value"]) for b in bars]
    except (KeyError, TypeError, ValueError):
        return "a value is not a number"
    if any(v < 0 for v in vals) or max(vals) <= 0:
        return "negative or empty values"
    missing = [b["label"] for b in bars if not found(b["value"], texts[n])]
    return f"not in the story's sources: {', '.join(missing)}" if missing else ""


def make(root: Path, day: str, must: list, texts: dict, llm, log=print) -> dict | None:
    """must: [{n, headline, what}] ; texts: {n: the story's source text}. Saves and returns the chart, or None."""
    from . import stages
    block = "\n".join(f"{m['n']}. {m['headline']}: {m['what']}\n   sources: {texts.get(m['n'], '')[:3000]}" for m in must)
    try:
        c = stages._ask(llm, "You are a careful data editor.", PROMPT + block, 600) or {}
    except Exception as e:  # noqa: BLE001
        log(f"chart: skipped ({e})"[:160])
        return None
    why = check(c, texts)
    if why:
        log(f"chart: none today ({why})")
        return None
    c = {"story": int(str(c["story"]).strip().lstrip("#")), "title": str(c.get("title", ""))[:90], "unit": str(c.get("unit", ""))[:12],
         "bars": [{"label": str(b["label"])[:40], "value": float(b["value"])} for b in c["bars"]]}
    p = root / DIR / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1) + "\n", "utf-8")
    log(f"chart: story {c['story']}, {c['title']} ({len(c['bars'])} bars)")
    return c


def load(root: Path, day: str) -> dict | None:
    try:
        return json.loads((Path(root) / DIR / f"{day}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _fmt(v: float, unit: str) -> str:
    n = _num(v)
    if unit.startswith("$"):
        return f"${n}{unit[1:]}"
    return f"{n}%" if unit == "%" else f"{n}{unit if unit == 'x' else ' ' + unit if unit else ''}"


def html(c: dict, bar: str = "#3e7e8a", ink: str = "#14272b", muted: str = "#5b6d71") -> str:
    """Email-safe bars: a table per row, widths in percent of the largest value."""
    top = max(b["value"] for b in c["bars"]) or 1
    e = htmllib.escape
    rows = "".join(
        f'<tr><td style="padding:3px 8px 3px 0;font-size:13px;color:{ink};white-space:nowrap">{e(b["label"])}</td>'
        f'<td style="padding:3px 0;width:100%"><div style="background:{bar};height:14px;border-radius:3px;'
        f'width:{max(2, round(100 * b["value"] / top))}%"></div></td>'
        f'<td style="padding:3px 0 3px 8px;font-size:13px;color:{ink};white-space:nowrap">{e(_fmt(b["value"], c.get("unit", "")))}</td></tr>'
        for b in c["bars"])
    return (f'<div class="chart" style="margin:10px 0 14px"><div style="font-size:13px;font-weight:600;color:{ink};margin:0 0 6px">'
            f'{e(c.get("title", ""))}</div><table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">'
            f'{rows}</table><div style="font-size:11px;color:{muted};margin-top:4px">Figures as reported in this story\'s sources.</div></div>')
