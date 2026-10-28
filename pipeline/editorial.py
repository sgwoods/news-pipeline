"""Briefing v2: stories, not items.

cluster   group records about the same story (local model, one call)      → stories
select    rank stories, balance sources, pick Must read / Worth knowing / In brief (code)
merge     one combined account per multi-source story (local model, a call per story)
editorial day-in-brief + Top of mind + Editor's view lines (Claude, one call)
render    Markdown; every link and the layout come from code, never from the model
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter

from . import houseviews
from .stages import _ask, _one_line, display_name, prompt

VERDICT_ORDER = {"unsupported": 0, "overstated": 1, "unverified": 2, "mixed": 2, "holds": 3}
# Aggregator / mass-market tiers (newsletters.yaml): their items can never lead a story on their own.
WIRE_TIERS = {"wire", "coverage-check", "own"}
_NO_AGENDA = re.compile(r"^(none|n/?a|no (clear |apparent |direct |obvious )?(conflict|agenda|slant))", re.I)


def _words(s: str, n: int) -> str:
    w = (s or "").split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def _sentences(s: str, n: int) -> str:
    """Whole sentences up to about n words (never cut mid-sentence unless the first one is too long)."""
    parts = re.split(r"(?<=[.!?])\s+", _one_line(s))
    out, count = [], 0
    for p in parts:
        k = len(p.split())
        if out and count + k > n:
            break
        out.append(p)
        count += k
    text = " ".join(out)
    return text if len(text.split()) <= n + 15 else _words(text, n)


def story_key(ids: list) -> str:
    return hashlib.sha1(",".join(sorted(ids)).encode()).hexdigest()[:12]


def headline_of(r: dict) -> str:
    return r.get("headline") or _one_line(r.get("title", ""))[:120] or "(untitled)"


def claim_of(r: dict) -> str:
    c = (r.get("critique_detail") or {}).get("corrected_claim") or r.get("claim") or ""
    return _one_line(c)


def verdict_of(r: dict) -> str:
    return (r.get("critique_detail") or {}).get("verdict", "")


def verdict_line(r: dict) -> str:
    d = r.get("critique_detail") or {}
    if not d:
        return ""
    reason = d.get("one_line") or _words(d.get("overstated", ""), 25)
    return f"{d['verdict'].capitalize()}. {_one_line(reason)}".strip()


# ---------- cluster ----------

def run_cluster(llm, records: list, system: str, cfg: dict, log) -> tuple:
    """→ (stories, prompt_version, errors). A story = {"ids": [...], "headline": str|None}."""
    tmpl, version = prompt("cluster")
    recs = sorted(records, key=lambda r: -(r.get("importance") or 0))[: cfg.get("cluster_max_items", 80)]
    num = {n: r["id"] for n, r in enumerate(recs, 1)}
    listing = "\n".join(f"[{n}] {display_name(r)} | {headline_of(r)} | {_words(claim_of(r), 28)}"
                        for n, r in enumerate(recs, 1))
    groups, errors, used, top = [], [], set(), []
    try:
        out = _ask(llm, system, tmpl.replace("{{entries}}", listing), 1500)
        for g in out.get("stories", []) if isinstance(out, dict) else []:
            ns = list(dict.fromkeys(int(x) for x in (g.get("items") or [])
                                    if str(x).isdigit() and int(x) in num and int(x) not in used))
            if len(ns) >= 2:
                used.update(ns)
                groups.append({"ids": [num[n] for n in ns], "headline": _one_line(g.get("headline", ""))[:140] or None})
        top = [num[int(x)] for x in (out.get("top") or []) if str(x).isdigit() and int(x) in num]
    except Exception as e:  # noqa: BLE001 - clustering is an improvement, never a blocker
        errors.append(f"cluster: {type(e).__name__}: {e}"[:300])
        log.warning("cluster failed, using single stories: %s", e)
    grouped = {i for g in groups for i in g["ids"]}
    stories = groups + [{"ids": [r["id"]], "headline": None} for r in records if r["id"] not in grouped]
    rank = {}
    for pos, i in enumerate(top):
        for s in stories:
            if i in s["ids"] and "rank" not in s:
                s["rank"] = pos
    log.info("cluster: editor ranking covers %d stories", sum(1 for s in stories if "rank" in s))
    log.info("cluster: %d records → %d stories (%d multi-source)", len(records), len(stories), len(groups))
    return stories, version, errors


# ---------- select ----------

def build_stories(stories: list, by_id: dict) -> list:
    out = []
    for s in stories:
        recs = [by_id[i] for i in s["ids"] if i in by_id]
        if not recs:
            continue
        recs.sort(key=lambda r: (-(r.get("importance") or 0), r.get("tag") != "FULL READ",
                                 -VERDICT_ORDER.get(verdict_of(r), 2)))
        lead = recs[0]
        size = len(recs)
        score = max(r.get("importance") or 0 for r in recs) + (1.0 if size >= 3 else 0.5 if size == 2 else 0)
        score += 0.3 if any(r.get("tag") == "FULL READ" for r in recs) else 0
        if size == 1 and verdict_of(lead) == "unsupported":
            score -= 0.5
        names = distinct_names(list(dict.fromkeys(display_name(r) for r in recs)))
        wire_only = all((r.get("tier") or "") in WIRE_TIERS for r in recs)
        from .profiles import evidence
        ev = evidence(recs)
        out.append({"key": story_key(s["ids"]), "ids": [r["id"] for r in recs], "records": recs, "lead": lead,
                    "wire_only": wire_only, "evidence": ev,
                    "headline": s.get("headline") or headline_of(lead), "names": names, "score": round(score, 2),
                    "published": max(r.get("published") or "" for r in recs), "rank": s.get("rank")})
    out.sort(key=lambda s: s["published"], reverse=True)       # newest first within equal scores
    out.sort(key=lambda s: -s["score"])
    # The cluster model's importance ranking (when given) decides the order of the stories it ranked;
    # unranked stories follow in score order.
    out.sort(key=lambda s: (s["rank"] is None, s["rank"] if s["rank"] is not None else 0))
    return out


_SPONSORED = re.compile(r"\b(sponsored by|sponsored content|paid partnership|presented by|register (?:now|today)|"
                        r"webinar|on-demand demo|book a demo)\b", re.I)


def weak_lead(s: dict) -> str:
    """Why the story's lead can't carry a Must read ('' if it can): a sponsored or webinar page, or a link to a bare
    homepage rather than an article (critic, 2026-10-24: a vendor-sponsored webinar page became a Must read)."""
    from urllib.parse import urlparse
    r = s.get("lead") or {}
    try:
        u = _cite_url(r) if r.get("url") else ""
    except (KeyError, TypeError):
        u = ""
    if u and urlparse(u).path.strip("/") == "" and not urlparse(u).query:
        return "the source link is a homepage, not an article"
    text = " ".join(str(r.get(k) or "") for k in ("title", "description", "text"))[:4000]
    if _SPONSORED.search(text):
        return "the source is sponsored or a webinar page"
    return ""


def select(stories: list, cfg: dict) -> dict:
    max_must, max_worth = cfg.get("max_must_read", 6), cfg.get("max_worth_knowing", 8)
    max_brief, per_source = cfg.get("max_in_brief", 8), cfg.get("max_stories_per_source", 2)
    per_edition = int(cfg.get("max_items_per_source", 3))
    must, worth, brief, more = [], [], [], 0
    used, total = Counter(), Counter()
    for s in stories:
        primary = s["names"][0]
        single = len(s["ids"]) == 1
        if single and total[primary] >= per_edition:       # no more than N items a day from one source
            more += 1
            continue
        total[primary] += 1 if single else 0
        over = single and used[primary] >= per_source
        imp = s["lead"].get("importance") or 0
        ranked = s.get("rank") is not None
        grounded = (s.get("evidence") or {}).get("grounded", True)   # a primary source or a report
        weak = weak_lead(s)
        if weak:
            s["weak_lead"] = weak
        if not over and not s.get("wire_only") and grounded and not weak and len(must) < max_must and (s["score"] >= 4 or (ranked and s["score"] >= 3)):
            must.append(s)
        elif not over and len(worth) < max_worth and s["score"] >= 3:
            worth.append(s)
        elif len(brief) < max_brief and imp >= 2:
            brief.append(s)
            continue
        else:
            more += 1
            continue
        if single:
            used[primary] += 1
    return {"must": must, "worth": worth, "brief": brief, "more": more}


# ---------- merge ----------

def _rec_block(r: dict) -> str:
    return (f"<item>\nsource: {display_name(r)}\nheadline: {headline_of(r)}\nclaim: {claim_of(r)}\n"
            f"critical pass: {verdict_line(r) or 'not run'}\n</item>")


def run_merge(llm, stories: list, system: str, log) -> tuple:
    tmpl, version = prompt("merge")
    errors = []
    for s in stories:
        if len(s["records"]) < 2:
            continue
        try:
            out = _ask(llm, system, tmpl.replace("{{items}}", "\n\n".join(_rec_block(r) for r in s["records"])), 600)
            s["what_happened"] = _one_line(out.get("what_happened", ""))
            s["critical_pass"] = _one_line(out.get("critical_pass", ""))
        except Exception as e:  # noqa: BLE001
            errors.append(f"merge {s['key']}: {type(e).__name__}: {e}"[:300])
            log.warning("merge failed for story %s: %s", s["key"], e)
    return version, errors


# ---------- editorial ----------

EDITORIAL_DEFAULTS = {
    "audience": "an early-stage (seed to Series A) AI investor",
    "focus": "what it means for an early-stage AI investor, a question worth exploring in diligence, or where we read the source differently",
    "tone": "Your own judgement, plain and direct.",
}


HOUSE_RULE = (
    "HOUSE VIEWS (listed just above the stories as V1, V2, ...): each Our read takes its position under the "
    "ONE house view that fits the story best, and says which way we lean (\"We think...\"). Return each editor_view "
    "as {\"text\": ..., \"view\": <the view's number>, \"changes\": what specific evidence would change our mind about "
    "THIS story (at most 15 words)}. A view is a lens, not a conclusion: when the facts point against the view, say "
    "so plainly. Use 0 for \"view\" when no view fits; never force one. Never quote or paraphrase anyone as holding "
    "the view: house views are \"our\" views. Never write a view's number (V7) in any text: readers see its name.\n"
    "3d. \"lead_case\": for MUST READ story 1 only, the bull and bear cases in their strongest honest form: "
    "{\"for\": the case for (at most 30 words), \"against\": the case against (at most 30 words), \"deciding\": the one "
    "question whose answer decides between them (at most 20 words), \"lean\": which way we lean and why, under its "
    "house view (at most 25 words)}. Facts from the story only. No stock counter-view on any other story.\n")


def _unnumber(text: str) -> str:
    """View numbers are for the model (V7); readers see the view's name on the line. "Under V7, we lean..." -> "We lean..."."""
    t = re.sub(r"(?i)\b(?:under|per|by|following|via)\s+(?:(?:our|the)\s+)?(?:house\s+view\s+)?V\d{1,2}\b\s*[,:;]?\s*", "", text)
    t = re.sub(r"\(\s*V\d{1,2}\s*\)\s*", "", t)
    t = re.sub(r"\b(?:house view\s+)?V\d{1,2}\b", "our house view", t).strip()
    return t[:1].upper() + t[1:] if t else t


