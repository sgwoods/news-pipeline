"""Running trend charts (Steven, 2026-10-31): our scores against the top shows over time, and our own edition
metrics day by day. Drawn as inline SVG for the dashboard's Quality page; the weekly critic keeps the series going
(each Saturday adds data/critic/<date>.json), and the daily scorecard adds a point per edition.

    field(root, dim)      -> {show: [(date, value)]}  "overall" or a rubric dimension, from data/critic/
    daily(root, cfg, n)   -> [{"day", metric: value}] our last n editions (quality scorecard, corrections, takes)
    svg_lines(series, ...) -> an <svg> line chart, our line in the brand teal, everyone else grey
"""
from __future__ import annotations

import html as htmllib
import json
from pathlib import Path

from . import critic

DAILY = [("checks_pct", "Scorecard checks passed", "%"), ("words", "Written words", ""),
         ("must_grounded", "Must reads with a primary source or report", "%"), ("corrections", "Corrections after send", ""),
         ("takes", "Steven's takes published", ""), ("rating_readers", "Reader rating (1-5)", ""),
         # craft (2026-11-03, pipeline/craft.py): the target band or limit is in each title
         ("pace_podcast", "Podcast pace, words a minute (145-165)", ""), ("pace_deepdive", "Deep-dive pace, words a minute (145-165)", ""),
         ("long_sents", "Written sentences over 35 words (≤10%)", "%"), ("repeats", "Repeated 4-word phrases, all three pieces (0)", "")]


def field(root: Path, dim: str = "overall") -> dict:
    out = {}
    for w in critic.history(root):
        for s in w.get("shows", []):
            v = s.get("overall") if dim == "overall" else ((s.get("scores") or {}).get(dim) or (s.get("craft") or {}).get(dim))
            if v is not None:
                out.setdefault(s["name"], []).append((w["date"], float(v)))
        o = w.get("ours") or {}
        v = o.get("overall") if dim == "overall" else ((o.get("scores") or {}).get(dim) or (o.get("craft") or {}).get(dim))
        if v is not None:
            out.setdefault(critic.OURS, []).append((w["date"], float(v)))
    return out


def _corrections(root: Path) -> dict:
    n = {}
    p = root / "data" / "state" / "corrections.jsonl"
    if p.exists():
        for ln in p.read_text("utf-8").splitlines():
            try:
                d = json.loads(ln)["day"]
            except (ValueError, KeyError):
                continue
            n[d] = n.get(d, 0) + 1
    return n


def _takes(root: Path, day: str) -> int:
    try:
        return len(json.loads((root / "data" / "takes" / f"{day}.json").read_text("utf-8")).get("published") or [])
    except (OSError, ValueError):
        return 0


def _craft(root: Path, cfg: dict, day: str, r: dict | None) -> dict:
    m = ((r or {}).get("craft") or {}).get("metrics")
    if m is None:
        try:
            from . import craft
            m = craft.ours(root, cfg, day)
        except Exception:  # noqa: BLE001
            m = {}
    b, s, dd = m.get("briefing") or {}, m.get("script") or {}, m.get("deepdive") or {}
    reps = [x.get("repeats") for x in (b, s, dd) if x.get("repeats") is not None]
    return {"pace_podcast": s.get("pace_wpm"), "pace_deepdive": dd.get("pace_wpm"),
            "long_sents": b.get("long_sent_pct"), "repeats": sum(reps) if reps else None}


def daily(root: Path, cfg: dict, n: int = 30) -> list:
    from . import quality
    have = {r["day"]: r for r in quality.load_all(root)}
    days = sorted(f.stem for f in (root / "briefings").glob("????-??-??.md"))[-n:]
    corr = _corrections(root)
    rows = []
    for d in days:
        r = have.get(d)
        if r is None:
            try:
                r = quality.score_day(root, cfg, d)
            except Exception:  # noqa: BLE001
                r = None
        checks = {c["key"]: c.get("value") for c in (r or {}).get("checks", [])}
        mg = checks.get("must_grounded")
        rows.append({"day": d,
                     "checks_pct": round(100 * r["passed"] / r["total"]) if r and r.get("total") else None,
                     "words": checks.get("words"),
                     "must_grounded": round(100 * mg) if isinstance(mg, (int, float)) else None,
                     "corrections": corr.get(d, 0), "takes": _takes(root, d),
                     "rating_readers": (r or {}).get("rating_readers"), **_craft(root, cfg, d, r)})
    return rows


