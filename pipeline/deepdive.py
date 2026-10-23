"""Topical deep dive: a separate ~10-minute explainer episode after the daily briefing, on the day's focal point.

1 pick     Claude reads today's briefing, the past week's headlines and recent deep dives, and decides whether
           anything deserves one (a breakthrough, a controversy, a concept like the "third scaling law", a
           change in trajectory, a story that has matured). It may say no: a weak deep dive is worse than none.
2 write    Claude (web search on) writes the episode from today's sources plus primary documents it finds.
3 check    every source link is checked live and dead ones dropped (fewer than 2 live -> no episode);
           quotation marks survive only around words found in the archived or fetched source text;
           sentences with a $ or % figure found in no source are cut; private names scrubbed; banned
           words/markup fail the episode.
4 publish  briefings/deepdives/<day>.md (show notes + sources), .script.md, .spoken.txt, .mp3; the podcast
           feed lists it as a bonus episode "Deep dive: <title>" right after that day's briefing.

    ./np deepdive [DAY] [--topic "..."] [--force]
config.yaml deepdive: {enabled, max_per_week, minutes, avoid_repeat_days, web, timeout_seconds}
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .archive import append_jsonl, read_jsonl

DIR = "briefings/deepdives"
LOG = "data/deepdives.jsonl"
SECTIONS = ["why_today", "plainly", "evidence", "readings", "so_what", "watch"]
OUTRO = ("That's the deep dive, and today's AI Briefing. Every source is linked in the show notes, and the AI Briefing "
         "web page has the written edition, this deep dive and every past episode. The daily briefing is back tomorrow.")


def dcfg(cfg: dict) -> dict:
    return {"enabled": True, "max_per_week": 7, "minutes": 10, "max_minutes": 13, "avoid_repeat_days": 21, "web": True,
            "timeout_seconds": 1800, **(cfg.get("deepdive") or {})}


def records(root: Path) -> list:
    return read_jsonl(root / LOG)


def recent(root: Path, day: str, days: int) -> list:
    cut = (dt.date.fromisoformat(day) - dt.timedelta(days=days)).isoformat()
    return [r for r in records(root) if cut <= r.get("day", "") <= day and r.get("status") == "published"]


def opener(day: str, title: str, acfg: dict | None = None) -> str:
    acfg = acfg or {}
    d = dt.date.fromisoformat(day)
    host, prev = acfg.get("deepdive_host") or "", acfg.get("host_name") or ""
    thanks = f"Thanks, {prev}. " if prev and host else ""
    me = f" I'm {host}." if host else ""
    return (f"{thanks}This is the AI Briefing deep dive for {d.strftime('%A, %B')} {d.day}: {title.rstrip('.')}.{me} "
            "Like the briefing, it is written and read by AI, from public sources.")


# ---------- context ----------

def _stories(root: Path, day: str) -> list:
    rows = read_jsonl(root / "data" / "stories" / f"{day}.jsonl")
    return rows[-1].get("stories", []) if rows else []


def today_block(root: Path, cfg: dict, day: str) -> tuple:
    """(text for the prompt, numbered stories)."""
    md_file = root / cfg["paths"]["briefings"] / f"{day}.md"
    md = md_file.read_text("utf-8") if md_file.exists() else ""
    brief = re.search(r"\*\*The day in brief\.\*\* (.+)", md)
    stories = [s for s in _stories(root, day) if s.get("section") in ("must", "worth")]
    lines = [f"Day in brief: {brief.group(1) if brief else ''}"]
    for n, s in enumerate(stories, 1):
        lines.append(f"[{n}] ({s.get('section')}) {s.get('headline', '')} | sources: {', '.join(s.get('names') or [])}"
                     + (f" | developing, day {s['thread_day']}" if (s.get("thread_day") or 1) > 1 else "")
                     + f"\n    what happened: {s.get('what_happened', '')}\n    evidence check: {s.get('critical_pass', '')}"
                     + (f"\n    our read: {s['editor_view']}" if s.get("editor_view") else ""))
    oq = re.findall(r"^- \*\*(.+?)\*\*", md.split("## Open questions", 1)[1], re.M) if "## Open questions" in md else []
    if oq:
        lines.append("Open questions: " + " | ".join(oq))
    return "\n".join(lines), stories


def week_block(root: Path, day: str) -> str:
    out = []
    d0 = dt.date.fromisoformat(day)
    for i in range(1, 8):
        d = (d0 - dt.timedelta(days=i)).isoformat()
        heads = [s.get("headline", "") + (f" (developing, day {s['thread_day']})" if (s.get("thread_day") or 1) > 1 else "")
                 for s in _stories(root, d) if s.get("section") == "must"]
        if heads:
            out.append(f"{d}: " + " | ".join(heads))
    return "\n".join(out) or "(none)"


def material(root: Path, chosen: list, chars: int = 6000) -> tuple:
    """Text of the chosen stories' archived sources -> (prompt text, corpus for checks).
    chosen: [{"headline", "what_happened", "critical_pass", "editor_view", "ids"}]."""
    from .stages import _clean, raw_items
    ids = [i for s in chosen for i in s.get("ids", [])]
    raw = raw_items(root, ids, days=60)
    blocks, corpus = [], []
    for s in chosen:
        blocks.append(f"STORY: {s.get('headline', '')}\nwhat happened: {s.get('what_happened', '')}\n"
                      f"evidence check: {s.get('critical_pass', '')}\nour read: {s.get('editor_view', '')}")
        for i in s.get("ids", []):
            it = raw.get(i)
            if not it:
                continue
            from .stages import PRIVATE_KINDS, web_safe_text   # the writer has web access: no mailbox text
            corpus.append((it.get("text") or "")[:chars] + " " + it.get("title", ""))   # checks only, never sent
            if (it.get("source_kind") or "") in PRIVATE_KINDS or it.get("forwarded"):
                blocks.append(f'<source person="{it.get("person", "")}">\n{web_safe_text(it, chars)}\n</source>')
                continue
            blocks.append(f'<source person="{it.get("person", "")}" url="{it.get("linked_url") or it.get("url", "")}">\n'
                          f"title: {_clean(it.get('title', ''))}\n{_clean(web_safe_text(it, chars))}\n</source>")
    return "\n\n".join(blocks), corpus


# ---------- checks ----------

_FIG = re.compile(r"(?:[$€£]\s?\d[\d,.]*\s?(?:[BMKT]|bn|billion|million|trillion)?|\d[\d,.]*\s?%)")


def _fig_key(f: str) -> str:
    f = f.lower().replace(" ", "").replace(",", "")
    for a, b in (("billion", "b"), ("bn", "b"), ("million", "m"), ("trillion", "t")):
        f = f.replace(a, b)
    return f


def cut_unsourced_figures(text: str, corpus: str) -> tuple:
    """Drop sentences whose $/% figures appear in no source text -> (text, cut sentences)."""
    have = {_fig_key(f) for f in _FIG.findall(corpus)}
    keep, cut = [], []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        figs = [_fig_key(f) for f in _FIG.findall(sent)]
        if figs and any(f not in have for f in figs):
            cut.append(sent)
        else:
            keep.append(sent)
    return " ".join(keep).strip(), cut


def check_script(sections: list, corpus: list, cfg: dict) -> tuple:
    """-> (sections, notes, fatal). Quotes verified, unsourced figures cut, private names scrubbed."""
    from . import stages
    from .audio import banned, spelled_figures
    notes, out = [], []
    hay = " ".join(corpus)
    names = stages.private_names()
    allow = stages.allowed_names(names, [hay])
    for sid, text in sections:
        text = re.sub(r"https?://\S+", "", text).replace("*", "").strip()
        text, removed = stages.verify_quotes(text, corpus)
        if removed:
            notes.append(f"{sid}: {len(removed)} quotation(s) not found in sources, quote marks removed")
        text, cut = cut_unsourced_figures(text, hay)
        if cut:
            notes.append(f"{sid}: {len(cut)} sentence(s) with an unsourced figure cut")
        text, hits = stages.scrub_private(text, names, allow)
        if hits:
            notes.append(f"{sid}: private name(s) removed")
        from .links import strip_disclosures
        text, k = strip_disclosures(text)
        if k:
            notes.append(f"{sid}: {k} board-seat disclosure(s) removed")
        keep, dropped = [], []
        for sent in re.split(r"(?<=[.!?])\s+", text):     # a bad sentence is cut, not the whole episode
            (dropped if (banned(sent) or spelled_figures(sent)) else keep).append(sent)
        if dropped:
            notes.append(f"{sid}: {len(dropped)} sentence(s) cut (markup or a figure in words)")
        text = " ".join(keep).strip()
        if text:
            out.append((sid, text))
    return out, notes, False


# ---------- queue: suggestions Steven can schedule, reorder or dismiss (dashboard /deep-dives) ----------
QUEUE = "data/deepdive_queue.json"
Q_STATUSES = ("suggested", "queued", "scheduled", "done", "dismissed", "failed")


def load_queue(root: Path) -> list:
    try:
        return json.loads((root / QUEUE).read_text("utf-8")).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_queue(root: Path, items: list) -> None:
    p = root / QUEUE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"updated": dt.datetime.now().isoformat(timespec="seconds"), "items": items},
                            indent=1, ensure_ascii=False) + "\n", "utf-8")


def _qid(topic: str) -> str:
    import hashlib
    return hashlib.sha1(re.sub(r"[^a-z0-9]+", " ", topic.lower()).strip().encode()).hexdigest()[:8]


def _similar(a: str, b: str) -> bool:
    wa, wb = set(re.findall(r"[a-z0-9]{4,}", a.lower())), set(re.findall(r"[a-z0-9]{4,}", b.lower()))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def add_suggestions(root: Path, day: str, cands: list, stories: list, origin: str = "claude") -> list:
    items = load_queue(root)
    added = []
    for c in cands:
        t = str(c.get("topic") or "").strip()
        if not t or any(_similar(t, x["topic"]) for x in items if x["status"] not in ("dismissed",)):
            continue
        nums = [n for n in c.get("story_numbers") or [] if isinstance(n, int) and 1 <= n <= len(stories)]
        it = {"id": _qid(t + day), "topic": t[:120], "kind": c.get("kind", ""), "why_today": str(c.get("why_today", ""))[:300],
              "angle": str(c.get("angle", ""))[:500], "search_hints": list(c.get("search_hints") or [])[:4],
              "strength": c.get("strength"), "source_day": day, "story_ids": [i for n in nums for i in stories[n - 1].get("ids", [])],
              "story_headlines": [stories[n - 1].get("headline", "") for n in nums], "status": "suggested",
              "origin": origin, "created": dt.datetime.now().isoformat(timespec="seconds")}
        items.append(it)
        added.append(it)
    save_queue(root, items)
    return added


def set_status(root: Path, qid: str, status: str, **extra) -> dict:
    if status not in Q_STATUSES:
        raise ValueError(status)
    items = load_queue(root)
    for it in items:
        if it["id"] == qid:
            it["status"] = status
            if status == "queued":
                it["order"] = max([x.get("order", 0) for x in items if x["status"] == "queued"] + [0]) + 1
            it.update(extra, status_at=dt.datetime.now().isoformat(timespec="seconds"))
            save_queue(root, items)
            return it
    raise KeyError(qid)


def move(root: Path, qid: str, delta: int) -> None:
    items = load_queue(root)
    q = sorted([x for x in items if x["status"] == "queued"], key=lambda x: x.get("order", 0))
    i = next((n for n, x in enumerate(q) if x["id"] == qid), None)
    if i is None:
        return
    j = max(0, min(len(q) - 1, i + delta))
    q[i], q[j] = q[j], q[i]
    for n, x in enumerate(q, 1):
        x["order"] = n
    save_queue(root, items)


def move_to(root: Path, qid: str, pos: int) -> None:
    """Put a topic at position POS (1 = next to air) in Up next; a suggested topic is queued there."""
    items = load_queue(root)
    it = next((x for x in items if x["id"] == qid), None)
    if not it:
        raise KeyError(qid)
    if it["status"] != "queued":
        it["status"], it["status_at"] = "queued", dt.datetime.now().isoformat(timespec="seconds")
    q = sorted([x for x in items if x["status"] == "queued" and x is not it], key=lambda x: x.get("order", 0))
    pos = max(1, min(len(q) + 1, int(pos)))
    q.insert(pos - 1, it)
    it.pop("auto", None)                         # placed by Steven now
    for n, x in enumerate(q, 1):
        x["order"] = n
    save_queue(root, items)


def add_manual(root: Path, topic: str, angle: str = "", day: str = "") -> dict:
    day = day or dt.date.today().isoformat()
    it = add_suggestions(root, day, [{"topic": topic, "angle": angle or topic, "kind": "concept",
                                      "why_today": "Chosen by the editor.", "strength": 5}], [], origin="steven")
    return set_status(root, it[0]["id"], "queued") if it else {}


def snapshot(root: Path) -> list:
    """What the email queue page shows: Up next in order, then the strongest recent suggestions."""
    items = load_queue(root)
    up = sorted([x for x in items if x["status"] == "queued"], key=lambda x: x.get("order", 0))
    sugg = sorted([x for x in items if x["status"] == "suggested"],
                  key=lambda x: (x.get("source_day", ""), x.get("strength") or 0), reverse=True)[:10]
    return [{"id": x["id"], "topic": x["topic"], "status": x["status"],
             "why": (x.get("why_today") or "")[:200]} for x in up + sugg]


REMOTE_STATE = "data/state/dd-actions.json"


def apply_remote(root: Path, cfg: dict, log=print) -> int:
    """Apply Steven's clicks on the email queue page (Make next, up/down, dismiss, suggest) -> how many."""
    from .mailer import call
    try:
        acts = call(cfg, "ddactions").get("actions") or []
    except Exception as e:  # noqa: BLE001
        log(f"deep-dive queue page: not read ({e})")
        return 0
    try:
        last = json.loads((root / REMOTE_STATE).read_text("utf-8")).get("last", "")
    except (OSError, json.JSONDecodeError):
        last = ""
    n = 0
    for a in sorted(acts, key=lambda a: a.get("at", "")):
        if a.get("at", "") <= last:
            continue
        op, qid = a.get("op"), str(a.get("id") or "")
        try:
            if op == "next":
                move_to(root, qid, 1)
            elif op in ("up", "down"):
                move(root, qid, -1 if op == "up" else 1)
            elif op == "dismiss":
                set_status(root, qid, "dismissed")
            elif op == "add" and str(a.get("topic") or "").strip():
                add_manual(root, str(a["topic"]).strip()[:200], str(a.get("angle") or "").strip()[:400])
            n += 1
        except (KeyError, ValueError):
            pass
        last = a.get("at", last)
    p = root / REMOTE_STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last": last}) + "\n", "utf-8")
    if n:
        log(f"Deep-dive queue: applied {n} change(s) from your email page")
    return n