def merged(cfg: dict) -> bool:
    """briefing.top_format "merged": one 5-bullet "Today in 30 seconds" replaces the day in brief and Top of mind."""
    return str((cfg.get("analysis") or {}).get("top_format", "separate")) == "merged"


def top_count(cfg: dict) -> int:
    return 5 if merged(cfg) else int((cfg.get("analysis") or {}).get("top_of_mind", 4))


_QUESTION = re.compile(r"(?i)A question worth asking in diligence this week:\s*(.+)$")


def diligence_question(day_in_brief: str) -> str:
    m = _QUESTION.search(day_in_brief or "")
    if m:
        return m.group(1).strip()
    qs = [s for s in re.split(r"(?<=[.!?])\s+", day_in_brief or "") if s.endswith("?")]
    return qs[-1].strip() if qs else ""


def editorial_prompt(tmpl: str, lines: list, cfg: dict, earlier: list, views: list | None = None) -> str:
    """Fill the editorial template from the tuning profile (cfg = {"analysis": ..., "editorial": ...})."""
    a, e = cfg.get("analysis") or {}, {**EDITORIAL_DEFAULTS, **(cfg.get("editorial") or {})}
    n_top, n_q = top_count(cfg), int(a.get("open_questions", 0))
    top_rule = (f"exactly {n_top} bullets ({n_top - 1} if there are only {n_top - 1} stories)." if n_top > 1
                else "exactly 1 bullet." if n_top == 1 else "return an empty list [].")
    if merged(cfg):
        top_rule += (" These bullets open the edition on their own, as \"Today in 30 seconds\": the day's two or three "
                     "main threads first, then the next most important, each a different story. So the day_in_brief "
                     "is only its last sentence, the diligence question (\"A question worth asking in diligence this "
                     "week: ...\").")
    q_rule = ("return an empty list []." if n_q <= 0 else
              f"{n_q} questions worth following up in the coming days or weeks: things a careful investor would "
              "want settled, not rhetorical ones. Each has \"q\" (at most 25 words), \"why\" it matters (at most "
              "20 words), \"settle\": what evidence or event would answer it (at most 20 words), and \"refs\".")
    if earlier:
        c_rule = ("for today's stories that continue a story from the last days (listed under EARLIER STORIES as E1, "
                  "E2, ...), map today's story number to the earlier one. Only when it is clearly the same developing "
                  "story (same event and its consequences), not the same broad topic. Otherwise return {}.")
        earlier_block = "EARLIER STORIES (from previous briefings):\n" + "\n".join(
            f"[E{n}] {x['day']} · {x['headline']}" for n, x in enumerate(earlier, 1))
    else:
        c_rule, earlier_block = "return {} (no earlier stories today).", ""
    return (tmpl.replace("{{audience}}", e["audience"]).replace("{{focus}}", e["focus"].rstrip("."))
            .replace("{{tone}}", e["tone"]).replace("{{top_rule}}", top_rule)
            .replace("{{questions_rule}}", q_rule).replace("{{continues_rule}}", c_rule)
            .replace("{{house_views_rule}}", HOUSE_RULE if views else "")
            .replace("{{house_views}}", houseviews.prompt_block(views or []))
            .replace("{{stories}}", "\n".join(lines)).replace("{{earlier}}", earlier_block))


