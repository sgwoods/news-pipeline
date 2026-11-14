"""Claude chooses the day's stories (selection review, 2026-11-13).

Until v0.2.60 the pick was mechanical: the cluster model's one-line ranking, then a score (the local model's
importance 1-5 plus a bonus per extra source), then caps. Claude wrote about the stories but never chose them, and the
stories were two-thirds single-source, a third led by a Bluesky post, and the brief's own beats (legal AI, physical
AI, Canadian deals) rarely reached Must read.

Now, after cluster: the top candidates (ranked, with sources, evidence, verdicts, flags and yesterday's edition) go to
the selection model once; it returns Must read, Worth knowing and Money picks with a one-line reason each, the next
five it left out and why, and a note on the lead. Code keeps the guards it always had (grounded, not sponsored, not a
homepage, per-source caps, story fatigue, the capability slot, and now a portfolio/beat slot), demoting rather than
dropping when a pick fails one. If the call fails, the old mechanical select() runs, so a run never depends on it.

Everything the model said is kept in the day's stories record under "selection" (picks, reasons, left out, lead note,
flags) for the dashboard's Selection page and the "left out today" lines in the takes email.
"""
from __future__ import annotations

import re
from collections import Counter

from . import editorial
from .editorial import _KIND_WORD, claim_of, display_name, headline_of, verdict_line, weak_lead  # noqa: F401
from .stages import prompt, _ask

POST_HOSTS = ("bsky.app", "x.com", "twitter.com", "nitter", "xcancel")


def post_only(s: dict) -> bool:
    """The story's lead is a social post with no article behind it (a Bluesky teaser of a paywalled report, say)."""
    r = s.get("lead") or {}
    if r.get("source_kind") not in ("bluesky", "x", "shared"):
        return False
    try:
        u = editorial._cite_url(r)
    except (KeyError, TypeError):
        u = r.get("url", "")
    return any(h in (u or "") for h in POST_HOSTS) or not str(u).startswith("http")


def is_beat(s: dict, cfg: dict) -> str:
    """'portfolio' / 'beat' when the lead comes from a portfolio source or a configured beat source (legal AI, robotics,
    Canadian startups: analysis.filter_keep_sources), else ''."""
    r = s.get("lead") or {}
    flags = {str(f).upper() for f in (r.get("flags") or [])}
    if flags & {str(f).upper() for f in cfg.get("filter_keep_flags", ["PORTFOLIO"])}:
        return "portfolio"
    if (r.get("person") or "") in set(cfg.get("filter_keep_sources") or []):
        return "beat"
    return ""


def flags_for(s: dict, cfg: dict) -> list:
    out = []
    if len(s.get("ids") or []) == 1:
        out.append("single-source")
    if post_only(s):
        out.append("post-only lead")
    if s.get("wire_only"):
        out.append("wire-only")
    w = weak_lead(s)
    if w:
        out.append(f"weak lead: {w}")
    if not (s.get("evidence") or {}).get("grounded", True):
        out.append("not grounded (commentary only)")
    if s.get("thread_day", 1) > 1 or s.get("continues_day"):
        out.append(f"continues: day {s.get('thread_day') or s.get('continues_day')}")
    b = is_beat(s, cfg)
    if b:
        out.append(f"{b} source")
    if (s["lead"].get("tag") or "") == "SUMMARY ONLY" and len(s.get("ids") or []) == 1:
        out.append("headline-only (full text not read)")
    return out


def candidate_block(n: int, s: dict, cfg: dict) -> str:
    r = s["lead"]
    recs = s.get("records") or [r]
    srcs = ", ".join(dict.fromkeys(display_name(x) for x in recs))[:160]
    imp = r.get("importance") or 0
    v = verdict_line(r)
    fl = flags_for(s, cfg)
    return (f"[{n}] {s.get('headline') or headline_of(r)}\n"
            f"    sources ({len(recs)}): {srcs}\n"
            f"    claim: {editorial._words(claim_of(r), 45)}\n"
            f"    so what: {editorial._words(r.get('so_what') or '', 30)}\n"
            f"    importance (local model): {imp} | {editorial.evidence_prompt_line(s).strip()}\n"
            + (f"    verdict: {v}\n" if v else "")
            + (f"    flags: {'; '.join(fl)}\n" if fl else ""))


def candidates(stories: list, cfg: dict, n: int = 25) -> list:
    """The stories the selection model sees: the top N by the existing order (cluster rank, then score), plus any
    beat/portfolio story with importance >= 3 that the order left below the cut (so the brief's own ground is at
    least considered)."""
    top = list(stories[:n])
    seen = {id(s) for s in top}
    for s in stories[n:]:
        if is_beat(s, cfg) and (s["lead"].get("importance") or 0) >= 3 and id(s) not in seen:
            top.append(s)
            seen.add(id(s))
    return top[: n + 5]


def _earlier_block(earlier: list) -> str:
    if not earlier:
        return ""
    return "YESTERDAY AND BEFORE (the last editions' stories; a candidate that continues one needs a new fact to lead):\n" + \
        "\n".join(f"  {x['day']} · {x['headline']}" for x in earlier[:25]) + "\n"


