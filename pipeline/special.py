"""Special editions (Steven, 2026-11-04): an occasional deep dive that goes out on its own, the day news breaks,
instead of waiting for the next morning's edition. The first was the midterm sweep (Nov 3, 2026).

A special is an extra episode, dated the day it goes out. The daily deep dive is untouched: a special has its own
files (briefings/specials/DAY.*), its own log (data/specials.jsonl) and its own fact-check file
(data/audit/DAY-special.json). It is written by the deep-dive writer and passes the same checks.

    draft QID         write and check it (not voiced); email Steven the review: the article, and the fact checks as
                      F1, F2 ... with A/B/C options and a recommendation
    revise DAY NOTE   rewrite the draft following Steven's notes (checked again)
    decide DAY "F1: B, F3: C"   apply his fact-check choices (unanswered items get the recommendation at release)
    release DAY       voice it; the site build adds its page at <site>/DAY/special/ (then: publish, verify, email)
    email DAY         one email to every active subscriber, once, after the page is live
    status            the specials, newest first

Where it goes (Steven, 2026-11-04): an email to subscribers, linking to its own page with the audio. It is not in
the podcast feeds, the landing page, Slack or the next morning's edition.

"Occasionally": at most one special a day and MAX_PER_30_DAYS in thirty days; the email goes out 07:00-21:00.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import html as htmllib
import json
import re
from pathlib import Path

from .stages import append_jsonl, read_jsonl

DIR = "briefings/specials"
LOG = "data/specials.jsonl"
EMAIL_LOG = "data/specials-email.jsonl"
MAX_PER_30_DAYS = 4
EMAIL_HOURS = (7, 21)


class SpecialError(RuntimeError):
    pass


@contextlib.contextmanager
def edition():
    """The deep-dive machinery, pointed at the special-edition files for the duration."""
    from . import deepdive
    saved = (deepdive.DIR, deepdive.LOG, deepdive.EDITION)
    deepdive.DIR, deepdive.LOG, deepdive.EDITION = DIR, LOG, "special"
    try:
        yield deepdive
    finally:
        deepdive.DIR, deepdive.LOG, deepdive.EDITION = saved


def records(root: Path) -> list:
    return read_jsonl(Path(root) / LOG)


def latest(root: Path, day: str) -> dict | None:
    return next((r for r in reversed(records(root)) if r.get("day") == day), None)


def emailed(root: Path, day: str) -> dict | None:
    return next((r for r in reversed(read_jsonl(Path(root) / EMAIL_LOG)) if r.get("day") == day and r.get("ok")
                 and not r.get("test")), None)


def _today() -> str:
    return dt.date.today().isoformat()


def recent_count(root: Path, day: str) -> int:
    cut = (dt.date.fromisoformat(day) - dt.timedelta(days=29)).isoformat()
    return len({r["day"] for r in records(root) if cut <= r.get("day", "") <= day and r.get("status") in ("written", "published")})


def page_url(cfg: dict, day: str) -> str:
    base = ((cfg.get("publish") or {}).get("site_url") or "https://sgwoods.github.io/ai-briefing/").rstrip("/")
    return f"{base}/{day}/special/"


# ---------- fact checks: the deep-dive kind of item, from DAY-special.json ----------

def fact_items(root: Path, day: str) -> list:
    from .audit import DIR as ADIR
    try:
        chk = json.loads((Path(root) / ADIR / f"{day}-special.json").read_text("utf-8"))
    except (OSError, ValueError):
        chk = {}
    out = []
    for h in chk.get("held") or []:
        prop = h.get("proposed") or ""
        opts = [("A", "keep as written")] + ([("B", "use the proposed rewrite")] if prop else []) + [("C", "cut it")]
        rec = "A" if _is_question(h["claim"]) else "B" if prop else "C"     # a question asserts nothing
        out.append({"id": f"F{len(out) + 1}", "claim": h["claim"], "why": h.get("why", ""), "proposed": prop,
                    "section": h.get("section", ""), "options": opts, "rec": rec})
    return out


def _is_question(s: str) -> bool:
    return str(s).strip().endswith("?")


def choices_path(root: Path, day: str) -> Path:
    return Path(root) / "data" / "audit" / f"{day}-special-choices.json"


def load_choices(root: Path, day: str) -> dict:
    try:
        return json.loads(choices_path(root, day).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def decide(root: Path, day: str, text: str) -> dict:
    """'F1: B, F3: C' (commas or lines) -> saved choices, merged with earlier ones."""
    from .factopts import parse
    picks = parse(re.sub(r"[,;]\s*", "\n", text or ""))
    its = {i["id"]: i for i in fact_items(root, day)}
    bad = [k for k, v in picks.items() if k not in its or v not in [o for o, _ in its[k]["options"]]]
    if bad:
        raise SpecialError(f"not a choice for {day}: {', '.join(bad)}")
    ch = {**load_choices(root, day), **picks}
    p = choices_path(root, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ch, indent=1) + "\n", "utf-8")
    return ch


def apply_choices(root: Path, day: str, log=print) -> list:
    """Each held sentence: Steven's choice, else the recommendation, into the written parts. -> results."""
    p = Path(root) / DIR / f"{day}.parts.json"
    data = json.loads(p.read_text("utf-8"))
    ch, results = load_choices(root, day), []
    for it in fact_items(root, day):
        pick = ch.get(it["id"]) or it["rec"]
        done = pick == "A"
        if pick in ("B", "C"):
            for part in data["parts"]:
                if it["claim"] in part[1]:
                    part[1] = re.sub(r"\s{2,}", " ", part[1].replace(it["claim"], it["proposed"] if pick == "B" else "", 1)).strip()
                    done = True
                    break
        results.append({"id": it["id"], "pick": pick, "by": "Steven" if it["id"] in ch else "recommendation",
                        **({} if done else {"note": "text not found (already changed?)"})})
        if pick != "A" or it["id"] in ch:
            log(f"special {day} {it['id']}: {pick} ({results[-1]['by']}){' - not applied' if not done else ''}")
    p.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    from .audio import script_markdown
    (Path(root) / DIR / f"{day}.script.md").write_text(
        script_markdown(f"Deep dive: {data['title']}", [tuple(x) for x in data["parts"]], {"fact_choices": "applied"}), "utf-8")
    return results


