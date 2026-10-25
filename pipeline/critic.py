"""The weekly critic: how the briefing scores against the top tech and AI shows, and what to improve.

Every Saturday a scheduled Claude session researches the latest episode or issue of the ten benchmark shows,
reviews the past week of our editions with the same rubric, and saves the result as data/critic/<date>.json
(schema below). This module turns those files into the owner's weekly email: our score and rank, bar charts by
characteristic against the field, our trend over the weeks, what shipped, and the top suggestions. Charts are
plain HTML tables (no images), so they render in any mail client. The email goes only to the owner.

    {"date": "YYYY-MM-DD", "method": "...",
     "weights": {"selection": 18, ...},
     "shows": [{"name", "episode", "date", "link", "scores": {dim: 1-10}, "overall"}],
     "ours": {"scores": {dim: n}, "written": {dim: n}, "podcast": {dim: n}, "overall", "written_overall",
              "podcast_overall", "edition_days": [...]},
     "strengths": ["..."], "suggestions": [{"title", "evidence", "options": ["A. ...", ...], "pick": "A"}],
     "first_batch": ["..."], "notes": "..."}

    ./np critic preview [DATE]    the email as text, nothing sent
    ./np critic email [DATE]      send it to the owner (also the run queue's critic-email job)
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
from pathlib import Path

DIR = "data/critic"
DIMS = [("selection", "Content selection", 18), ("accuracy", "Accuracy & sourcing", 15),
        ("depth", "Depth & insight", 14), ("timeliness", "Timeliness & cadence", 10),
        ("structure", "Structure & pacing", 10), ("opinion", "Opinion / point of view", 9),
        ("distinct", "Distinctiveness & fit", 7), ("writing", "Writing / script", 6),
        ("tone", "Tone & voice", 5), ("production", "Production", 6)]
OURS = "AI Briefing (us)"
C = {"us": "#2563eb", "field": "#9ca3af", "best": "#16a34a", "text": "#111827", "muted": "#6b7280",
     "bg": "#f9fafb", "panel": "#ffffff", "border": "#e5e7eb", "low": "#dc2626"}


def overall(scores: dict) -> float:
    return round(sum(scores.get(k, 0) * w for k, _, w in DIMS) / 10, 1)


def history(root: Path) -> list:
    out = []
    for p in sorted((root / DIR).glob("????-??-??.json")):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except ValueError:
            continue
    return out


def save(root: Path, week: dict) -> Path:
    for s in week.get("shows", []):
        s["overall"] = overall(s["scores"])
    week["ours"]["overall"] = overall(week["ours"]["scores"])
    p = root / DIR / f"{week['date']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(week, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return p


# ---------------------------------------------------------------- charts (HTML tables)
def _bar(value: float, scale: float, color: str, h: int = 12) -> str:
    pct = max(0.0, min(100.0, 100.0 * value / scale))
    rest = 100 - pct
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="width:{pct:.0f}%;background:{color};height:{h}px;border-radius:3px"></td>'
            + (f'<td style="width:{rest:.0f}%;height:{h}px"></td>' if rest > 0 else "") + "</tr></table>")


def _esc(s) -> str:
    return htmllib.escape(str(s))


def chart_by_dimension(week: dict) -> str:
    """Our score per characteristic against the field average and the best show."""
    shows = week.get("shows", [])
    rows = []
    for k, label, w in DIMS:
        vals = [s["scores"].get(k, 0) for s in shows]
        avg = sum(vals) / len(vals) if vals else 0
        best = max(shows, key=lambda s: s["scores"].get(k, 0)) if shows else None
        us = week["ours"]["scores"].get(k, 0)
        color = C["low"] if us < avg - 0.5 else C["us"]
        rows.append(
            f'<tr><td style="padding:6px 8px 6px 0;font-size:13px;color:{C["text"]};white-space:nowrap">{_esc(label)}'
            f'<div style="font-size:11px;color:{C["muted"]}">weight {w}</div></td>'
            f'<td style="padding:6px 0;width:100%">{_bar(us, 10, color)}<div style="height:3px"></div>{_bar(avg, 10, C["field"], 6)}</td>'
            f'<td style="padding:6px 0 6px 8px;font-size:13px;white-space:nowrap;color:{C["text"]}"><b>{us:g}</b> '
            f'<span style="color:{C["muted"]}">avg {avg:.1f} · best {best["scores"].get(k, 0) if best else 0:g} '
            f'({_esc((best or {}).get("name", "")[:18])})</span></td></tr>')
    legend = (f'<div style="font-size:12px;color:{C["muted"]};margin:0 0 8px">'
              f'<span style="color:{C["us"]}">■</span> us &nbsp; <span style="color:{C["low"]}">■</span> us, below the field '
              f'&nbsp; <span style="color:{C["field"]}">■</span> field average (out of 10)</div>')
    return legend + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>'


def chart_ranking(week: dict) -> str:
    rows = sorted([(s["name"], s["overall"]) for s in week.get("shows", [])] + [(OURS, week["ours"]["overall"])],
                  key=lambda r: -r[1])
    out = []
    for i, (name, score) in enumerate(rows, 1):
        us = name == OURS
        out.append(f'<tr><td style="padding:4px 8px 4px 0;font-size:13px;white-space:nowrap;color:{C["text"]};'
                   f'font-weight:{700 if us else 400}">{i}. {_esc(name)}</td>'
                   f'<td style="padding:4px 0;width:100%">{_bar(score, 100, C["us"] if us else C["field"])}</td>'
                   f'<td style="padding:4px 0 4px 8px;font-size:13px;font-weight:{700 if us else 400}">{score:.1f}</td></tr>')
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(out)}</table>'


def chart_trend(weeks: list, n: int = 8) -> str:
    """Our score per characteristic over the last n weeks: one small bar per week."""
    weeks = weeks[-n:]
    note = (f'<p style="font-size:12px;color:{C["muted"]};margin:8px 0 0">First week on record: each Saturday adds a '
            f'bar per characteristic, so the trend shows from next week.</p>') if len(weeks) == 1 else ""
    head = "".join(f'<td style="font-size:11px;color:{C["muted"]};text-align:center;padding:0 2px">'
                   f'{_esc(w["date"][5:])}</td>' for w in weeks)
    rows = []
    for k, label, _ in [("overall", "Overall (÷10)", 0)] + DIMS:
        cells = []
        for w in weeks:
            v = w["ours"]["overall"] / 10 if k == "overall" else w["ours"]["scores"].get(k, 0)
            hpx = int(round(4 + 3.2 * v))
            cells.append(f'<td style="vertical-align:bottom;text-align:center;padding:0 2px">'
                         f'<div style="font-size:10px;color:{C["muted"]}">{v:.1f}</div>'
                         f'<div style="height:{hpx}px;width:14px;margin:0 auto;background:{C["us"]};border-radius:2px">'
                         f'</div></td>')
        first, last = (weeks[0]["ours"]["overall"] / 10, weeks[-1]["ours"]["overall"] / 10) if k == "overall" else \
            (weeks[0]["ours"]["scores"].get(k, 0), weeks[-1]["ours"]["scores"].get(k, 0))
        d = last - first
        arrow = f'<span style="color:{C["best"] if d > 0 else (C["low"] if d < 0 else C["muted"])}">' \
                f'{"▲" if d > 0 else ("▼" if d < 0 else "·")} {d:+.1f}</span>'
        rows.append(f'<tr><td style="font-size:12px;padding:4px 8px 4px 0;white-space:nowrap">{_esc(label)}</td>'
                    f'{"".join(cells)}<td style="font-size:12px;padding-left:8px;white-space:nowrap">{arrow}</td></tr>')
    return (f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td></td>{head}<td></td></tr>'
            f'{"".join(rows)}</table>' + note)


# ---------------------------------------------------------------- the email
def shipped(root: Path, since: str, until: str) -> list:
    p = root / "data" / "state" / "releases.jsonl"
    rows = []
    for x in (p.read_text("utf-8").splitlines() if p.exists() else []):
        try:
            r = json.loads(x)
        except ValueError:
            continue
        if since <= r.get("at", "")[:10] <= until and r.get("kind") == "release":
            rows.append(f"v{r['version']}: {r.get('note', '').replace('reviewed:', '').strip()[:140]}")
    return rows


def render(root: Path, date: str | None = None) -> dict:
    weeks = history(root)
    if not weeks:
        raise RuntimeError("no critic results yet (data/critic/*.json)")
    week = next((w for w in weeks if w["date"] == date), weeks[-1]) if date else weeks[-1]
    upto = [w for w in weeks if w["date"] <= week["date"]]
    prev = upto[-2] if len(upto) > 1 else None
    ours = week["ours"]
    rank_rows = sorted([s["overall"] for s in week["shows"]] + [ours["overall"]], reverse=True)
    rank = rank_rows.index(ours["overall"]) + 1
    delta = f"{ours['overall'] - prev['ours']['overall']:+.1f} since {prev['date']}" if prev else "First week on record"
    gaps = sorted(DIMS, key=lambda d: ours["scores"].get(d[0], 0) - max(s["scores"].get(d[0], 0) for s in week["shows"]))
    top = week.get("suggestions", [])[:5]
    since = (dt.date.fromisoformat(week["date"]) - dt.timedelta(days=7)).isoformat()
    ships = shipped(root, since, week["date"])
    d = dt.date.fromisoformat(week["date"])
    subject = f"AI Briefing · Weekly critic · {d.strftime('%a %b')} {d.day}: {ours['overall']:.1f}/100, #{rank} of {len(rank_rows)}"
    cell = f'style="padding:20px 22px;background:{C["panel"]};border:1px solid {C["border"]};border-radius:14px"'
    H2 = f'style="margin:0 0 10px;font-size:17px;color:{C["text"]}"'
    P = f'style="margin:0 0 10px;font-size:14px;line-height:1.55;color:{C["text"]}"'
    sp = '<tr><td style="height:14px"></td></tr>'
    blocks = [
        f'<tr><td {cell}><div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:{C["muted"]}">'
        f'Weekly critic · private</div><h1 style="margin:8px 0 6px;font-size:24px;color:{C["text"]}">'
        f'{ours["overall"]:.1f} / 100 · #{rank} of {len(rank_rows)}</h1>'
        f'<p {P}>{_esc(delta)}. Written edition {ours.get("written_overall", ours["overall"]):.1f}, podcast '
        f'{ours.get("podcast_overall", ours["overall"]):.1f}. Biggest gaps to the best show: '
        f'{", ".join(_esc(lbl) for _, lbl, _ in gaps[:3])}.</p>'
        f'<p style="margin:0;font-size:12px;color:{C["muted"]}">{_esc(week.get("method", ""))}</p></td></tr>',
        sp + f'<tr><td {cell}><h2 {H2}>Top suggestions this week</h2><ol style="margin:0;padding-left:20px">'
        + "".join(f'<li style="margin:0 0 10px;font-size:14px;line-height:1.5;color:{C["text"]}"><b>{_esc(s["title"])}</b>'
                  f'<br><span style="color:{C["muted"]}">{_esc(s.get("evidence", ""))}</span><br>'
                  f'Recommended: {_esc(next((o for o in s.get("options", []) if o.startswith(s.get("pick", "A"))), (s.get("options") or [""])[0]))}</li>'
                  for s in top) + "</ol>"
        + (f'<p {P}><b>Suggested first batch:</b> {_esc("; ".join(week.get("first_batch", [])))}</p>' if week.get("first_batch") else "")
        + "</td></tr>",
        sp + f'<tr><td {cell}><h2 {H2}>How we stack up, by characteristic</h2>{chart_by_dimension(week)}</td></tr>',
        sp + f'<tr><td {cell}><h2 {H2}>Overall ranking (latest episode or issue each)</h2>{chart_ranking(week)}</td></tr>',
        sp + f'<tr><td {cell}><h2 {H2}>Our trend</h2>{chart_trend(upto)}</td></tr>',
    ]
    if ships:
        blocks.append(sp + f'<tr><td {cell}><h2 {H2}>Shipped this week</h2><ul style="margin:0;padding-left:20px">'
                      + "".join(f'<li style="font-size:13px;margin:0 0 4px">{_esc(x)}</li>' for x in ships) + "</ul></td></tr>")
    if week.get("strengths"):
        blocks.append(sp + f'<tr><td {cell}><h2 {H2}>Keep doing</h2><ul style="margin:0;padding-left:20px">'
                      + "".join(f'<li style="font-size:13px;margin:0 0 4px">{_esc(x)}</li>' for x in week["strengths"])
                      + "</ul></td></tr>")
    rest = week.get("suggestions", [])[5:]
    if rest:
        blocks.append(sp + f'<tr><td {cell}><h2 {H2}>Other suggestions</h2><ol start="6" style="margin:0;padding-left:20px">'
                      + "".join(f'<li style="font-size:13px;margin:0 0 6px">{_esc(s["title"])}</li>' for s in rest)
                      + "</ol></td></tr>")
    shows = "".join(f'<li style="font-size:12px;margin:0 0 3px">{_esc(s["name"])}: '
                    f'<a href="{_esc(s.get("link", ""))}" style="color:{C["us"]}">{_esc(s.get("episode", "")[:80])}</a> '
                    f'({_esc(s.get("date", ""))}) · {s["overall"]:.1f}</li>' for s in week["shows"])
    blocks.append(sp + f'<tr><td {cell}><h2 {H2}>What was rated</h2><ul style="margin:0;padding-left:20px">{shows}</ul>'
                  f'<p style="margin:8px 0 0;font-size:12px;color:{C["muted"]}">Rubric (weights): '
                  + _esc(", ".join(f"{lbl} {w}" for _, lbl, w in DIMS)) + ". Each 1-10; overall = weighted sum ÷ 10."
                  + (f" {_esc(week['notes'])}" if week.get("notes") else "") + "</p></td></tr>")
    html = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"></head><body style="margin:0;background:{C["bg"]}"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" style="background:{C["bg"]}"><tr><td align="center" style="padding:18px 10px">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;'
            f'font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif">{"".join(blocks)}</table></td></tr></table>'
            f'</body></html>')
    L = [subject, "", f"{ours['overall']:.1f}/100, #{rank} of {len(rank_rows)} ({delta}).", "", "TOP SUGGESTIONS"]
    L += [f"{i}. {s['title']}: {s.get('evidence', '')}" for i, s in enumerate(top, 1)]
    L += ["", "BY CHARACTERISTIC (us / field avg)"]
    for k, label, w in DIMS:
        vals = [s["scores"].get(k, 0) for s in week["shows"]]
        L.append(f"  {label} ({w}): {ours['scores'].get(k, 0):g} / {sum(vals) / len(vals):.1f}")
    L += ["", "RANKING"] + [f"  {n}: {v:.1f}" for n, v in sorted([(s["name"], s["overall"]) for s in week["shows"]]
                                                                + [(OURS, ours["overall"])], key=lambda r: -r[1])]
    if ships:
        L += ["", "SHIPPED THIS WEEK"] + [f"  {x}" for x in ships]
    return {"subject": subject, "html": html, "text": "\n".join(L), "date": week["date"]}


def send(root: Path, cfg: dict, date: str | None = None) -> str:
    """To the owner only (email.test_to), through the gated mailer."""
    from . import mailer
    m = render(root, date)
    to = mailer.ecfg(cfg).get("test_to")
    if not to:
        raise RuntimeError("email.test_to (the owner's address) is not set")
    mailer.call(cfg, "send", subject=m["subject"], html=mailer.defuse(m["html"]), text=mailer.defuse(m["text"]), to=to)
    p = root / DIR / "sent.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"date": m["date"], "at": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
    return f"weekly critic for {m['date']} sent to the owner"