def queued(root: Path) -> list:
    return sorted([x for x in load_queue(root) if x["status"] == "queued"], key=lambda x: x.get("order", 0))


def scheduled_for(root: Path, day: str) -> dict | None:
    return next((x for x in load_queue(root) if x["status"] == "scheduled" and x.get("for_day") == day), None)


def _backend(cfg: dict, web: bool):
    from . import llm as llmmod
    b = llmmod.for_stage(cfg, "deepdive")
    if isinstance(b, llmmod.ClaudeCode):
        b.web = web
        b.timeout = max(b.timeout, int(dcfg(cfg)["timeout_seconds"]))
    b.check()
    return b


def suggest(root: Path, cfg: dict, day: str, llm=None, log=print) -> dict:
    """Ask for today's candidates and add the new ones to the queue -> {"added", "best", "stories"}."""
    from . import stages
    today, stories = today_block(root, cfg, day)
    if not stories:
        return {"added": [], "best": None, "stories": []}
    persp = (root / cfg["paths"]["perspective"]).read_text("utf-8")
    system, _ = stages.system_prompt(persp)
    tmpl, _ = stages.prompt("deepdive_pick")
    past = recent(root, day, int(dcfg(cfg)["avoid_repeat_days"]))
    waiting = [x["topic"] for x in load_queue(root) if x["status"] in ("suggested", "queued", "scheduled")]
    out = stages._ask(llm or _backend(cfg, False), system,
                      tmpl.replace("{{today}}", today).replace("{{week}}", week_block(root, day))
                      .replace("{{recent}}", "\n".join(f"{r['day']}: {r.get('title', '')}" for r in past) or "(none)")
                      .replace("{{queue}}", "\n".join(waiting) or "(none)"), 2500)
    cands = [c for c in out.get("candidates") or [] if isinstance(c, dict)][:4]
    added = add_suggestions(root, day, cands, stories)
    best_i = out.get("best", -1)
    best = None
    if isinstance(best_i, int) and 0 <= best_i < len(cands) and (cands[best_i].get("strength") or 0) >= 4:
        bt = cands[best_i].get("topic", "")
        best = next((x for x in load_queue(root) if x["topic"] == bt and x["status"] == "suggested"), None)
    log(f"Deep dive suggestions: {len(added)} new" + (f"; best today: {best['topic']}" if best else "; none strong enough today"))
    return {"added": added, "best": best, "stories": stories}