# ---------- the steps ----------

def draft(root: Path, cfg: dict, qid: str, log=print, **kw) -> dict:
    """Write and check today's special from deep-dive queue item QID; email Steven the review."""
    from .deepdive import load_queue, set_status
    day = _today()
    rec = latest(root, day)
    if rec and rec.get("status") in ("written", "published"):
        raise SpecialError(f"{day} already has a special edition ({rec.get('title', '')}); revise it instead")
    if recent_count(root, day) >= MAX_PER_30_DAYS:
        raise SpecialError(f"{MAX_PER_30_DAYS} special editions in the last 30 days already: specials are occasional")
    if not any(q.get("id") == qid for q in load_queue(root)):
        raise SpecialError(f"no deep-dive queue item {qid}")
    set_status(root, qid, "scheduled", for_day=day, special=True)
    try:
        with edition() as dd:
            rec = dd.run(root, cfg, day, log=log, tts=False, draft=True, qid=qid, **kw)
    finally:                                     # never left "scheduled": the daily dive must not pick it up
        _settle(root, qid)
    if rec.get("status") != "written":
        raise SpecialError(f"special not written: {rec.get('reason') or rec.get('status')}")
    review_email(root, cfg, day, log)
    return rec


def _settle(root: Path, qid: str) -> None:
    from .deepdive import load_queue, set_status
    q = next((x for x in load_queue(root) if x.get("id") == qid), None)
    if q and q.get("status") == "scheduled":
        set_status(root, qid, "special", special=True)


