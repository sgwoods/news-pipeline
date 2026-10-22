"""Daily quality scorecard: what code can measure about each edition, against the format spec's targets.

    ./np quality [DAY | all]      -> data/quality/<day>.json (+ a table)
    dashboard /quality            -> scorecard by day, trends, Steven's 1-5 rating and readers' ratings

Measured from files already written (briefing, script, briefings log, run log): nothing here calls a model.
Human judgement comes in as ratings: Steven's from the dashboard or the terminal and readers' from replies that
start with a number 1-5 (data/ratings.jsonl, feedback.py), plus one-click stars in the email and on the site
(data/ratings-stars.jsonl, pulled from the mail script by pull_stars). Stars from Steven's own addresses count as
his rating; anonymous site stars are reported separately and never count toward the breakpoint.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

DIR = "data/quality"
RATINGS = "data/ratings.jsonl"
STARS = "data/ratings-stars.jsonl"           # replaced on every pull: the script's ratings tab is the record
OPPORTUNITY = re.compile(r"\b(helps?|opening|opens|opportunit\w*|wedge|tailwind|wins?|winners?|benefit\w*|advantage|"
                         r"upside|buy signal|room for|cheaper for|good news for)\b", re.I)
DIRECTIVE = re.compile(r"(?:^|[.!?:]\s+)(Ask|Stop|Treat|Don't|Do not|Require|Demand|Insist|Get|Avoid|Make sure|Push|Discount|Accept|"
                       r"Refuse|Reject|Press|Make|Check|Verify|Watch for|Wait for)\b")
VERDICT = re.compile(r"\*\*(?:Evidence check|Critical pass):\*\* (Holds|Mixed|Overstated|Unsupported|Unverified|Too early)\b")

# (key, label, target text, test)
TARGETS = [
    ("privacy", "Privacy gate", "pass", lambda v: v == "pass"),
    ("personal_links", "Personal links in copy", "0", lambda v: v == 0),
    ("words", "Written words", "900–1,300 (cap 1,500)", lambda v: 900 <= v <= 1500),
    ("must", "Must read", "≤5", lambda v: v <= 5),
    ("worth", "Worth knowing", "≤5", lambda v: v <= 5),
    ("brief", "In brief", "≤8", lambda v: v <= 8),
    ("must_grounded", "Must read with primary/report/test", "all", lambda v: v is None or v >= 1.0),
    ("critical_share", "Critiques overstated + unsupported", "15–40%", lambda v: v is None or 0.15 <= v <= 0.40),
    ("opportunity_share", "Our reads naming an opportunity", "≥25%", lambda v: v is None or v >= 0.25),
    ("aggregator_link_share", "Links to aggregators/social", "≤30%", lambda v: v is None or v <= 0.30),
    ("quotes_removed", "Quotes not found in sources", "0", lambda v: v in (None, 0)),
    ("directive", "Directive phrasing (Ask…, Stop…, Treat…)", "0", lambda v: v in (None, 0)),
    ("minutes", "Episode length", "≈10 min (cap 12)", lambda v: v is None or 7 <= v <= 12),
    ("script_problems", "Script sections rewritten/left out", "0", lambda v: v in (None, 0)),
    ("number_issues", "Numbers that don't add up (pipeline/numbers.py)", "0", lambda v: v in (None, 0)),
    ("untraced", "Figures in no source (cut before sending, or flagged)", "0", lambda v: v in (None, 0)),
]


def _rows(p: Path) -> list:
    out = []
    if p.exists():
        for ln in p.read_text("utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    return out


def _section(md: str, name: str) -> str:
    m = re.search(rf"(?ms)^## {re.escape(name)}\n(.*?)(?=^## |\Z)", md)
    return m.group(1) if m else ""


def _untraced(root: Path, day: str):
    runs = [r for r in _rows(root / "data" / "runs.jsonl") if r.get("day") == day
            and ((r.get("stages") or {}).get("write") or {}).get("factcheck")]
    if not runs:
        return None
    fc = runs[-1]["stages"]["write"]["factcheck"]
    return len(fc.get("cut") or []) + len(fc.get("flagged") or [])


def _number_issues(md: str):
    try:
        from .numbers import check
        return len(check(md))
    except Exception:  # noqa: BLE001
        return None


def privacy_check(root: Path, cfg: dict, texts: list) -> tuple:
    """(status, details): private names or personal links anywhere in the public copy -> fail."""
    from . import stages
    from .links import _MDLINK, personal, personal_addresses
    details = []
    names = stages.private_names()
    for t in texts:
        _, hits = stages.scrub_private(t, names, stages.allowed_names(names, []))
        details += [f"private name: {h}" for h in hits]
        details += [f"personal link: {u[:60]}" for _, u in _MDLINK.findall(t) if personal(u, cfg)]
        details += [f"address: {a}" for a in personal_addresses(cfg) if "@" in a and a in t.lower()]
        from .links import DISCLOSURE_FLAG
        details += [f"owner or board-seat mention: {m.group(0)[:40]}" for m in DISCLOSURE_FLAG.finditer(t)][:3]
    return ("fail" if details else "pass"), sorted(set(details))[:10]


def score_day(root: Path, cfg: dict, day: str) -> dict | None:
    from .profiles import profile, host
    bdir = root / cfg.get("paths", {}).get("briefings", "briefings")
    f = bdir / f"{day}.md"
    if not f.exists():
        return None
    md = f.read_text("utf-8")
    script = (bdir / f"{day}.script.md").read_text("utf-8") if (bdir / f"{day}.script.md").exists() else ""
    log = [b for b in _rows(root / "data" / "briefings.jsonl") if b.get("day") == day]
    last = log[-1] if log else {}
    runs = [r for r in _rows(root / "data" / "runs.jsonl") if r.get("day") == day and (r.get("stages") or {}).get("audio")]
    audio = (runs[-1]["stages"]["audio"] if runs else {}) or {}
    crit_runs = [r for r in _rows(root / "data" / "runs.jsonl") if r.get("day") == day
                 and ((r.get("stages") or {}).get("critique") or {}).get("verdicts")]
    cv = crit_runs[-1]["stages"]["critique"]["verdicts"] if crit_runs else {}

    must = len(re.findall(r"^### ", _section(md, "Must read"), re.M))
    worth = len(re.findall(r"^- ", _section(md, "Worth knowing"), re.M))
    brief = len(re.findall(r"^- ", _section(md, "In brief"), re.M))
    verdicts = VERDICT.findall(md)
    crit = sum(1 for v in verdicts if v in ("Overstated", "Unsupported"))
    judged_md = sum(1 for v in verdicts if v not in ("Unverified", "Too early"))
    judged_cv = sum(n for k, n in cv.items() if k != "unverified")
    reads = re.findall(r"\*\*Our read:\*\* (.+)", md)
    voiced = reads + re.findall(r"\*\*The (?:AGI-forward|AI-realist|market|policy) view:\*\* (.+)", md) \
        + re.findall(r"\*\*The day in brief\.\*\* (.+)", md)
    directive = sum(len(DIRECTIVE.findall(t)) for t in voiced)
    opp = sum(1 for r in reads if OPPORTUNITY.search(r))
    from .links import _MDLINK
    urls = [u for _, u in _MDLINK.findall(md)]
    weak = sum(1 for u in urls if profile({"url": u, "person": ""})["kind"] in ("aggregator", "social"))
    bal = last.get("balance") or {}
    privacy, pdetails = privacy_check(root, cfg, [md, script])
    from .links import personal
    plinks = sum(1 for u in urls if personal(u, cfg))
    errs = [e for e in (audio.get("errors") or []) if "script" in str(e)]
    v = {
        "privacy": privacy, "personal_links": plinks, "words": len(md.split()),
        "must": must, "worth": worth, "brief": brief,
        "must_grounded": (bal["must_grounded"] / bal["must"]) if bal.get("must") else None,
        # headline-only items ("unverified") were not judged, so they are not in the share either way
        "critical_share": ((cv.get("overstated", 0) + cv.get("unsupported", 0)) / judged_cv) if judged_cv
        else ((crit / judged_md) if judged_md else None),
        "headline_only": (cv.get("unverified", 0) if cv else sum(1 for x in verdicts if x == "Unverified")),
        "opportunity_share": (opp / len(reads)) if reads else None,
        "aggregator_link_share": (weak / len(urls)) if urls else None,
        "quotes_removed": last.get("quotes_removed"), "directive": directive,
        "minutes": audio.get("minutes"), "script_problems": len(errs) if audio else None,
        "number_issues": _number_issues(md),
        "untraced": _untraced(root, day),
    }
    checks = [{"key": k, "label": lab, "target": tgt, "value": v.get(k), "ok": bool(test(v.get(k)))}
              for k, lab, tgt, test in TARGETS if v.get(k) is not None or k in ("must_grounded", "critical_share")]
    ratings = sorted((r for r in _rows(root / RATINGS) + _rows(root / STARS) if r.get("day") == day),
                     key=lambda r: str(r.get("at") or ""))
    steven = [r["score"] for r in ratings if r.get("who") == "steven"]
    by_reader = {}                               # one vote per reader per day: the latest
    for r in ratings:
        if r.get("who") not in ("steven", "web"):
            by_reader[r.get("id") or r.get("who")] = r["score"]
    readers = list(by_reader.values())
    web = [r["score"] for r in ratings if r.get("who") == "web"]
    out = {"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "values": v, "checks": checks,
           "passed": sum(1 for c in checks if c["ok"]), "total": len(checks), "privacy_details": pdetails,
           "verdicts": {x: verdicts.count(x) for x in ("Holds", "Mixed", "Overstated", "Unsupported", "Unverified")},
           "balance": bal, "rating_steven": steven[-1] if steven else None,
           "rating_readers": (round(sum(readers) / len(readers), 1) if readers else None), "n_reader_ratings": len(readers),
           "rating_web": (round(sum(web) / len(web), 1) if web else None), "n_web_ratings": len(web)}
    p = root / DIR / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return out


def load_all(root: Path) -> list:
    out = []
    for p in sorted((root / DIR).glob("????-??-??.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return out


def pull_stars(root: Path, cfg: dict) -> int:
    """Fetch the star ratings from the mail script into data/ratings-stars.jsonl -> rows. Needs email.ratings."""
    from . import mailer
    if not mailer.ecfg(cfg).get("ratings"):
        return 0
    rows = []
    for r in mailer.ratings(cfg):
        try:
            sc = int(r.get("score"))
        except (TypeError, ValueError):
            continue
        if not (1 <= sc <= 5) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(r.get("day", ""))[:10]):
            continue
        who = r.get("who") if r.get("who") in ("steven", "reader", "web") else "web"
        at = str(r.get("at") or "")
        try:                                     # the script stamps UTC; local ratings are local time
            at = dt.datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone().replace(tzinfo=None) \
                .isoformat(timespec="seconds")
        except ValueError:
            pass
        rows.append({"day": str(r["day"])[:10], "score": sc, "who": who, "id": str(r.get("id") or "")[:16],
                     "note": str(r.get("note") or "")[:600], "at": at, "src": "stars"})
    p = root / STARS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), "utf-8")
    return len(rows)


def add_rating(root: Path, day: str, score: int, who: str = "steven", note: str = "") -> dict:
    if not (1 <= int(score) <= 5):
        raise ValueError("score must be 1-5")
    row = {"day": day, "score": int(score), "who": who, "note": note[:300],
           "at": dt.datetime.now().isoformat(timespec="seconds")}
    p = root / RATINGS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float) and v <= 1.0 and not isinstance(v, bool):
        return f"{v:.0%}"
    return str(v)
