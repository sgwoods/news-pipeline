"""Weekly quality review, run on the Mac from local files only (no web, no tools, no mailbox).

    ./np review weekly [DAY]   -> docs/reviews/<DAY>-weekly-review.md (+ git commit)

Replaces the cloud scheduled task (2026-10-16): the model sees the last 7 editions, their scripts and
scorecards, the deep dives, ratings and feedback themes, and writes the review in the agreed format.
Its output is scrubbed for private names before it is written.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

DIR = "docs/reviews"
RUBRIC_FILE = "docs/reviews/2026-10-13-format-review.md"


def _read(p: Path, n: int) -> str:
    try:
        return p.read_text("utf-8")[:n]
    except OSError:
        return ""


def _section(md: str, start: str, stop: str) -> str:
    i = md.find(start)
    if i < 0:
        return ""
    j = md.find(stop, i + len(start))
    return md[i: j if j > 0 else None]


def gather(root: Path, cfg: dict, day: str) -> str:
    bdir = root / cfg.get("paths", {}).get("briefings", "briefings")
    days = sorted(f.stem for f in bdir.glob("????-??-??.md") if f.stem <= day)[-7:]
    rubric = _read(root / RUBRIC_FILE, 40000)
    parts = ["# Rubric and format spec",
             _section(rubric, "## 1. Rubric and scores", "| Edition |") + _section(rubric, "## 4. Format spec", "## 5.")]
    earlier = sorted(p for p in (root / DIR).glob("*-weekly-review.md") if p.name[:10] < day)
    if earlier:
        parts += ["# Last week's review (for comparison)", _read(earlier[-1], 8000)]
    for d in days:
        q = {}
        try:
            q = json.loads((root / "data" / "quality" / f"{d}.json").read_text("utf-8"))
        except (OSError, ValueError):
            pass
        card = {"checks": f"{q.get('passed')}/{q.get('total')}",
                "missed": [c["label"] for c in q.get("checks", []) if not c.get("ok")],
                "privacy": (q.get("values") or {}).get("privacy"),
                "ratings": {k: q.get(k) for k in ("rating_steven", "rating_readers", "n_reader_ratings", "rating_web")},
                "values": {k: v for k, v in (q.get("values") or {}).items()
                           if k in ("critical_share", "headline_only", "aggregator_link_share", "words", "minutes",
                                    "directive", "script_problems", "must_grounded")}}
        parts += [f"# Edition {d}", "## Scorecard", json.dumps(card, ensure_ascii=False),
                  "## Written edition", _read(bdir / f"{d}.md", 12000),
                  "## Podcast script", _read(bdir / f"{d}.script.md", 9000)]
        dd = root / "briefings" / "deepdives" / f"{d}.md"
        if dd.exists():
            parts += ["## Deep dive (written version)", _read(dd, 5000)]
    try:
        fb = json.loads((root / "data" / "feedback" / "feedback.json").read_text("utf-8"))
        items = fb.get("items", fb) if isinstance(fb, dict) else fb
        themes = [{k: it.get(k) for k in ("day", "category", "summary", "status", "rating") if it.get(k)}
                  for it in (items or []) if isinstance(it, dict)][-40:]
        parts += ["# Reader feedback (summaries only)", json.dumps(themes, ensure_ascii=False)]
    except (OSError, ValueError):
        parts += ["# Reader feedback", "none yet"]
    return "\n\n".join(p for p in parts if p)


def run(root: Path, cfg: dict, day: str = "", log=print) -> Path:
    from . import llm as llm_mod
    from . import stages
    from .links import strip_disclosures
    day = day or dt.date.today().isoformat()
    tmpl, _v = stages.prompt("weekly_review")
    data = gather(root, cfg, day)
    backend = llm_mod.for_stage(cfg, "review")
    text = backend.complete("You review a daily AI newsletter and podcast. You have no tools; answer in Markdown.",
                            tmpl + "\n\n---\n\n" + data, json_mode=False, max_tokens=6000)
    text, _hits = stages.scrub_private(text)          # never a private name in the repo
    text = strip_disclosures(text)[0]
    out = root / DIR / f"{day}-weekly-review.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# Weekly quality review · {day}\n\n*Written by {backend.label} from the pipeline's own files "
                   f"(last 7 editions, scripts, scorecards, ratings, feedback).*\n\n" + text.strip() + "\n", "utf-8")
    bottom = re.search(r"## Bottom line\s+(.+?)(?:\n## |\Z)", text, re.S)
    log(f"Weekly review: {out.relative_to(root)}")
    if bottom:
        log(bottom.group(1).strip()[:600])
    return out


def due(root: Path, cfg: dict, day: str) -> bool:
    """The configured weekday (review.weekly_day, default friday) and no review written for this day yet."""
    want = str((cfg.get("review") or {}).get("weekly_day", "friday")).lower()
    d = dt.date.fromisoformat(day)
    return d.strftime("%A").lower() == want and not (root / DIR / f"{day}-weekly-review.md").exists()