def run_editorial(llm, sel: dict, system: str, log, cfg: dict | None = None, earlier: list | None = None,
                  views: list | None = None) -> tuple:
    """views: house_views.md (pipeline/houseviews.py); none -> Our read as before, with no view or lead case."""
    tmpl, version = prompt("editorial")
    views = views or []
    names = {v.n: v.name for v in views}
    known = set(names)
    cfg = cfg or {}
    earlier = earlier or []
    numbered = sel["must"] + sel["worth"]
    if not numbered:
        return {}, version, []
    lines = []
    for n, s in enumerate(numbered, 1):
        tag = "MUST READ" if s in sel["must"] else "WORTH KNOWING"
        what = s.get("what_happened") or claim_of(s["lead"])
        crit = s.get("critical_pass") or verdict_line(s["lead"]) or "not run"
        pub = (s.get("published") or "")[:10]
        lines.append(f"[{n}] ({tag}) {s['headline']} | sources: {', '.join(s['names'])}"
                     + (f" | published {pub}" if pub else "") + "\n"
                     f"    what happened: {what}\n    critical pass: {crit}\n" + evidence_prompt_line(s)
                     + "\n    readable sources: " + "; ".join(f"{display_name(r)} ({profile_kind(r)}): {headline_of(r)[:80]}"
                                                       for r in s["records"][:5]))
    try:
        out = _ask(llm, system, editorial_prompt(tmpl, lines, cfg, earlier, views), 2400 + (600 if views else 0))
    except Exception as e:  # noqa: BLE001
        log.warning("editorial failed: %s", e)
        return {}, version, [f"editorial: {type(e).__name__}: {e}"[:300]]
    n_top = top_count(cfg)
    n_q = int((cfg.get("analysis") or {}).get("open_questions", 0))
    ed = {"day_in_brief": _one_line(out.get("day_in_brief", "")), "top_of_mind": [], "editor_view": {},
          "open_questions": []}
    def refs_of(x):
        return [int(r) for r in (x.get("refs") or []) if str(r).isdigit() and 1 <= int(r) <= len(numbered)]
    for b in out.get("top_of_mind", []) or []:
        if isinstance(b, dict) and b.get("text"):
            ed["top_of_mind"].append({"lead": _one_line(b.get("lead", "")).rstrip("."), "text": _one_line(b["text"]),
                                      "refs": refs_of(b)})
    for q in out.get("open_questions", []) or []:
        if isinstance(q, dict) and q.get("q"):
            ed["open_questions"].append({"q": _one_line(q["q"]), "why": _one_line(q.get("why", "")),
                                         "settle": _one_line(q.get("settle", "")), "refs": refs_of(q)})
    ev = out.get("editor_view") or {}
    for n, s in enumerate(numbered, 1):
        v = ev.get(str(n)) or ev.get(n)
        if isinstance(v, dict):
            text = _unnumber(_one_line(str(v.get("text") or "")))
            if text:
                s["editor_view"] = text
                try:
                    vn = int(str(v.get("view") or 0).lstrip("Vv") or 0)
                except ValueError:
                    vn = 0
                if vn in known:
                    s["house_view"] = vn
                    s["house_view_name"] = names[vn]
                if v.get("changes") and vn in known:
                    s["changes_our_mind"] = _one_line(str(v["changes"]))
        elif v:
            s["editor_view"] = _one_line(v)
    lc = out.get("lead_case") if views else None
    if isinstance(lc, dict) and sel["must"]:
        case = {k: _unnumber(_one_line(str(lc.get(k) or ""))) for k in ("for", "against", "deciding", "lean")}
        if all(case.values()):
            sel["must"][0]["lead_case"] = case
    es = out.get("early_stage") or {}
    for n, s in enumerate(sel["must"], 1):
        v = es.get(str(n)) or es.get(n)
        if v and _one_line(v):
            s["early_stage"] = _one_line(v)
    lenses = {"The AGI-forward view", "The AI-realist view", "The market view", "The policy view"}
    ol = out.get("other_lens") or {}
    used = 0
    for n, s in enumerate(numbered, 1):
        v = ol.get(str(n)) or ol.get(n)
        if isinstance(v, dict) and v.get("text") and used < 3:
            lens = re.sub(r"(?i)the (sceptic|skeptic)('s|s')? view", "The AI-realist view",
                          str(v.get("lens", ""))).replace("AGI forward", "AGI-forward").replace("AI realist", "AI-realist").strip()
            if lens in lenses:
                s["other_lens"] = {"lens": lens, "text": _one_line(v["text"])}
                used += 1
    cont = out.get("continues") or {}
    for n, s in enumerate(numbered, 1):
        ref = str(cont.get(str(n)) or cont.get(n) or "").strip().upper().lstrip("E")
        if ref.isdigit() and 1 <= int(ref) <= len(earlier):
            prev = earlier[int(ref) - 1]
            s["thread"] = prev["thread"]
            s["continues"] = prev["key"]
    rr = out.get("recommended_reading") or {}
    try:
        n = int(rr.get("n", 0))
    except (TypeError, ValueError):
        n = 0
    if 1 <= n <= len(numbered) and rr.get("why"):
        s = numbered[n - 1]
        r = recommended_record(s, str(rr.get("source") or ""))
        ed["recommended_reading"] = {"n": n, "key": s.get("key"), "id": r.get("id"), "why": _one_line(rr["why"]),
                                     "title": headline_of(r), "who": display_name(r), "kind": profile_kind(r),
                                     "url": _cite_url(r)}
    ed["top_of_mind"] = ed["top_of_mind"][: max(n_top, 0) or 5] if n_top else []
    if merged(cfg):
        ed["top_format"] = "merged"
    ed["open_questions"] = ed["open_questions"][:n_q] if n_q > 0 else []
    return ed, version, []