def run_select(llm, stories: list, system: str, cfg: dict, log, earlier: list | None = None,
               views: list | None = None, profile: dict | None = None) -> tuple:
    """-> (sel, record, errors). sel has the same shape as editorial.select(); record is what the model said
    (for the Selection page) or {} when the mechanical selector was used."""
    from . import houseviews
    acfg = cfg.get("analysis") or cfg
    p = profile or {}
    max_must = int(p.get("max_must_read", acfg.get("max_must_read", 5)))
    max_worth = int(p.get("max_worth_knowing", acfg.get("max_worth_knowing", 5)))
    max_money = int(acfg.get("max_money", 5))
    cands = candidates(stories, acfg, int(acfg.get("select_candidates", 25)))
    tmpl, version = prompt("select")
    e = {**editorial.EDITORIAL_DEFAULTS, **(cfg.get("editorial") or {})}
    house_rule = ("House views (listed below): when two candidates are equal, prefer the one a house view has something "
                  "to say about." if views else "")
    user = (tmpl.replace("{{audience}}", e["audience"]).replace("{{max_must}}", str(max_must))
            .replace("{{max_worth}}", str(max_worth)).replace("{{max_money}}", str(max_money))
            .replace("{{house_rule}}", house_rule).replace("{{house_views}}", houseviews.prompt_block(views or []))
            .replace("{{earlier}}", _earlier_block(earlier or []))
            .replace("{{candidates}}", "\n".join(candidate_block(i, s, acfg) for i, s in enumerate(cands, 1))))
    try:
        out = _ask(llm, system, user, 1200)
        picks = _parse(out, len(cands))
    except Exception as ex:  # noqa: BLE001 - the run never depends on this call
        log.warning("selection: %s; using the mechanical selector", str(ex)[:200])
        sel = editorial.select(stories, acfg)
        return sel, {"model": getattr(llm, "label", "?"), "prompt": version, "fallback": str(ex)[:200]}, [f"selection: {ex}"[:300]]
    sel = apply(picks, cands, stories, acfg, log)
    rec = {"model": getattr(llm, "label", "?"), "prompt": version, "lead_note": picks.get("lead_note", ""),
           "candidates": [{"n": i, "headline": s.get("headline") or headline_of(s["lead"]), "key": s.get("key"),
                           "flags": flags_for(s, acfg), "importance": s["lead"].get("importance"),
                           "sources": len(s.get("ids") or []), "fate": s.get("fate", "more"),
                           "why": s.get("pick_reason", "")} for i, s in enumerate(cands, 1)],
           "left_out": [{"n": x["n"], "headline": cands[x["n"] - 1].get("headline") or headline_of(cands[x["n"] - 1]["lead"]),
                         "why": x["why"]} for x in picks.get("left_out", []) if 1 <= x["n"] <= len(cands)]}
    return sel, rec, []


def _parse(out: dict, n: int) -> dict:
    def rows(key):
        res, seen = [], set()
        for x in out.get(key) or []:
            if not isinstance(x, dict):
                continue
            try:
                k = int(x.get("n"))
            except (TypeError, ValueError):
                continue
            if 1 <= k <= n and k not in seen:
                seen.add(k)
                res.append({"n": k, "why": editorial._one_line(str(x.get("why", "")))[:160]})
        return res
    if not isinstance(out, dict) or not out.get("must"):
        raise ValueError("selection returned no Must read picks")
    return {"must": rows("must"), "worth": rows("worth"), "money": rows("money"), "left_out": rows("left_out"),
            "lead_note": editorial._one_line(str(out.get("lead_note", "")))[:240]}