def ensure_next(root: Path, log=print) -> dict | None:
    """Keep Up next non-empty (Steven, 2026-10-19: "the queue should never be empty"): if nothing is queued, the
    strongest recent suggestion goes to the top (4+ first, else the best rated 3; a 2 is too thin to air), so the next deep dive is always
    known in advance and can be changed on the dashboard or from the note."""
    if queued(root):
        return queued(root)[0]
    cands = [x for x in load_queue(root) if x["status"] == "suggested" and (x.get("strength") or 0) >= 4] \
        or [x for x in load_queue(root) if x["status"] == "suggested" and (x.get("strength") or 0) >= 3]
    if not cands:
        return None
    best = sorted(cands, key=lambda x: (x.get("strength") or 0, x.get("source_day", ""), x.get("created", "")), reverse=True)[0]
    it = set_status(root, best["id"], "queued", auto=True)
    log(f"Deep dive up next: {it['topic']} (Claude's pick; change it on the dashboard)")
    return it


def plan_today(root: Path, cfg: dict, day: str, llm=None, log=print) -> dict | None:
    """Refresh suggestions, then choose today's deep dive: Steven's queue first, else today's best suggestion
    (within the weekly cap). The choice is marked 'scheduled' for DAY -> the queue item, or None."""
    already = scheduled_for(root, day)
    if already:
        return already
    try:
        res = suggest(root, cfg, day, llm, log)
    except Exception as e:  # noqa: BLE001
        log(f"Deep dive suggestions failed: {e}")
        res = {"best": None}
    if _week_count(root, day) >= int(dcfg(cfg)["max_per_week"]):
        log(f"Deep dive: weekly cap ({dcfg(cfg)['max_per_week']}) reached; suggestions kept for later")
        ensure_next(root, log)
        return None
    pick = (queued(root) or [None])[0] or res.get("best") or ensure_next(root, log)   # the top of Up next airs
    if not pick:
        return None
    it = set_status(root, pick["id"], "scheduled", for_day=day)
    log(f"Deep dive today: {it['topic']} ({'from Up next' if pick.get('order') else 'best suggestion'})")
    ensure_next(root, log)                          # tomorrow's is known now
    return it