# ---------- threads (developing stories across days) ----------

def latest_story_records(stories_dir, before_day: str, days: int) -> list:
    """The last story record of each of the `days` days before `before_day` (oldest first)."""
    from .archive import read_jsonl
    from pathlib import Path
    d = Path(stories_dir)
    if not d.exists():
        return []
    start = (dt.date.fromisoformat(before_day) - dt.timedelta(days=days)).isoformat()
    out = []
    for f in sorted(d.glob("????-??-??.jsonl")):
        if start <= f.stem < before_day:
            rows = read_jsonl(f)
            if rows:
                out.append(rows[-1])
    return out


def earlier_stories(stories_dir, day: str, days: int = 7, limit: int = 40) -> list:
    """Candidates for "continues": recent stories with their thread ids, newest first."""
    out = []
    for rec in reversed(latest_story_records(stories_dir, day, days)):
        for s in rec.get("stories", []):
            if s.get("section") in ("must", "worth", "brief"):
                out.append({"day": rec["day"], "key": s["key"], "headline": s["headline"],
                            "thread": s.get("thread") or s["key"]})
    return out[:limit]


def thread_index(stories_dir) -> dict:
    """thread id → [{day, key, headline, section, n}] across every briefing (latest record per day)."""
    from .archive import read_jsonl
    from pathlib import Path
    d = Path(stories_dir)
    idx: dict = {}
    for f in sorted(d.glob("????-??-??.jsonl")) if d.exists() else []:
        rows = read_jsonl(f)
        if not rows:
            continue
        rec = rows[-1]
        for s in rec.get("stories", []):
            t = s.get("thread") or s["key"]
            idx.setdefault(t, []).append({"day": rec["day"], "key": s["key"], "headline": s["headline"],
                                          "section": s.get("section"), "n": s.get("n"),
                                          "names": s.get("names", []), "lead_url": s.get("lead_url", "")})
    return idx