def apply(picks: dict, cands: list, stories: list, cfg: dict, log) -> dict:
    """The model's picks through the code guards: a Must read that is wire-only, ungrounded, weak-lead or post-only is
    demoted to Worth knowing with the reason appended; per-source caps hold; everything unpicked falls to Money / In
    brief by the old rules; then the capability slot and the portfolio/beat slot."""
    max_must, max_worth = int(cfg.get("max_must_read", 5)), int(cfg.get("max_worth_knowing", 5))
    max_brief, max_money = int(cfg.get("max_in_brief", 8)), int(cfg.get("max_money", 5))
    per_source, per_edition = int(cfg.get("max_stories_per_source", 2)), int(cfg.get("max_items_per_source", 3))
    must, worth, money, brief = [], [], [], []
    used, total, taken = Counter(), Counter(), set()

    def source_ok(s):
        single = len(s["ids"]) == 1
        primary = s["names"][0]
        return not (single and (used[primary] >= per_source or total[primary] >= per_edition))

    def take(s, where, why):
        s["pick_reason"], s["fate"] = why, where
        taken.add(id(s))
        if len(s["ids"]) == 1:
            used[s["names"][0]] += 1
            total[s["names"][0]] += 1
        {"must": must, "worth": worth, "money": money, "brief": brief}[where].append(s)

    for x in picks["must"]:
        s = cands[x["n"] - 1]
        if id(s) in taken:
            continue
        bad = []
        if s.get("wire_only"):
            bad.append("wire-only")
        if not (s.get("evidence") or {}).get("grounded", True):
            bad.append("not grounded")
        w = weak_lead(s)
        if w:
            s["weak_lead"] = w
            bad.append(w)
        if post_only(s):
            bad.append("post-only lead")
        if not source_ok(s):
            bad.append("source cap")
        if bad or len(must) >= max_must:
            if len(worth) < max_worth:
                take(s, "worth", f"{x['why']} (held at Worth knowing: {', '.join(bad) or 'Must read is full'})")
                log.info("selection: %s held at Worth knowing: %s", (s.get("headline") or "")[:60], ", ".join(bad) or "full")
            continue
        take(s, "must", x["why"])
    for x in picks["worth"]:
        s = cands[x["n"] - 1]
        if id(s) in taken or len(worth) >= max_worth or not source_ok(s):
            continue
        take(s, "worth", x["why"])
    for x in picks["money"]:
        s = cands[x["n"] - 1]
        if id(s) in taken or len(money) >= max_money:
            continue
        take(s, "money", x["why"])
    for x in picks.get("left_out", []):
        s = cands[x["n"] - 1]
        if id(s) not in taken:
            s["left_out_reason"] = x["why"]
    more = 0
    for s in stories:                                   # the rest, by the old rules
        if id(s) in taken:
            continue
        imp = s["lead"].get("importance") or 0
        if len(money) < max_money and imp >= 2 and editorial.is_money(s):
            take(s, "money", "deal (by rule)")
        elif len(brief) < max_brief and imp >= 2:
            take(s, "brief", "")
        else:
            more += 1
    editorial.capability_slot(must, worth, max_must)
    beat_slot(must, worth, brief, max_must, cfg)
    return {"must": must, "worth": worth, "brief": brief, "money": money, "more": more}


def beat_slot(must: list, worth: list, brief: list, max_must: int, cfg: dict) -> str:
    """One story from the brief's own ground (a portfolio or beat source: legal AI, physical AI, Canadian startups)
    among the Must reads when a grounded one with importance >= 3 waits in Worth knowing or In brief and none is in
    Must. A story the model explicitly left out (with a reason) is respected and never promoted."""
    if not must or any(is_beat(s, cfg) for s in must):
        return ""
    pool = [(s, worth) for s in worth] + [(s, brief) for s in brief]
    cands = [(s, where) for s, where in pool if is_beat(s, cfg) and (s["lead"].get("importance") or 0) >= 3
             and (s.get("evidence") or {}).get("grounded", True) and not weak_lead(s) and not post_only(s)
             and not s.get("left_out_reason")]
    if not cands:
        return ""
    best, where = cands[0]
    where.remove(best)
    if len(must) >= max_must:
        moved = must.pop()
        moved["fate"] = "worth"
        worth.insert(0, moved)
    best["beat_slot"] = True
    best["fate"] = "must"
    best["pick_reason"] = (best.get("pick_reason", "") + " (beat slot: the brief's own ground)").strip()
    must.append(best)
    return best.get("headline") or ""


def day_view(root, paths: dict, day: str) -> dict:
    """What the dashboard's Selection page shows for DAY: the selection record (picks, reasons, left out) from the
    day's stories file and, from the summaries, the items kept without the filter, rescued, and dropped."""
    import json
    from pathlib import Path as _P
    from .archive import read_jsonl
    sel, fallback = {}, ""
    sp = _P(root) / "data" / "stories" / f"{day}.jsonl"
    if sp.exists():
        recs = read_jsonl(sp)
        if recs:
            sel = recs[-1].get("selection") or {}
            fallback = sel.get("fallback", "") if sel else ""
            if sel and sel.get("fallback"):
                sel = {}
    protected, rescued, dropped = [], [], []
    sm = _P(paths.get("summaries", _P(root) / "data" / "summaries")) / f"{day}.jsonl"
    seen = set()
    for r in (read_jsonl(sm) if sm.exists() else []):
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        row = {"id": r.get("id"), "person": r.get("person", ""), "title": (r.get("title") or r.get("headline") or "")[:140],
               "url": r.get("url", ""), "reason": r.get("filter_reason", ""), "rule": False}
        reason = row["reason"] or ""
        if r.get("keep") is False:
            row["rule"] = any(k in reason for k in ("duplicate", "excluded URL", "empty", "own LinkedIn", "no real text"))
            dropped.append(row)
        elif reason.startswith("kept without the model filter"):
            row["reason"] = reason.split(":", 1)[-1].strip()
            protected.append(row)
        elif reason.startswith("rescued"):
            row["reason"] = reason.split(":", 1)[-1].strip()
            rescued.append(row)
    return {"sel": sel, "fallback": fallback, "protected": protected, "rescued": rescued, "dropped": dropped,
            "model_drops": sum(1 for d in dropped if not d["rule"]), "rule_drops": sum(1 for d in dropped if d["rule"])}
