"""Staging against production for the same day: is the dev code's edition still the same kind of edition?

    ./np staging compare [DAY]     # in dev, after ./np staging run: writes logs/compare-DAY.md, prints a summary;
                                   # exit 3 when something needs review

Compared: sections, story and bullet counts, words, source links, the evidence mix and fact-check counts (from
each side's run record), audio minutes, and the privacy scan of the dev site. Model output differs run to run,
so wording is shown as a diff, not judged; the flags are for structure and safety.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from pathlib import Path


def _section(md: str, name: str) -> str:
    return md.split(f"## {name}", 1)[1].split("\n## ", 1)[0] if f"## {name}" in md else ""


def edition(root: Path, day: str) -> dict:
    p = root / "briefings" / f"{day}.md"
    from .textutil import legacy_top
    md = legacy_top(p.read_text("utf-8")) if p.exists() else ""
    run = {}
    rp = root / "data" / "runs.jsonl"
    if rp.exists():
        for ln in rp.read_text("utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("day") == day and (r.get("stages", {}).get("write") or {}).get("status") == "ok":
                run = r
    w = (run.get("stages") or {}).get("write") or {}
    au = (run.get("stages") or {}).get("audio") or {}
    bal, fc = w.get("balance") or {}, w.get("factcheck") or {}
    return {
        "exists": bool(md),
        "sections": re.findall(r"^## (.+)$", md, re.M),
        "must read": len(re.findall(r"^### ", _section(md, "Must read"), re.M)),
        "worth knowing": len(re.findall(r"^### |^- ", _section(md, "Worth knowing"), re.M)),
        "top of mind": len(re.findall(r"^- ", _section(md, "Top of mind"), re.M)),
        "open questions": len(re.findall(r"^- |^\d+\. ", _section(md, "Open questions"), re.M)),
        "words": len(re.findall(r"\w+", md)),
        "source links": len(re.findall(r"\]\(https?://", md)),
        "must grounded": f"{bal.get('must_grounded', '?')}/{bal.get('must', '?')}" if bal else "?",
        "evidence": f"{bal.get('primary', '?')} primary, {bal.get('reports', '?')} reports, {bal.get('commentary', '?')} commentary"
                    if bal else "?",
        "fact check": f"{fc.get('checked', '?')} checked, {len(fc.get('cut') or [])} cut, {len(fc.get('flagged') or [])} flagged"
                      if fc else "?",
        "audio minutes": au.get("minutes"),
        "run": run.get("run_id", ""),
        "md": md,
    }


def flags(prod: dict, dev: dict) -> list:
    out = []
    if not dev["exists"]:
        return ["dev has no edition for this day: run ./np staging run"]
    if not prod["exists"]:
        out.append("production has no edition for this day to compare against")
        return out
    missing = [s for s in prod["sections"] if s not in dev["sections"]]
    if missing:
        out.append(f"sections missing in dev: {', '.join(missing)}")
    for k in ("must read", "top of mind"):
        if dev[k] < prod[k]:
            out.append(f"{k}: {dev[k]} in dev vs {prod[k]} in production")
    if prod["words"] and abs(dev["words"] - prod["words"]) / prod["words"] > 0.25:
        out.append(f"length changed by more than 25%: {prod['words']} -> {dev['words']} words")
    if prod["source links"] and dev["source links"] < 0.7 * prod["source links"]:
        out.append(f"far fewer source links: {prod['source links']} -> {dev['source links']}")
    pa, da = prod.get("audio minutes"), dev.get("audio minutes")
    if pa and da and abs(da - pa) / pa > 0.25:
        out.append(f"audio length changed by more than 25%: {pa} -> {da} min")
    if pa and not da:
        out.append("dev has no audio for this day")
    return out


def write(dev_root: Path, prod_root: Path, day: str) -> dict:
    prod, dev = edition(prod_root, day), edition(dev_root, day)
    review = flags(prod, dev)
    scan = []
    if (dev_root / "site" / "index.html").exists():
        from .publish import scan_site
        scan = scan_site(dev_root, dev_root / "site")
        review += [f"privacy scan: {x}" for x in scan[:10]]
    from .version import full
    keys = ["sections", "must read", "worth knowing", "top of mind", "open questions", "words", "source links",
            "must grounded", "evidence", "fact check", "audio minutes", "run"]
    rows = "\n".join(f"| {k} | {', '.join(prod[k]) if isinstance(prod[k], list) else prod[k]} | "
                     f"{', '.join(dev[k]) if isinstance(dev[k], list) else dev[k]} |" for k in keys)
    diff = "\n".join(list(difflib.unified_diff(prod["md"].splitlines(), dev["md"].splitlines(), "production", "dev",
                                               lineterm="", n=0))[:400])
    verdict = "NEEDS REVIEW" if review else "OK: same shape as production"
    text = (f"# Staging vs production · {day}\n\nDev code v{full(dev_root)} · compared "
            f"{dt.datetime.now():%Y-%m-%d %H:%M}\n\n**{verdict}**\n\n"
            + ("".join(f"- {x}\n" for x in review) + "\n" if review else "")
            + f"| | production | dev |\n|---|---|---|\n{rows}\n\n"
            f"Wording differs run to run (the models are not deterministic); the diff is for reading, not a verdict.\n\n"
            f"```diff\n{diff}\n```\n")
    p = dev_root / "logs" / f"compare-{day}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")
    summary = f"{verdict} ({day})\n" + "".join(f"  - {x}\n" for x in review) + "\n".join(
        f"  {k}: production {prod[k] if not isinstance(prod[k], list) else len(prod[k])} · dev "
        f"{dev[k] if not isinstance(dev[k], list) else len(dev[k])}" for k in keys[1:11])
    return {"review": review, "file": str(p.relative_to(dev_root)), "summary": summary, "scan": scan}