# ---------- run ----------

def _week_count(root: Path, day: str) -> int:
    """Deep-dive DAYS in the last week (a re-recording or a write+voice pair is one day, not two)."""
    return len({r.get("day") for r in recent(root, day, 6)})


def run(root: Path, cfg: dict, day: str, log=print, topic: str = "", force: bool = False,
        llm_pick=None, llm_write=None, tts=True) -> dict:
    """Write (and voice) DAY's deep dive: the scheduled queue item, or plan one now."""
    from . import stages
    from .dive import check_links
    from .record import page_text
    c = dcfg(cfg)
    rec = {"day": day, "at": dt.datetime.now().isoformat(timespec="seconds")}
    if topic:
        item = add_manual(root, topic, day=day)
        item = set_status(root, item["id"], "scheduled", for_day=day) if item else None
    else:
        item = scheduled_for(root, day)
        if not item:
            if not force and _week_count(root, day) >= int(c["max_per_week"]):
                rec.update(status="skipped", reason=f"weekly cap ({c['max_per_week']}) reached")
                append_jsonl(root / LOG, [rec])
                log(f"Deep dive: skipped, {rec['reason']}")
                return rec
            item = plan_today(root, cfg, day, llm_pick, log)
    if not item:
        rec.update(status="skipped", reason="nothing in the queue and no suggestion strong enough today")
        append_jsonl(root / LOG, [rec])
        log(f"Deep dive: none today ({rec['reason']})")
        return rec
    persp = (root / cfg["paths"]["perspective"]).read_text("utf-8")
    system, _ = stages.web_system_prompt(persp)          # the writer has web access: no private context
    pick = {"topic": item["topic"], "kind": item.get("kind"), "why_today": item.get("why_today", ""),
            "angle": item.get("angle", ""), "search_hints": item.get("search_hints") or []}
    rec["pick"] = {**pick, "queue_id": item["id"], "origin": item.get("origin")}
    log(f"Deep dive: {pick['topic']} ({pick.get('kind')}): {pick.get('why_today', '')}")
    chosen = []
    src_stories = {}
    d0 = dt.date.fromisoformat(item.get("source_day") or day)
    for back in range(0, 30):                       # a queued topic can draw on stories from several days
        for s in _stories(root, (d0 - dt.timedelta(days=back)).isoformat()):
            for i in s.get("ids", []):
                src_stories.setdefault(i, s)
    for i in item.get("story_ids") or []:
        s = src_stories.get(i)
        if s and s not in chosen:
            chosen.append(s)
    if not chosen:
        chosen = [s for s in _stories(root, day) if s.get("section") == "must"][:2]

    # 2 write
    mat, corpus = material(root, chosen)
    from .audio import voice_wpm
    wpm = voice_wpm(((cfg.get("audio") or {}).get("deepdive_voice")) or "af_bella", root)
    words = int(float(c["minutes"]) * wpm * 0.95)
    max_words = int(float(c.get("max_minutes", 13)) * wpm)       # a touch longer when the topic needs the detail
    wt, wv = stages.prompt("deepdive_write")
    hints = "; ".join(pick.get("search_hints") or [])
    share = lambda f: str(int(words * f))
    user = (wt.replace("{{words}}", str(words)).replace("{{max_words}}", str(max_words))
              .replace("{{w_why}}", share(0.11)).replace("{{w_plain}}", share(0.25)).replace("{{w_evidence}}", share(0.25))
              .replace("{{w_readings}}", share(0.17)).replace("{{w_sowhat}}", share(0.14)).replace("{{w_watch}}", share(0.08))
              .replace("{{topic}}", pick["topic"]).replace("{{why_today}}", pick.get("why_today", ""))
              .replace("{{angle}}", pick.get("angle", "") + (f" Look up: {hints}." if hints else ""))
              .replace("{{material}}", mat or "(no archived text)"))
    llm_write = llm_write or _backend(cfg, bool(c["web"]))
    out = stages._ask(llm_write, system, user, 9000)
    by_id = {s.get("id"): str(s.get("text", "")) for s in out.get("sections") or [] if isinstance(s, dict)}
    sections = [(sid, by_id[sid]) for sid in SECTIONS if by_id.get(sid)]

    # 3 check
    srcs = [s for s in out.get("sources") or [] if isinstance(s, dict) and str(s.get("url", "")).startswith("http")][:12]
    live = check_links([s["url"] for s in srcs], cfg)
    srcs_live = [s for s in srcs if live.get(s["url"])]
    rec["sources_dropped"] = [s["url"] for s in srcs if not live.get(s["url"])]
    for s in srcs_live[:8]:
        t = page_text(s["url"], cfg, 20000)
        if t:
            corpus.append(t)
    if len(srcs_live) < 2:
        rec.update(status="failed", reason=f"only {len(srcs_live)} live source(s)", title=out.get("title", ""))
        set_status(root, item["id"], "failed", note=rec["reason"])
        append_jsonl(root / LOG, [rec])
        log(f"Deep dive: not published, {rec['reason']}")
        return rec
    sections, notes, fatal = check_script(sections, corpus, cfg)
    rec["checks"] = notes
    if fatal or len(sections) < 4:
        rec.update(status="failed", reason="script failed checks: " + "; ".join(notes[-2:]), title=out.get("title", ""))
        set_status(root, item["id"], "failed", note=rec["reason"])
        append_jsonl(root / LOG, [rec])
        log(f"Deep dive: not published, {rec['reason']}")
        return rec
    cap = max_words
    while sum(len(t.split()) for _, t in sections) > cap and len(sections) > 4:
        drop = "readings" if any(s == "readings" for s, _ in sections) else sections[-2][0]
        sections = [(s, t) for s, t in sections if s != drop]
        notes.append(f"over {cap} words: left out {drop}")

    # 3b the lines readers see first (email, site) come from the CHECKED body, never from the suggestion text
    from .consistency import check_header
    body = " ".join(t for _, t in sections)
    why_sec = next((t for s, t in sections if s == "why_today"), "")
    hay_all = " ".join(corpus)
    why_line, wn = check_header(" ".join(re.split(r"(?<=[.!?])\s+", why_sec)[:2]), body, hay_all)
    summary, sn = check_header(str(out.get("summary", "")).strip(), body, hay_all)
    if not summary:                              # nothing in the model's summary survived: use the checked opening
        summary = why_line or " ".join(re.split(r"(?<=[.!?])\s+", body)[:2])
    notes += wn + sn
    rec["checks"] = notes

    # 4 publish files
    title = re.sub(r"\s+", " ", str(out.get("title") or pick["topic"])).strip()[:90]
    d = root / DIR
    d.mkdir(parents=True, exist_ok=True)
    parts = [("Opener", opener(day, title, cfg.get("audio") or {}))] + sections + [("Outro", OUTRO)]
    from .profiles import profile
    from .editorial import _KIND_WORD
    src_md = "\n".join(f"- [{s.get('title') or s['url']}]({s['url']}) · {_KIND_WORD.get(profile({'url': s['url']})['kind'], 'source')}"
                       + (f": {s['what']}" if s.get("what") else "") for s in srcs_live)
    from .links import scrub_output
    notes_md, _ = scrub_output(
        f"# Deep dive: {title}\n\n*AI Briefing · {day} · follows today's briefing · written and read by AI from public sources*\n\n"
        f"{summary}\n\n" + (f"**Why today.** {why_line}\n\n" if why_line else "") + f"## Sources\n\n{src_md}\n", cfg)
    (d / f"{day}.md").write_text(notes_md, "utf-8")
    from .audio import script_markdown
    (d / f"{day}.script.md").write_text(script_markdown(f"Deep dive: {title}", parts, {"script_model": getattr(llm_write, "label", ""),
                                                                                         "prompt": wv}), "utf-8")
    rec.update(status="written", title=title, kind=pick.get("kind"), sources=[s["url"] for s in srcs_live],
               words=sum(len(t.split()) for _, t in parts), file=f"{DIR}/{day}.md", prompt_write=wv)
    (d / f"{day}.parts.json").write_text(json.dumps({"title": title, "parts": parts}, ensure_ascii=False), "utf-8")
    if tts:
        rec["minutes"] = _render(root, cfg, day, title, parts)
        rec["voice"] = c.get("voice") or (cfg.get("audio") or {}).get("deepdive_voice") or "af_bella"
        rec["status"] = "published"
    set_status(root, item["id"], "done", done_day=day, title=title)
    append_jsonl(root / LOG, [rec])
    log(f"Deep dive: {rec['status']} '{title}' · {rec['words']} words · {len(srcs_live)} live sources"
        + (f" · {rec.get('minutes')} min" if rec.get("minutes") else "") + (f" · checks: {'; '.join(notes)}" if notes else ""))
    return rec