def mark_threads(sel: dict, stories_dir, day: str) -> None:
    """Give each selected story its thread id and how many earlier days the thread has."""
    idx = thread_index(stories_dir)
    for s in sel["must"] + sel["worth"] + sel["brief"]:
        t = s.get("thread") or s["key"]
        s["thread"] = t
        prior_days = sorted({x["day"] for x in idx.get(t, []) if x["day"] < day})
        s["thread_day"] = len(prior_days) + 1
        s["thread_first"] = prior_days[0] if prior_days else day


# ---------- render ----------

_PIPELINE_TALK = re.compile(r"[^.!?]*\b(?:no critical pass (?:was )?run|critical pass was not run|the item does not "
                            r"(?:say|state|mention|specify)|the item doesn't say|link shortener|not the source\b)[^.!?]*[.!?]?\s*", re.I)


def _clean(s: str) -> str:
    """Pipeline vocabulary never reaches readers ("No critical pass was run.", "The item does not say ...")."""
    return re.sub(r"\s{2,}", " ", _PIPELINE_TALK.sub(" ", s or "")).strip()


def _md(s: str) -> str:
    return _clean(_one_line(s)).replace("[", "(").replace("]", ")")


_MONEY_WORD = re.compile(r"([$€£])\s?(\d[\d,]*(?:\.\d+)?)\s?(bn|billion|mn|million|m|tn|trillion|B|M|T)\b(?!-)")
_SCALE = {"bn": "B", "billion": "B", "b": "B", "mn": "M", "million": "M", "m": "M", "tn": "T", "trillion": "T", "t": "T"}


_KIND_WORD = {"primary": "primary source", "reporting": "report", "analysis": "analysis", "opinion": "opinion",
              "aggregator": "summary", "social": "post", "unknown": "source", "tested": "hands-on test"}


def profile_kind(r: dict) -> str:
    from .profiles import profile
    p = profile(r)
    return "hands-on test" if p["kind"] == "analysis" and p.get("tests") else p["kind"]


