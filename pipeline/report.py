"""Compact, paste-friendly status report → logs/last-report.md.

Written after every ./np command. Short on purpose: it's what Claude reads (directly from the
folder, or pasted into chat) to see what happened, without scrolling through full logs.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

from .archive import read_jsonl


def _git(root: Path, *args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _stage_detail(name: str, s: dict) -> str:
    if s.get("error"):
        return s["error"][:160]
    if s.get("reason"):
        return s["reason"]
    if name == "fetch" and "items_new" in s:
        return f"{s['items_new']} new; {s.get('sources_failed', 0)}/{s.get('sources_total', 0)} sources failed"
    if name == "filter" and "items_in" in s:
        return (f"{s['items_in']} in → {s['kept']} kept ({s.get('dropped_by_rule', 0)} dropped by rule, "
                f"{s['dropped'] - s.get('dropped_by_rule', 0)} by model)")
    if name == "rank" and "summarized" in s:
        return f"{s['summarized']} summarized, {s.get('full_read', 0)} FULL READ, {s.get('failed', 0)} failed"
    if name == "critique" and "critiqued" in s:
        v = ", ".join(f"{k} {n}" for k, n in (s.get("verdicts") or {}).items())
        rd = s.get("reader") or {}
        extra = (f" · {rd.get('thin', 0)} headline-only: {rd.get('read', 0)} article(s) read, "
                 f"{rd.get('unreadable', 0)} unreadable, {rd.get('no_link', 0)} posts") if rd.get("thin") else ""
        return f"{s['critiqued']} critiqued ({v}){extra}"
    if name == "cluster" and "stories" in s:
        return (f"{s['records']} records → {s['stories']} stories ({s['multi_source']} multi-source); "
                f"must {s['must']}, worth {s['worth']}, brief {s['brief']}, +{s['more']} more")
    if name == "editorial" and "top_of_mind" in s:
        return (f"day-in-brief {'yes' if s.get('day_in_brief') else 'no'}, {s['top_of_mind']} top-of-mind, "
                f"{s.get('editor_views', 0)} editor's views, {s.get('open_questions', 0)} open questions, "
                f"{s.get('developing', 0)} developing · {s.get('model', '')}")
    if name == "audio" and "minutes" in s:
        return f"{s['minutes']} min, {s.get('words', 0)} words, {s.get('voice', '')} · {s.get('delivered', '')}"
    if name == "write" and s.get("file"):
        b = s.get("balance") or {}
        bal = (f" · evidence: {b.get('must_grounded', 0)}/{b.get('must', 0)} Must read grounded, {b.get('primary', 0)} primary,"
               f" {b.get('reports', 0)} reports, {b.get('commentary', 0)} commentary · stances "
               + (", ".join(f"{k} {v}" for k, v in sorted((b.get("stances") or {}).items())) or "none")) if b else ""
        return f"{s['file']} · {s.get('items', 0)} items · {s.get('topline_bullets', 0)} top-of-mind bullets{bal}"
    return ""


def _count_entries(md: str, section: str) -> int:
    body = md.split("## " + section, 1)[1].split("\n## ", 1)[0]
    if section in ("Top of mind", "In brief", "Open questions"):
        return len(re.findall(r"^- ", body, re.M))
    return len(re.findall(r"^### |^- \*\*\d+\.", body, re.M))


def build(root: Path, cfg: dict, cmd: str = "", exit_code=None, output_file: str = "") -> str:
    paths = cfg.get("paths", {})
    L = [f"# news-pipeline report · {dt.datetime.now():%Y-%m-%d %H:%M}"]
    if cmd:
        L.append(f"Command: `./np {cmd}`" + (f" → exit {exit_code}" if exit_code is not None else "")
                 + (f" · full output: `{output_file}`" if output_file else ""))
    L.append("")

    runs = read_jsonl(root / paths.get("runs", "data/runs.jsonl"))
    if runs:
        r = runs[-1]
        exp = f" · EXPERIMENT profile {r['experiment']}" if r.get("experiment") else ""
        prof = (r.get("profile") or {})
        L += [f"## Last run {r['run_id']}: {r['status'].upper()}  ({r['started'][11:16]}–{(r.get('ended') or '')[11:16]}){exp}",
              f"Profile: {prof.get('name', '')} {prof.get('fingerprint', '')}".rstrip() if prof else "",
              f"LLM: {r.get('llm', {}).get('backend', '')} {r.get('llm', {}).get('model', '')}", "",
              "| stage | status | sec | detail |", "|---|---|---|---|"]
        for name, s in r["stages"].items():
            L.append(f"| {name} | {s.get('status', '')} | {s.get('seconds', '')} | {_stage_detail(name, s)} |")
        fails = [p for p in r["stages"].get("fetch", {}).get("per_source", []) if p.get("status") != "ok"]
        if fails:
            L += ["", "Fetch failures:"] + [f"- {p['person']} [{p['kind']}] {p['url']}: {p.get('error', '')}" for p in fails]
        errs = [e for s in r["stages"].values() for e in (s.get("errors") or [])]
        if errs:
            L += ["", "Stage errors:"] + [f"- {e[:200]}" for e in errs[:10]]
        log = root / r.get("log", "")
        if log.is_file():
            lines = log.read_text("utf-8", errors="replace").splitlines()
            warn = [ln for ln in lines if " WARNING " in ln or " ERROR " in ln]
            times = [float(m.group(1)) for ln in lines if (m := re.search(r"summarize \d+/\d+ ([\d.]+)s", ln))]
            if times:
                L += ["", f"Summarize speed: {len(times)} items, avg {sum(times) / len(times):.1f}s, max {max(times):.1f}s"]
            if warn:
                L += ["", f"Warnings/errors in log ({len(warn)}):"] + [f"- {w[:220]}" for w in warn[:12]]
        L.append("")

    # verification report, if the last command was verify
    if cmd.startswith("verify"):
        reps = sorted((root / paths.get("logs", "logs")).glob("source-verification-*.md"))
        if reps:
            txt = reps[-1].read_text("utf-8")
            head = next((ln for ln in txt.splitlines() if ln.startswith("Verified:")), "")
            failed = re.findall(r"^- \*\*(.+?)\*\* \[(.+?)\]", txt, re.M)
            L += [f"## Source verification ({reps[-1].name})", head]
            L += [f"- FAIL {p} [{g}]" for p, g in failed]
            L.append("")

    # deep dive
    if cmd.startswith("dive"):
        dv = read_jsonl(root / "data" / "dives.jsonl")
        if dv:
            d = dv[-1]
            L += [f"## Deep dive: {d['headline']}", f"{d['file']} · {len(d['sources'])} sources, {len(d['related'])} related, "
                  f"{len(d['web'])} web links kept, {len(d.get('web_dropped', []))} dead dropped", ""]

    # source suggestion queue
    if cmd.startswith(("sources", "suggest")):
        from . import suggest
        g = suggest.summary(suggest.load_store(root))
        L += [f"## Source suggestions: {len(g['pending'])} pending · {len(g['accepted'])} accepted · "
              f"{len(g['watch'])} watch · {len(g['denied'])} denied"]
        for x in g["pending"]:
            src = ", ".join(f"{v.get('channel') or v['kind']} {v['url']} ({v.get('entries', 0)}, latest {v.get('latest') or '?'}"
                            f"{', STALE' if suggest.is_stale(v, suggest.stale_days(cfg)) else ''})"
                            for v in x.get("verified") or []) or "NO LIVE WEB SOURCE"
            alt = ", ".join([f"X @{h}" for h in x.get("x") or []] + list(x.get("other") or []))
            L += [f"- `{x['id']}` **{x['name']}** ({x.get('kind', '')}{', SCRUTINY' if x.get('scrutiny') else ''}): "
                  f"{x.get('why', '')}", f"  - live: {src}" + (f" · elsewhere: {alt}" if alt else "")]
            if x.get("failed"):
                L.append("  - failed: " + "; ".join(f"{f['label']} → {f['reason']}" for f in x["failed"])[:300])
        L.append("")

    # briefing
    blog = read_jsonl(root / paths.get("briefings_log", "data/briefings.jsonl"))
    if blog:
        b = blog[-1]
        f = root / b["file"]
        L.append(f"## Latest briefing: {b['file']} (run {b['run_id']}, {len(b.get('item_ids', []))} items)")
        if f.is_file():
            md = f.read_text("utf-8")
            secs = re.findall(r"^## (.+)$", md, re.M)
            L.append("Sections: " + " · ".join(f"{s} ({_count_entries(md, s)})" for s in secs))
            tom = md.split("## Top of mind", 1)[1].split("\n## ", 1)[0].strip() if "## Top of mind" in md else ""
            if tom:
                L += ["Top of mind:"] + [re.sub(r"\s*\[\d+\]\(https?://[^)]+\)", "", ln)[:260] for ln in tom.splitlines()[:5]]
            if "quoted wording not found in source" in md:
                L.append(f"⚠ {md.count('quoted wording not found in source')} claim(s) flagged: quoted wording not found in source")
        L.append("")

    # reader feedback (replies to the daily email)
    try:
        from . import feedback as fb
        c = fb.counts(root)
        if c["total"]:
            d = fb.load(root)
            L += ["## Reader feedback",
                  f"{c['open']} open · {c['high']} high · {c['new']} not triaged · {c['total']} total (dashboard: /feedback)"]
            for it in [i for i in d["items"] if i.get("status") in fb.OPEN
                       and (i.get("triage") or {}).get("severity") == "high"][:5]:
                t = it["triage"]
                L.append(f"- {it['id']} [{t.get('category')}] {t.get('summary', '')[:160]} → {t.get('action', '')[:160]}")
            L.append("")
    except Exception:  # noqa: BLE001
        pass

    # archive
    idx = read_jsonl(root / paths.get("index", "data/index.jsonl"))
    summ_ids, n_summ = set(), 0
    sd = root / paths.get("summaries", "data/summaries")
    if sd.exists():
        for fp in sd.glob("*.jsonl"):
            rows = read_jsonl(fp)
            n_summ += len(rows)
            summ_ids |= {x["id"] for x in rows}
    pending = sum(1 for x in idx if x["id"] not in summ_ids)
    dirty = _git(root, "status", "--porcelain")
    L += ["## Archive",
          f"{len(idx)} items · {len(summ_ids)} analyzed ({n_summ} analysis records) · {pending} not yet analyzed",
          f"git: {_git(root, 'log', '-1', '--format=%h %s')[:100]}"
          + (f" · {len(dirty.splitlines())} uncommitted change(s)" if dirty else " · clean")]

    if output_file and exit_code not in (None, 0) and not runs:
        p = root / output_file
        if p.is_file():
            L += ["", "Output tail:", "```"] + p.read_text("utf-8", errors="replace").splitlines()[-25:] + ["```"]
    return "\n".join(L) + "\n"


def write(root: Path, cfg: dict, **kw) -> Path:
    text = build(root, cfg, **kw)
    out = root / cfg.get("paths", {}).get("logs", "logs") / "last-report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, "utf-8")
    return out


def as_json(root: Path, cfg: dict) -> str:
    runs = read_jsonl(root / cfg.get("paths", {}).get("runs", "data/runs.jsonl"))
    return json.dumps(runs[-1] if runs else {}, indent=1)[:20000]