def _render(root: Path, cfg: dict, day: str, title: str, parts: list) -> float:
    from . import audio, speech
    from .episodes import rebuilt
    c = dcfg(cfg)
    d = root / DIR
    eng = audio.engine_from(cfg, c.get("voice") or (cfg.get("audio") or {}).get("deepdive_voice") or None)
    eng.check()
    table = speech.load_table(root)
    said = [(n, speech.spoken(t, table)) for n, t in parts]
    (d / f"{day}.spoken.txt").write_text("\n\n".join(f"[{n}]\n{t}" for n, t in said) + "\n", "utf-8")
    minutes = round(audio.render_mp3(eng, said, d / f"{day}.mp3", f"Deep dive: {title}",
                                     (cfg.get("audio") or {}).get("bitrate", "64k")), 1)
    rebuilt(root, f"deepdive:{day}")
    return minutes


def latest(root: Path, day: str) -> dict | None:
    return next((r for r in reversed(records(root)) if r.get("day") == day), None)


def voice(root: Path, cfg: dict, day: str, log=print) -> dict | None:
    """Record DAY's written deep dive (the script was written and checked before the briefing audio)."""
    rec = latest(root, day)
    if not rec or rec.get("status") != "written":
        return rec
    p = root / DIR / f"{day}.parts.json"
    data = json.loads(p.read_text("utf-8"))
    out = {**rec, "at": dt.datetime.now().isoformat(timespec="seconds"), "status": "published",
           "minutes": _render(root, cfg, day, data["title"], [tuple(x) for x in data["parts"]]),
           "voice": (dcfg(cfg).get("voice") or (cfg.get("audio") or {}).get("deepdive_voice") or "af_bella"),
           "words": sum(len(str(t).split()) for _, t in data["parts"])}     # voice_wpm() learns from these
    append_jsonl(root / LOG, [out])
    log(f"Deep dive: published '{data['title']}' · {out['minutes']} min")
    return out


