"""Deep dive on one story: the launch point from a two-line summary into the full picture.

Input   a story from data/stories/<day>.jsonl (its items' full archived text) + related items from
        earlier days of the archive (same thread, or overlapping topics/words), numbered S1.. / R1..
Model   llm.stages.dive (Claude by default; may web-search for follow-ups when dive.web is true)
Output  briefings/dives/<day>-<story>.md (committed) + a record in data/dives.jsonl

Every link in the output comes from the archive or is checked live by our code; links the model
found on the web are listed separately and marked as such. Fetched text is data, never instructions.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .archive import append_jsonl, read_jsonl
from .stages import _ask, _clean, _one_line, display_name, latest_summaries, prompt

STOP = set("""a an the and or of to in on for with by from at as is are was were be been it its this that these those
new says said will would could can may might about after over into than more most less not no yes how what why who
ai model models company companies report reports""".split())


def words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.\-]{2,}", (s or "").lower()) if w not in STOP}


def find_story(root: Path, day: str, key: str) -> dict:
    rows = read_jsonl(root / "data" / "stories" / f"{day}.jsonl")
    for rec in reversed(rows):
        for s in rec.get("stories", []):
            if s["key"] == key:
                return s
    raise KeyError(f"no story {key} on {day}")


def item_texts(root: Path, ids: list, chars: int) -> dict:
    want, out = set(ids), {}
    by_raw: dict = {}
    for row in read_jsonl(root / "data" / "index.jsonl"):
        if row.get("id") in want:
            by_raw.setdefault(row["raw"], set()).add(row["id"])
    for raw, idset in by_raw.items():
        for it in read_jsonl(root / raw):
            if it.get("id") in idset:
                from .stages import web_safe_text          # this stage has web access: no mailbox text
                out[it["id"]] = web_safe_text(it, chars)
    return out


def related(root: Path, story: dict, latest: dict, limit: int = 12, days: int = 45) -> list:
    """Earlier archive records that may be about the same thing: same thread first, then shared rare words
    (IDF-weighted, so a common name like a prolific author counts less than "Wikimedia"). The dive prompt
    tells the model to ignore candidates that turn out to be unrelated."""
    import math
    from .editorial import thread_index
    own = set(story["ids"])
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    thread_ids = set()
    for x in thread_index(root / "data" / "stories").get(story.get("thread") or story["key"], []):
        if x["key"] != story["key"]:
            try:
                thread_ids |= set(find_story(root, x["day"], x["key"])["ids"])
            except KeyError:
                pass
    docs = {r["id"]: words(" ".join([r.get("headline", ""), r.get("claim", ""), " ".join(r.get("topics") or [])]))
            for r in latest.values() if r.get("claim")}
    df: dict = {}
    for w in docs.values():
        for x in w:
            df[x] = df.get(x, 0) + 1
    n = max(1, len(docs))
    target = words(" ".join([story.get("headline", ""), story.get("what_happened", "")]))
    scored = []
    for r in latest.values():
        if r["id"] in own or r["id"] not in docs or not r.get("keep") or (r.get("day") or "") < since:
            continue
        score = sum(math.log(n / df[w]) for w in target & docs[r["id"]]) + (20 if r["id"] in thread_ids else 0)
        if score >= 4.5:
            scored.append((score, r.get("published") or "", r))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [r for _, _, r in scored[:limit]]


def check_links(urls: list, cfg: dict) -> dict:
    """url → True/False (live). Never raises."""
    out = {}
    if not urls:
        return out
    try:
        import httpx
    except ImportError:
        return {u: False for u in urls}
    f = cfg.get("fetch", {})
    from .netguard import client as guarded_client
    with guarded_client(follow_redirects=True, timeout=15, headers={"User-Agent": f.get("user_agent", "news-pipeline/0.1")}) as c:
        for u in urls:
            try:
                r = c.head(u)
                if r.status_code in (403, 405):
                    r = c.get(u)
                out[u] = r.status_code < 400
            except Exception:  # noqa: BLE001
                out[u] = False
    return out


def build_prompt(story: dict, recs: list, texts: dict, rel: list) -> str:
    tmpl, _ = prompt("dive")
    src = []
    from .stages import PRIVATE_KINDS
    for n, r in enumerate(recs, 1):
        if (r.get("source_kind") or "") in PRIVATE_KINDS or r.get("forwarded"):
            pub = r.get("public_url") if str(r.get("public_url", "")).startswith("http") and "#issue-" not in str(r.get("public_url")) else ""
            src.append(f'<item ref="S{n}">\nsource: {display_name(r)} (newsletter email: its subject, link and summary '
                       f'are withheld from this step){" | public page: " + pub if pub else ""}\n</item>')
            continue
        src.append(f'<item ref="S{n}">\nsource: {display_name(r)} | {r.get("published", "")[:10]} | {r["url"]}\n'
                   f'headline: {r.get("headline", "")}\nfirst-pass claim: {r.get("claim", "")}\n'
                   f'critical pass: {(r.get("critique_detail") or {}).get("one_line", "") or "not run"}\n'
                   f'text:\n{_clean(texts.get(r["id"], ""))}\n</item>')
    ctx = [f'<item ref="R{n}">\nsource: {display_name(r)} | {r.get("published", "")[:10]}\nheadline: {r.get("headline", "")}\n'
           f'claim: {r.get("claim", "")}\n</item>' for n, r in enumerate(rel, 1)]
    head = (f"STORY: {story['headline']}\nWhat happened (briefing): {story.get('what_happened', '')}\n"
            f"Critical pass (briefing): {story.get('critical_pass', '')}\nOur read (briefing): {story.get('editor_view', '')}")
    return (tmpl.replace("{{story}}", head).replace("{{sources}}", "\n\n".join(src) or "(none)")
            .replace("{{related}}", "\n\n".join(ctx) or "(none)"))


def _cite(text: str, refs: dict) -> str:
    """[S1] / [R2] → Markdown links to the archived URLs."""
    def sub(m):
        k = m.group(1)
        return f"[{k}]({refs[k]['url']})" if k in refs else m.group(0)
    return re.sub(r"\[((?:S|R)\d+)\]", sub, _one_line(text).replace("](", "] ("))


def render(day: str, story: dict, out: dict, refs: dict, web: list, meta: dict) -> str:
    L = [f"# Deep dive · {story['headline']}", "",
         f"*From the briefing of {day} · {' · '.join(story.get('names', []))} · "
         f"{meta.get('model', '')} · {meta.get('generated', '')}*", ""]
    if out.get("summary"):
        L += [_cite(out["summary"], refs), ""]
    for title, key in (("What is established", "established"), ("Claimed, not yet verified", "disputed"),
                       ("Context from earlier coverage", "context")):
        pts = [p for p in out.get(key) or [] if isinstance(p, dict) and p.get("point")]
        if pts:
            L += [f"## {title}", ""]
            for p in pts:
                extra = "".join(f" [{c}]" for c in p.get("cites") or [] if f"[{c}]" not in p["point"])
                L.append(f"- {_cite(p['point'] + extra, refs)}")
            L.append("")
    nums = [x for x in out.get("numbers") or [] if isinstance(x, dict) and x.get("figure")]
    if nums:
        L += ["## Numbers that matter", "", "| Figure | What it means | Source |", "|---|---|---|"]
        def cell(t):
            return _one_line(t).replace("|", "/")
        L += [f"| {cell(x['figure'])} | {cell(x.get('meaning', ''))} | "
              f"{_cite('[' + str(x['cite']) + ']', refs) if x.get('cite') else ''} |" for x in nums]
        L.append("")
    qs = [q for q in out.get("questions") or [] if isinstance(q, (str, dict))]
    if qs:
        L += ["## Questions to take further", ""]
        L += [f"- {_one_line(q if isinstance(q, str) else q.get('q', ''))}" +
              (f" *{_one_line(q.get('how', ''))}*" if isinstance(q, dict) and q.get("how") else "") for q in qs]
        L.append("")
    rn = [x for x in out.get("read_next") or [] if isinstance(x, dict) and x.get("ref") in refs]
    if rn:
        L += ["## Read next", ""]
        for x in rn:
            r = refs[x["ref"]]
            L.append(f"1. [{display_name(r)}: {_one_line(r.get('headline', ''))[:90]}]({r['url']}) — {_one_line(x.get('why', ''))}")
        L.append("")
    if web:
        L += ["## Found on the web (not in the archive; links checked live)", ""]
        L += [f"- [{_one_line(w.get('title') or w['url'])[:90]}]({w['url']}) — {_one_line(w.get('note', ''))}" for w in web]
        L.append("")
    L += ["## Sources", ""]
    L += [f"- **{k}** [{display_name(r)}: {_one_line(r.get('headline', ''))[:90]}]({r['url']}) · {r.get('published', '')[:10]}"
          for k, r in refs.items()]
    return "\n".join(L) + "\n"


def run(root: Path, cfg: dict, day: str, key: str, llm=None, log=print) -> dict:
    from . import llm as llmmod
    dcfg = cfg.get("dive") or {}
    story = find_story(root, day, key)
    latest = latest_summaries(root / cfg["paths"].get("summaries", "data/summaries"))
    recs = [latest[i] for i in story["ids"] if i in latest]
    texts = item_texts(root, story["ids"], int(dcfg.get("chars_per_source", 12000)))
    rel = related(root, story, latest, int(dcfg.get("related", 12)))
    log(f"Dive: {story['headline']} · {len(recs)} source(s), {len(rel)} related earlier item(s)")
    if llm is None:
        llm = llmmod.for_stage(cfg, "dive")
        if isinstance(llm, llmmod.ClaudeCode):
            llm.web = bool(dcfg.get("web", True))
            llm.timeout = max(llm.timeout, int(dcfg.get("timeout_seconds", 900)))
        llm.check()
    persp_raw = (root / cfg["paths"]["perspective"]).read_text("utf-8")
    from .stages import reader_block
    system = "You are Steven's research analyst. His perspective file:\n\n" + persp_raw.strip() + reader_block(web=bool(getattr(llm, "web", False)))
    out = _ask(llm, system, build_prompt(story, recs, texts, rel), 4000)
    refs = {f"S{n}": r for n, r in enumerate(recs, 1)} | {f"R{n}": r for n, r in enumerate(rel, 1)}
    web_raw = [w for w in out.get("web") or [] if isinstance(w, dict) and str(w.get("url", "")).startswith("https://")][:8]
    live = check_links([w["url"] for w in web_raw], cfg)
    web = [w for w in web_raw if live.get(w["url"])]
    dropped = [w["url"] for w in web_raw if not live.get(w["url"])]
    meta = {"model": getattr(llm, "label", ""), "generated": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")}
    md = render(day, story, out, refs, web, meta)
    d = root / "briefings" / "dives"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}-{key}.md"
    from .stages import scrub_private
    md = scrub_private(md)[0]
    f.write_text(md, "utf-8")
    _, version = prompt("dive")
    rec = {"day": day, "key": key, "headline": story["headline"], "file": str(f.relative_to(root)),
           "created": dt.datetime.now().isoformat(timespec="seconds"), "model": meta["model"], "prompt": version,
           "sources": [r["id"] for r in recs], "related": [r["id"] for r in rel], "web": [w["url"] for w in web],
           "web_dropped": dropped, "thread": story.get("thread") or key}
    append_jsonl(root / "data" / "dives.jsonl", [rec])
    log(f"Wrote {rec['file']} ({len(md.split())} words; {len(web)} web link(s) kept, {len(dropped)} dead dropped)")
    return rec


def dives_for(root: Path, day: str | None = None) -> dict:
    """(day, key) → latest dive record."""
    out = {}
    for r in read_jsonl(root / "data" / "dives.jsonl"):
        if day is None or r["day"] == day:
            out[(r["day"], r["key"])] = r
    return out