def recommended_record(s: dict, source: str = "") -> dict:
    """The one record of a story to read in full: the one the editor named, else the best long read."""
    recs = s.get("records") or [s["lead"]]
    if source:
        for r in recs:
            if source.lower() in display_name(r).lower() or display_name(r).lower() in source.lower():
                return r
    rank = {"hands-on test": 0, "analysis": 1, "reporting": 2, "primary": 3, "opinion": 4}
    return sorted(recs, key=lambda r: (rank.get(profile_kind(r), 9), -(r.get("importance") or 0)))[0]


def evidence_byline(s: dict) -> str:
    """' · primary source + 2 reports + 3 commentaries' (or ' · opinion' for a single source)."""
    from .profiles import evidence, evidence_label, profile
    recs = s.get("records") or [s["lead"]]
    if len(recs) == 1:
        p = profile(recs[0])
        return f" · {_KIND_WORD['tested'] if p['kind'] == 'analysis' and p.get('tests') else _KIND_WORD.get(p['kind'], 'post')}"
    lab = evidence_label(s.get("evidence") or evidence(recs))
    return f" · {lab}" if lab else ""


def evidence_prompt_line(s: dict) -> str:
    """For the editorial model: how well grounded the story is and who brings which stance or interest."""
    from .profiles import evidence, evidence_label, profile
    recs = s.get("records") or [s["lead"]]
    ev = s.get("evidence") or evidence(recs)
    stances = "; ".join(f"{k}: {', '.join(v)}" for k, v in ev["stances"].items()) or "none marked"
    interests = "; ".join(sorted({f"{profile(r).get('name') or profile(r).get('site')}: {profile(r)['interests']}"
                                  for r in recs if profile(r).get("interests")}))
    return (f"    evidence: {evidence_label(ev) or 'none'}{'' if ev['grounded'] else ' (no primary source, report or hands-on test)'}"
            f" | stances: {stances}" + (f" | interests: {interests}" if interests else ""))


def money_style(text: str) -> str:
    """One house style for amounts: $12.6B, $300M, $1T. Text inside quotation marks is left verbatim."""
    parts = re.split(r'("[^"\n]*"|“[^”\n]*”)', text or "")
    for i in range(0, len(parts), 2):
        parts[i] = _MONEY_WORD.sub(lambda m: f"{m.group(1)}{m.group(2)}{_SCALE[m.group(3).lower()]}", parts[i])
    return "".join(parts)


def _cite_url(r: dict) -> str:
    """The article behind a wire post: a Bluesky post that links out is cited by the article it points to."""
    from .links import is_tracker
    link = r.get("linked_url") or ""
    if r.get("source_kind") in ("bluesky", "shared") and link.startswith("http") and "bsky.app" not in link \
            and not is_tracker(link):
        return link
    if is_tracker(r.get("url", "")):                  # personal newsletter click-tracker: never cite it
        pub = r.get("public_url") or ""
        return pub if pub.startswith("http") and not is_tracker(pub) else (r.get("web") or "")
    return r["url"]


def _cite_label(r: dict) -> str:
    link = _cite_url(r)
    if link != r["url"]:
        from .stages import _host
        return f"{_host(link)} via {display_name(r)}"
    return display_name(r)


def _link(r: dict, label: str = "") -> str:
    u = _cite_url(r)
    return f"[{label or _cite_label(r)}]({u})" if u else (label or _cite_label(r))


def _base_name(n: str) -> set:
    """'Marcus on AI (Gary Marcus)' -> {'marcus on ai', 'gary marcus'}: one author is one source."""
    n = n.lower().strip()
    inner = re.findall(r"\(([^)]+)\)", n)
    outer = re.sub(r"\s*\([^)]*\)", "", n).strip()
    return {x.strip() for x in [outer] + inner if x.strip()}


def distinct_names(names: list) -> list:
    out, seen = [], []
    for n in names:
        b = _base_name(n)
        if any(b & s for s in seen):
            continue
        seen.append(b)
        out.append(n)
    return out


def _age(published: str, day: str) -> str:
    """'from Fri Oct 9' when an item is more than two days older than the edition, else ''."""
    try:
        p = dt.date.fromisoformat((published or "")[:10])
        d = dt.date.fromisoformat(day)
    except ValueError:
        return ""
    return f"from {p.strftime('%a %b')} {p.day}" if (d - p).days > 2 else ""


VERDICT_LABEL = {"holds": "Holds", "overstated": "Overstated", "unsupported": "Unsupported", "mixed": "Mixed",
                 "too early": "Too early", "unverified": "Unverified"}
_LABEL_RE = re.compile(r"^(holds|overstated|unsupported|mixed|too early|unverified)\b[.:]?\s*", re.I)


_NOT_SOLID = re.compile(r"\b(self-reported|self-assessed|unverified|not (?:yet )?(?:independently )?(?:verified|confirmed|"
                        r"replicated|reproduced)|no independent|untested|unconfirmed|vendor-reported|company-reported)\b",
                        re.I)