def svg_lines(series: dict, title: str, unit: str = "", us: str = critic.OURS, width: int = 760, height: int = 300,
              label_all: bool = True) -> str:
    """series: {name: [(x_label, value)]} with x labels that sort (ISO dates). Our line accent, others grey."""
    e = lambda s: htmllib.escape(str(s), quote=True)  # noqa: E731
    xs = sorted({x for pts in series.values() for x, _ in pts})
    vals = [v for pts in series.values() for _, v in pts if v is not None]
    if not xs or not vals:
        return f'<p class="muted small"><b>{e(title)}</b>: no data yet.</p>'
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:                                   # a flat series: show it against zero
        lo, hi = (0.0, hi * 1.25 or 1.0) if hi >= 0 else (lo * 1.25, 0.0)
    pad = (hi - lo) * 0.12
    nonneg, pct = min(vals) >= 0, unit == "%" and max(vals) <= 100
    lo, hi = (max(lo - pad, 0.0) if nonneg else lo - pad), (min(hi + pad, 100.0) if pct else hi + pad)
    x0, y0, x1, y1 = 56, 40, width - (70 if len(series) == 1 else 220), height - 34
    X = (lambda i: (x0 + x1) / 2) if len(xs) == 1 else (lambda i: x0 + i * (x1 - x0) / (len(xs) - 1))
    Y = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(title)}" style="width:100%;height:auto" '
             f'font-size="11" font-family="inherit">',
             f'<text x="{x0}" y="22" font-size="14" font-weight="600" fill="var(--ink,#14272b)">{e(title)}</text>']
    for t in range(5):                                   # light gridlines with values
        v = lo + t * (hi - lo) / 4
        parts.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line,#d3e2e5)"/>'
                     f'<text x="{x0 - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="var(--muted,#5b6d71)">{v:.0f}{e(unit)}</text>')
    step = max(1, len(xs) // 8)
    for i, x in enumerate(xs):
        last = i == len(xs) - 1
        if (i % step == 0 and (last or len(xs) - 1 - i >= step * 0.6)) or last:
            parts.append(f'<text x="{X(i):.1f}" y="{y1 + 18}" text-anchor="middle" fill="var(--muted,#5b6d71)">{e(x[5:] if len(x) == 10 else x)}</text>')
    ends = []
    for name in sorted(series, key=lambda n: (n == us, n)):   # ours drawn last, on top
        pts = [(xs.index(x), v) for x, v in sorted(series[name]) if v is not None]
        if not pts:
            continue
        mine = name == us
        col = "var(--teal,#3e7e8a)" if mine else "var(--wave,#b9d3d7)"
        d = " ".join(f"{'M' if k == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for k, (i, v) in enumerate(pts))
        parts.append(f'<g><title>{e(name)}</title><path d="{d}" fill="none" stroke="{col}" stroke-width="{3 if mine else 1.6}"/>'
                     + "".join(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{3.5 if mine else 2.5}" fill="{col}">'
                               f'<title>{e(name)} · {e(xs[i])}: {v:g}{e(unit)}</title></circle>' for i, v in pts) + "</g>")
        if mine or label_all:
            ends.append([Y(pts[-1][1]), name, pts[-1][1], mine, X(pts[-1][0])])
    ends.sort(key=lambda t: t[0])                         # end labels, nudged apart so none overlap
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k - 1][0] < 13:
            ends[k][0] = ends[k - 1][0] + 13
    solo = len(series) == 1
    for yy, name, v, mine, xe in ends:
        col = "var(--teal,#3e7e8a)" if mine else "var(--muted,#5b6d71)"
        if not solo:                                     # a thin leader from the line's end to its label
            parts.append(f'<line x1="{xe + 4:.1f}" x2="{x1 + 8}" y1="{Y(v):.1f}" y2="{yy:.1f}" stroke="var(--line,#d3e2e5)"/>')
        label = f"{v:g}{unit}" if solo else f"{name[:30]} {v:g}{unit}"
        parts.append(f'<text x="{x1 + 10}" y="{yy + 4:.1f}" fill="{col}" font-weight="{600 if mine else 400}">{e(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)