HEADINGS = {"why_today": "Why today", "plainly": "Plainly", "evidence": "What the evidence shows",
            "readings": "How people read it", "so_what": "What it means for builders and investors",
            "watch": "What to watch"}


def written_md(root: Path, day: str) -> str:
    """The deep dive as a readable article: the spoken script's sections under plain headings, without the
    spoken opener and sign-off ('' when there is no script)."""
    p = root / DIR / f"{day}.script.md"
    if not p.exists():
        return ""
    out = []
    for sec in re.split(r"(?m)^## ", p.read_text("utf-8"))[1:]:
        name, _, body = sec.partition("\n")
        name = name.strip()
        if name.lower() in ("opener", "outro", "intro", "close"):
            continue
        body = body.strip()
        if body:
            out.append(f"## {HEADINGS.get(name, name.replace('_', ' ').capitalize())}\n\n{body}")
    return "\n\n".join(out)


def episodes_for_feed(root: Path, days: list) -> list:
    """Deep-dive episodes for the site/podcast feed: one per day that has an MP3 (latest record wins)."""
    from .episodes import audio_file, guid
    by_day = {}
    for r in records(root):
        if r.get("status") == "published":
            by_day[r["day"]] = r
    out = []
    for day in days:
        r = by_day.get(day)
        mp3 = root / DIR / f"{day}.mp3"
        if not r or not mp3.is_file():
            continue
        md = (root / DIR / f"{day}.md").read_text("utf-8") if (root / DIR / f"{day}.md").exists() else ""
        key = f"deepdive:{day}"
        out.append({"key": key, "day": day, "title": f"Deep dive: {r.get('title', '')}", "md": md, "mp3": mp3,
                    "written": written_md(root, day),
                    "file": audio_file(root, key), "guid": guid(root, key), "type": "bonus", "time": "06:50:00",
                    "summary": (re.search(r"\*\n\n(.+?)\n", md) or re.search(r"(.+)", r.get("title", ""))).group(1)})
    return out