def label_fits(label: str, text: str) -> str:
    """'Holds' only when the evidence line itself doesn't say the claim is self-reported or unverified (critic,
    2026-10-24: 'Holds. Self-reported benchmarks unverified'). Such a line is labelled 'Unverified' instead."""
    return "Unverified" if label == "Holds" and _NOT_SOLID.search(text or "") else label


def critical_line(s: dict, r: dict) -> str:
    """The critical pass always opens with its verdict word (Holds / Overstated / Unsupported / Mixed / Too early)."""
    crit = _clean(_one_line(s.get("critical_pass") or verdict_line(r)))
    if not crit:
        return ""
    m = _LABEL_RE.match(crit)
    if m:
        rest = crit[m.end():].strip()
        return label_fits(VERDICT_LABEL[m.group(1).lower()], rest) + ". " + rest
    v = verdict_of(r)
    return f"{label_fits(VERDICT_LABEL[v], crit)}. {crit}" if v in VERDICT_LABEL else crit


def _agenda(r: dict) -> str:
    a = _one_line(r.get("agenda_flag", ""))
    return "" if not a or _NO_AGENDA.match(a) else a


def _developing(s: dict) -> str:
    first = dt.date.fromisoformat(s["thread_first"])
    return f"Developing story · day {s['thread_day']} · first in the briefing {first.strftime('%b')} {first.day}"


def render(day: str, sel: dict, ed: dict, meta: dict) -> tuple:
    date = dt.date.fromisoformat(day)
    numbered = sel["must"] + sel["worth"]
    url = {n: u for n, s in enumerate(numbered, 1) if (u := _cite_url(s["lead"]))}
    L = [f"# AI Briefing · {date.strftime('%A, %B')} {date.day}, {date.year}", ""]
    if ed.get("top_format") == "merged" and ed.get("top_of_mind"):
        from .textutil import QUESTION_LEAD, TOP_MERGED
        L += [f"## {TOP_MERGED}", ""]
        for b in ed["top_of_mind"]:
            links = " ".join(f"[{n}]({url[n]})" for n in b["refs"] if n in url)
            lead = f"**{_md(b['lead'])}.** " if b.get("lead") else ""
            L.append(f"- {lead}{_md(b['text'])} {links}".rstrip())
        q = diligence_question(ed.get("day_in_brief", ""))
        L += [""] + ([f"{QUESTION_LEAD} {_md(q)}", ""] if q else [])
    if ed.get("day_in_brief") and ed.get("top_format") != "merged":
        L += [f"**The day in brief.** {_md(ed['day_in_brief'])}", ""]
    if ed.get("top_of_mind") and ed.get("top_format") != "merged":
        L += ["## Top of mind", ""]
        for b in ed["top_of_mind"]:
            links = " ".join(f"[{n}]({url[n]})" for n in b["refs"] if n in url)
            lead = f"**{_md(b['lead'])}.** " if b.get("lead") else ""
            L.append(f"- {lead}{_md(b['text'])} {links}".rstrip())
        L.append("")
    if sel["must"]:
        L += ["## Must read", ""]
        for n, s in enumerate(sel["must"], 1):
            r = s["lead"]
            multi = len(s["records"]) > 1
            scr = ""                                  # tier tags stay internal (format spec)
            age = _age(s.get("published") or r.get("published", ""), day)
            when = f" · {age}" if age else (f" · {r['published'][:10]}" if r.get("published") and not multi else "")
            count = evidence_byline(s)
            L += [f"### {n}. {_md(s['headline'])}",
                  f"**{' · '.join(s['names'])}**{scr}{count}" + (f" · [source]({_cite_url(r)})" if _cite_url(r) else "") + when, ""]
            if s.get("thread_day", 1) > 1:
                L += [f"*{_developing(s)}*", ""]
            L.append(f"- **What happened:** {_md(s.get('what_happened') or claim_of(r))}")
            if r.get("so_what") and r.get("so_what") != "n/a" and not s.get("editor_view"):
                L.append(f"- **So what:** {_md(r['so_what'])}")   # the Editor's view replaces it when present
            if not multi and _agenda(r):
                L.append(f"- **Agenda:** {_md(_agenda(r))}")
            crit = critical_line(s, r)
            if crit:
                L.append(f"- **Evidence check:** {_md(crit)}")
            if s.get("editor_view"):
                hv = f" *(House view: {_md(s['house_view_name'])})*" if s.get("house_view_name") else ""
                L.append(f"- **Our read:** {_md(s['editor_view'])}{hv}")
            if s.get("lead_case"):
                c = s["lead_case"]
                L += [f"- **The case for:** {_md(c['for'])}", f"- **The case against:** {_md(c['against'])}",
                      f"- **The deciding question:** {_md(c['deciding'])}", f"- **Our lean:** {_md(c['lean'])}"]
            if s.get("early_stage"):
                L.append(f"- **For early-stage:** {_md(s['early_stage'])}")
            if s.get("other_lens") and not s.get("lead_case"):
                L.append(f"- **{s['other_lens']['lens']}:** {_md(s['other_lens']['text'])}")
            if multi:
                recs = s["records"]
                shown = recs[:4]
                more_n = len(recs) - len(shown)
                L.append("- **Sources:** " + " · ".join(_link(x, f"{_cite_label(x)}: {_words(headline_of(x), 8)}")
                                                         for x in shown) + (f" · +{more_n} more" if more_n > 0 else ""))
            L.append("")
    if sel["worth"]:
        L += ["## Worth knowing", ""]
        for n, s in enumerate(sel["worth"], len(sel["must"]) + 1):
            r = s["lead"]
            v = verdict_of(r)
            flag = f" *Evidence check: {v}.*" if v in ("overstated", "unsupported") else ""
            what = s.get("what_happened") or claim_of(r)
            links = ", ".join(_link(x) for x in s["records"])
            h = _md(s["headline"])
            h = h if h[-1:] in ".?!" else h + "."
            dev = f" *{_developing(s)}.*" if s.get("thread_day", 1) > 1 else ""
            age = _age(s.get("published") or r.get("published", ""), day)
            dev += f" *({age[5:]})*" if age else ""
            L.append(f"- **{n}. {h}** {_md(_sentences(what, 40))}{flag}{dev} ({links})")
        L.append("")
    rr = ed.get("recommended_reading")
    if rr and rr.get("url"):
        kind = {"primary": "primary source", "reporting": "report"}.get(rr["kind"], rr["kind"])
        L += ["## Recommended reading", "",
              f"**[{_md(rr['title'])}]({rr['url']})** · {rr['who']} · {kind}", "",
              f"*Why it matters:* {_md(rr['why'])}", ""]
    if sel["brief"]:
        L += ["## In brief", ""]
        for s in sel["brief"]:
            L.append(f"- {_md(s['headline'])} ({', '.join(_link(x) for x in s['records'])})")
        L.append("")
    if ed.get("open_questions"):
        L += ["## Open questions", ""]
        for q in ed["open_questions"]:
            links = " ".join(f"[{n}]({url[n]})" for n in q.get("refs", []) if n in url)
            why = f" {_md(q['why'])}" if q.get("why") else ""
            settle = f" *Settled by: {_md(q['settle']).rstrip('.')}.*" if q.get("settle") else ""
            L.append(f"- **{_md(q['q'])}**{why}{settle} {links}".rstrip())
        L.append("")
    total = sum(len(s["records"]) for k in ("must", "worth", "brief") for s in sel[k])
    L += ["---", f"*{meta.get('n_items', total)} items analyzed from {meta.get('n_sources', '?')} sources"
          f" · {meta.get('dropped', 0)} filtered as off-topic · {sel['more']} more stories in the dashboard."
          f" Analysis: {meta.get('models', '')}. Our read, the other views and the day in brief are machine-written."
          " Sources are weighed by how they know: a primary source, a report or a hands-on test establishes a fact;"
          " analysis, opinion, summaries and posts are commentary, however many there are."
          f" Generated {meta.get('generated', '')}.*", ""]
    order = [i for k in ("must", "worth", "brief") for s in sel[k] for i in s["ids"]]
    return "\n".join(L), order