def revise(root: Path, cfg: dict, day: str, note: str, log=print, **kw) -> dict:
    rec = latest(root, day)
    if not rec or rec.get("status") != "written":
        raise SpecialError(f"no unreleased special edition for {day}")
    qid = (rec.get("pick") or {}).get("queue_id")
    from .deepdive import set_status
    set_status(root, qid, "scheduled", for_day=day, special=True)
    try:
        with edition() as dd:
            previous = dd.written_md(root, day)
            new = dd.run(root, cfg, day, log=log, tts=False, draft=True, qid=qid, notes=note, previous=previous, **kw)
    finally:
        _settle(root, qid)
    if new.get("status") != "written":
        append_jsonl(Path(root) / LOG, [{**rec, "at": dt.datetime.now().isoformat(timespec="seconds"),
                                         "revision_failed": new.get("reason", "")}])
        raise SpecialError(f"revision not used ({new.get('reason')}); the draft stands")
    with contextlib.suppress(OSError):
        choices_path(root, day).unlink()             # the F-numbers belong to the old draft
    review_email(root, cfg, day, log)
    return new


def release(root: Path, cfg: dict, day: str, log=print) -> dict:
    """Apply the fact-check choices and record it. The site build then adds its page (pipeline/site.py)."""
    rec = latest(root, day)
    if not rec or rec.get("status") not in ("written", "published"):
        raise SpecialError(f"no special edition drafted for {day}")
    if rec.get("status") == "published":
        log(f"special {day}: already recorded")
        return rec
    apply_choices(root, day, log)
    with edition() as dd:
        out = dd.voice(root, cfg, day, log)
    return out or {}


def email(root: Path, cfg: dict, day: str, to: str = "", log=print, fetch=None) -> dict:
    """The special to every active subscriber (or `to`, a test), once, and only when its page is live."""
    from . import mailer
    rec = latest(root, day)
    if not rec or rec.get("status") != "published":
        raise SpecialError(f"{day}'s special edition is not released yet")
    if not to and emailed(root, day):
        return {"ok": True, "skipped": f"{day}'s special edition was already emailed"}
    h = dt.datetime.now().hour
    if not to and not (EMAIL_HOURS[0] <= h < EMAIL_HOURS[1]):
        raise SpecialError(f"subscriber email goes out {EMAIL_HOURS[0]:02d}:00-{EMAIL_HOURS[1]:02d}:00")
    url = page_url(cfg, day)
    if not to and not _live(url, f"special-{day}.mp3", cfg, fetch):
        raise SpecialError(f"the page isn't live yet: {url}")
    msg = render_email(root, cfg, day, url)
    bad = mailer.privacy_gate(msg, cfg)
    if bad:
        raise SpecialError("privacy gate blocked the email: " + "; ".join(bad))
    out = mailer.call(cfg, "send", subject=msg["subject"], html=msg["html"], text=msg["text"], to=to, day=day)
    row = {"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "ok": bool(out.get("ok")),
           "sent": out.get("sent", 0), "failed": len(out.get("failed") or []), "test": bool(to), "subject": msg["subject"]}
    append_jsonl(Path(root) / EMAIL_LOG, [row])
    log(f"special {day}: emailed to {row['sent']} ({'test' if to else 'subscribers'})")
    return row


def _live(url: str, marker: str, cfg: dict, fetch=None) -> bool:
    import time
    for attempt in range(4):
        try:
            if fetch:
                status, text = fetch(url)
            else:
                from .netguard import client
                with client(timeout=20, follow_redirects=True) as c:
                    r = c.get(url, params={"v": str(int(time.time()))})
                    status, text = r.status_code, r.text
            if status == 200 and marker in text:
                return True
        except Exception:  # noqa: BLE001
            pass
        if not fetch:
            time.sleep(20 * (attempt + 1))
    return False


# ---------- words ----------