def podcast_mp3(root: Path, day: str) -> Path:
    return root / "briefings" / f"{day}.podcast.mp3"


def make_podcast(root: Path, cfg: dict, day: str, log=print) -> Path | None:
    """The podcast episode for DAY: briefing + hand-off + deep dive in one file (Steven, 2026-10-19). Only when the
    briefing's audio ends with the hand-off (otherwise the deep dive stays a separate bonus episode). -> path or None."""
    from . import audio, episodes
    b_mp3, d_mp3 = root / "briefings" / f"{day}.mp3", root / DIR / f"{day}.mp3"
    script = root / "briefings" / f"{day}.script.md"
    if not (b_mp3.is_file() and d_mp3.is_file() and script.is_file()):
        return None
    if "takes you through today's deep dive" not in script.read_text("utf-8"):
        log(f"Podcast {day}: the briefing audio has no hand-off; the deep dive stays a separate episode")
        return None
    out = podcast_mp3(root, day)
    minutes = audio.combine([b_mp3, d_mp3], out, title=f"AI Briefing {day} + deep dive")
    episodes.rebuilt(root, day)                  # a new file for an already-published day is a new episode version
    log(f"Podcast {day}: briefing + deep dive in one episode, {minutes} min")
    return out


def revoice(root: Path, cfg: dict, day: str, log=print) -> dict | None:
    """Re-record DAY's deep dive with the current opener and sign-off (the checked sections are kept as written)."""
    p = root / DIR / f"{day}.parts.json"
    rec = latest(root, day)
    if not p.is_file() or not rec:
        return None
    data = json.loads(p.read_text("utf-8"))
    parts = [tuple(x) for x in data["parts"]]
    parts = [("Opener", opener(day, data["title"], cfg.get("audio") or {})) if n == "Opener" else
             ("Outro", OUTRO) if n == "Outro" else (n, t) for n, t in parts]
    data["parts"] = parts
    p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    out = {**rec, "at": dt.datetime.now().isoformat(timespec="seconds"), "status": "published",
           "minutes": _render(root, cfg, day, data["title"], parts), "revoiced": True}
    append_jsonl(root / LOG, [out])
    log(f"Deep dive {day}: re-recorded with the current opener and sign-off, {out['minutes']} min")
    return out