def fit(day: str, sel: dict, ed: dict, meta: dict, max_words: int) -> tuple:
    """render(), then drop the lowest In brief, then Worth knowing items until the edition is within max_words."""
    md, order = render(day, sel, ed, meta)
    dropped = 0
    while max_words and len(md.split()) > max_words and (sel["brief"] or len(sel["worth"]) > 2):
        if sel["brief"]:
            sel["brief"].pop()
        else:
            sel["worth"].pop()
        sel["more"] = sel.get("more", 0) + 1
        dropped += 1
        md, order = render(day, sel, ed, meta)
    return md, order, dropped


def story_records(sel: dict, run_id: str, day: str) -> dict:
    """What gets archived about the stories (data/stories/<day>.jsonl)."""
    def pack(s, section, n):
        return {"key": s["key"], "section": section, "n": n, "headline": s["headline"], "ids": s["ids"],
                "lead_id": s["lead"]["id"], "lead_url": s["lead"]["url"], "names": s["names"], "score": s["score"],
                "what_happened": s.get("what_happened", ""), "critical_pass": s.get("critical_pass", ""),
                "editor_view": s.get("editor_view", ""), "early_stage": s.get("early_stage", ""),
                "house_view": s.get("house_view", 0), "lead_case": s.get("lead_case") or {},
                "other_lens": s.get("other_lens") or {}, "thread": s.get("thread") or s["key"],
                "continues": s.get("continues", ""), "thread_day": s.get("thread_day", 1)}
    stories = [pack(s, "must", n) for n, s in enumerate(sel["must"], 1)]
    stories += [pack(s, "worth", n) for n, s in enumerate(sel["worth"], len(sel["must"]) + 1)]
    stories += [pack(s, "brief", None) for s in sel["brief"]]
    return {"run_id": run_id, "day": day, "stories": stories, "more": sel["more"]}


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)