def _summary(root: Path, day: str) -> tuple:
    md = (Path(root) / DIR / f"{day}.md").read_text("utf-8") if (Path(root) / DIR / f"{day}.md").exists() else ""
    m = re.search(r"\*\n\n(.+?)\n", md)
    why = re.search(r"(?m)^\*\*Why today\.\*\* (.+)$", md)
    return md, (m.group(1) if m else ""), (why.group(1) if why else "")


def render_email(root: Path, cfg: dict, day: str, url: str) -> dict:
    from .mailer import _btn
    rec = latest(root, day) or {}
    title = rec.get("title", "")
    _, summary, why = _summary(root, day)
    mins = int(round(rec.get("minutes") or 10))
    e = htmllib.escape
    subject = f"AI Briefing · Special edition: {title}"[:150]
    text = "\n\n".join(x for x in [f"AI Briefing special edition: {title}", summary, f"Why now: {why}" if why else "",
                                   f"Listen ({mins} min) or read it: {url}",
                                   "The daily briefing is back tomorrow morning.", "Unsubscribe: {{UNSUBSCRIBE}}"] if x)
    html = ("<div style=\"max-width:620px;margin:0 auto;font:16px/1.55 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111827\">"
            "<div style=\"font:700 12px sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#b45309\">AI Briefing · Special edition</div>"
            f"<h1 style=\"font-size:24px;line-height:1.25;margin:6px 0 12px\">{e(title)}</h1>"
            f"<p>{e(summary)}</p>" + (f"<p><b>Why now.</b> {e(why)}</p>" if why else "")
            + f"<p>{_btn(url, f'🎧 Listen · {mins} min')} {_btn(url + '#read', 'Read it', False)}</p>"
            "<p style=\"font-size:13px;color:#6b7280\">An occasional extra, on a day the news can't wait. The daily briefing is "
            "back tomorrow morning. Written and read by AI from public sources; every source is on the page.</p>"
            "<p style=\"font-size:12px;color:#9ca3af\"><a href=\"{{UNSUBSCRIBE}}\" style=\"color:#9ca3af\">Unsubscribe</a></p></div>")
    return {"subject": subject, "text": text, "html": html}


def review_email(root: Path, cfg: dict, day: str, log=print) -> None:
    """The draft and its fact checks to Steven, with how to answer."""
    from . import mailer
    to = mailer.ecfg(cfg).get("test_to")
    if not to:
        return
    rec = latest(root, day) or {}
    with edition() as dd:
        article = dd.written_md(root, day)
    its = fact_items(root, day)
    lines = [f"Special edition draft: {rec.get('title', '')}", "",
             "To send it: say \"release the special\" in chat, or press Release on the dashboard home page.",
             "Changes: tell me your notes, or fact-check choices like \"F1: B\". Unanswered items get my recommendation.", ""]
    for it in its:
        lines += [f"{it['id']} · {it['claim'][:280]}", f"   why: {it['why'][:220]}"]
        if it["proposed"]:
            lines.append(f"   proposed: {it['proposed'][:240]}")
        lines += ["   " + "  ·  ".join(f"{k}) {lab}" for k, lab in it["options"]) + f"   → I recommend {it['rec']}", ""]
    text = "\n".join(lines) + "\n\n" + re.sub(r"\*\*|##\s*", "", article)
    e = htmllib.escape
    facts = "".join(f"<div style='margin:0 0 10px;font-size:13px'><b>{e(it['id'])} · {e(it['claim'][:280])}</b><br>"
                    f"why: {e(it['why'][:220])}" + (f"<br>proposed: {e(it['proposed'][:240])}" if it["proposed"] else "")
                    + "<br>" + e("  ·  ".join(f"{k}) {lab}" for k, lab in it["options"])) + f" → I recommend <b>{it['rec']}</b></div>"
                    for it in its)
    body = "".join(f"<h3 style='font-size:16px;margin:18px 0 4px'>{e(h)}</h3><p>{e(t)}</p>" if h else f"<p>{e(t)}</p>"
                   for h, t in _blocks(article))
    html = (f"<div style='max-width:680px;font:15px/1.55 sans-serif;color:#111827'><h2>{e(rec.get('title', ''))}</h2>"
            f"<p><b>Special edition draft.</b> To send it, say \"release the special\" in chat or press Release on the "
            f"dashboard home page. Changes: your notes, or \"F1: B\".</p>"
            + (f"<div style='padding:12px 14px;border:1px solid #fcd34d;border-radius:10px;background:#fffbeb'>"
               f"<div style='font-weight:700;margin:0 0 6px'>Fact checks ({len(its)})</div>{facts}</div>" if its else "")
            + body + "</div>")
    try:
        mailer.call(cfg, "send", to=to, subject=f"AI Briefing · Special edition draft: {rec.get('title', '')[:90]}",
                    text=text, html=html)
    except Exception as ex:  # noqa: BLE001
        log(f"special review email not sent: {ex}"[:200])
    try:
        from . import ntfy
        ntfy.notify(cfg, "AI Briefing · special edition draft", f"{rec.get('title')}: review email sent; "
                    f"{len(its)} fact check(s).", tags=("notebook",), root=root)
    except Exception:  # noqa: BLE001
        pass


def _blocks(md: str) -> list:
    out = []
    for sec in re.split(r"(?m)^## ", md or ""):
        head, _, body = sec.partition("\n")
        if not body.strip():
            if head.strip():
                out.append(("", head.strip()))
            continue
        paras = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
        out += [(head.strip() if i == 0 else "", p.replace("**", "")) for i, p in enumerate(paras)]
    return out


# ---------- the site page ----------

def site_pages(root: Path, cfg: dict, out: Path, base_url: str, page, md_to_html) -> list:
    """<out>/DAY/special/index.html for each released special (+ its MP3 in <out>/audio). Not in any feed."""
    import shutil
    by_day = {}
    for r in records(root):
        if r.get("status") == "published":
            by_day[r["day"]] = r
    made = []
    with edition() as dd:
        for day, r in sorted(by_day.items()):
            mp3 = Path(root) / DIR / f"{day}.mp3"
            if not mp3.is_file():
                continue
            (out / "audio").mkdir(exist_ok=True)
            shutil.copy2(mp3, out / "audio" / f"special-{day}.mp3")
            md, summary, _ = _summary(root, day)
            head = md.split("## Sources", 1)[0]
            head = re.sub(r"(?m)^# .*\n", "", head).strip()
            head = re.sub(r"(?m)^\*\*Why today\.\*\*.*\n?", "", head)
            src = "## Sources" + md.split("## Sources", 1)[1] if "## Sources" in md else ""
            written = dd.written_md(root, day, cfg)
            title = f"Special edition: {r.get('title', '')}"
            body = (f'<p class="small" style="letter-spacing:.06em;text-transform:uppercase;color:#b45309"><b>AI Briefing · '
                    f'special edition · {dt.date.fromisoformat(day).strftime("%B")} {dt.date.fromisoformat(day).day}</b></p>'
                    + md_to_html(head)
                    + f'<div id="listen"><audio controls preload="none" src="../../audio/special-{day}.mp3"></audio></div>'
                    + f'<section id="read" class="ddread">{md_to_html(written)}</section>' + md_to_html(src)
                    + '<p><a href="../../index.html">The daily AI Briefing</a></p>')
            (out / day / "special").mkdir(parents=True, exist_ok=True)
            (out / day / "special" / "index.html").write_text(page(title, body, "../../", cfg, kind="deepdive"), "utf-8")
            made.append(day)
    return made


def status(root: Path) -> list:
    out = []
    for day in sorted({r["day"] for r in records(root)}, reverse=True):
        r = latest(root, day)
        out.append({"day": day, "title": r.get("title", ""), "status": r.get("status"),
                    "emailed": bool(emailed(root, day)), "facts": len(fact_items(root, day))})
    return out
