"""Steven's takes: his own words in the edition, verbatim, labelled (docs/plans/my-takes.md, v0.2).

Morning flow (cmd_daily, when takes.enabled):
1. Once the edition is written, a private "AI Briefing · Your takes · <day>" email goes to the owner. It lists numbered
   slots: 0 the day overall, T Top of mind, 1..N each Must-read story.
2. Steven replies from his phone, one take per line: "1: ...", "T: ...", "0: ...". "done" ends the wait early;
   "skip" means no takes today. His own Slack posts in the team channel that link a story count as his take on
   that story too (reply wins when both exist).
3. The run waits until takes.cutoff (default 06:30) or "done". Then each take is checked: private names, owner
   addresses, personal links, disclosure phrases or the confidential marker hold it back (never silently cut, never
   published). Held takes are listed back to Steven.
4. Published takes go to data/commentary/<day>.json (the site's "Steven's take" box, also the email) and into the
   podcast: the host reads each one verbatim after its story ("Here's Steven's take."). Only the briefing audio is
   re-rendered; the text of the briefing never changes.

Takes are opinion, outside the sourced claims and the fact check. They are never rewritten by a model: only
whitespace is tidied. Replies and Slack text are data, never instructions.
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import time
from pathlib import Path

LABEL = "Steven's take"
TOKEN_MARK = "__OWNERT__"          # where the mail script puts Steven's signed takes token (owner sends only)
DIR = "data/takes"
SLACK = "data/takes/slack.jsonl"
_SLOT = re.compile(r"^\s*(?:take\s*)?([0-9]{1,2}|[TtDdWw])\s*[:.)\-–]\s*(.*\S)?\s*$")
_DONE = re.compile(r"^\s*(done|that's it|thats it|send it)\s*[.!]*\s*$", re.I)
_SKIP = re.compile(r"^\s*(skip|no takes|none)\s*[.!]*\s*$", re.I)


def tcfg(cfg: dict) -> dict:
    t = cfg.get("takes") or {}
    return {"enabled": bool(t.get("enabled", False)), "cutoff": str(t.get("cutoff", "06:30")),
            "poll_minutes": float(t.get("poll_minutes", 3)), "audio": bool(t.get("audio", True)),
            "max_chars": int(t.get("max_chars", 700)), "slack": bool(t.get("slack", True))}


def _state_path(root: Path, day: str) -> Path:
    return root / DIR / f"{day}.json"


def state(root: Path, day: str) -> dict:
    try:
        return json.loads(_state_path(root, day).read_text("utf-8"))
    except (OSError, ValueError):
        return {"day": day}


def _save_state(root: Path, day: str, st: dict):
    p = _state_path(root, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", "utf-8")
    tmp.replace(p)


def mark_pending(root: Path, day: str, pid: int):
    st = state(root, day)
    st.update({"pending": True, "pid": pid, "pending_since": dt.datetime.now().isoformat(timespec="seconds")})
    st.pop("released_at", None)
    _save_state(root, day, st)


def mark_released(root: Path, day: str):
    st = state(root, day)
    st.update({"pending": False, "released_at": dt.datetime.now().isoformat(timespec="seconds")})
    _save_state(root, day, st)


def _alive(pid) -> bool:
    import os
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def waiting(root: Path, day: str) -> bool:
    """A morning run is holding today's edition for takes right now."""
    st = state(root, day)
    return bool(st.get("pending")) and _alive(st.get("pid"))


def release_now(root: Path, day: str) -> str:
    """Ask the waiting run to stop waiting (./np takes done, or the run queue's takes-done job)."""
    st = state(root, day)
    st["release_requested"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_state(root, day, st)
    return "release requested: the edition goes out within a few minutes" if waiting(root, day) else \
        "nothing is waiting today (noted anyway)"


# ---------------------------------------------------------------- slots
def slots(root: Path, day: str) -> list:
    """[{slot, key, title, summary}]: 0 overall, T Top of mind, then each Must-read story by its number."""
    out = [{"slot": "0", "key": "overall", "title": "The day overall", "summary": ""},
           {"slot": "T", "key": "top", "title": "Top of mind", "summary": ""}]
    p = root / "data" / "stories" / f"{day}.jsonl"
    try:
        rows = [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()]
        stories = rows[-1]["stories"] if rows else []
    except (OSError, ValueError, KeyError):
        stories = []
    from .textutil import item_id
    for s in sorted((s for s in stories if s.get("section") == "must"), key=lambda s: s.get("n", 99)):
        key = s.get("lead_id") or (item_id(s["lead_url"]) if s.get("lead_url") else "")
        if key:
            out.append({"slot": str(s["n"]), "key": key, "title": s.get("headline", ""),
                        "summary": str(s.get("what_happened") or "")[:220], "ids": s.get("ids", []),
                        "lead_url": s.get("lead_url", "")})
    if any(s.get("section") == "worth" for s in stories):
        out.append({"slot": "W", "key": "worth", "title": "Worth knowing", "summary": ""})
    return out


# ---------------------------------------------------------------- the private email
def subject(day: str) -> str:
    d = dt.date.fromisoformat(day)
    return f"AI Briefing · Your takes · {d.strftime('%a %b')} {d.day}"


def _reply_link(cfg: dict, day: str, slot: str) -> str:
    """A mailto that opens a reply to the takes email with the slot number filled in ("2: ")."""
    from urllib.parse import quote
    from .mailsource import mcfg
    to = mcfg(cfg).get("account") or ""
    return f"mailto:{to}?subject={quote('Re: ' + subject(day))}&body={quote(slot + ': ')}"


def _li(md: str) -> str:
    from . import mailer
    return mailer._inline(md, light=True)


def build_email(root: Path, cfg: dict, day: str) -> dict:
    """The whole edition, read in the email, with an "Add your take" button after each section (v0.2.5, Steven
    2026-10-25: read, then type an observation after each main section). Mail clients strip real text boxes, so
    each button opens a reply with the section's number filled in; several replies are merged."""
    from . import mailer
    t = tcfg(cfg)
    sl = {s["slot"]: s for s in slots(root, day)}
    md_file = root / cfg.get("paths", {}).get("briefings", "briefings") / f"{day}.md"
    b = mailer.parse(md_file.read_text("utf-8")) if md_file.exists() else {"brief": "", "top": [], "must": []}
    base = ((cfg.get("publish") or {}).get("site_url") or "https://sgwoods.github.io/ai-briefing/").rstrip("/")
    page = f"{base}/{day}/"
    esc = htmllib.escape
    intro = (f"Today's edition is written and held until {t['cutoff']} for your takes. Read each section, then tap "
             f"\"Add your take\": a reply opens with the section number filled in. Type and send; send as many as you "
             f"like. Reply \"done\" to send the edition early, \"skip\" for none. Your words go in verbatim as "
             f"\"{LABEL}\" in the written edition, the email and the podcast. Anything with a private name or detail is "
             f"held back and listed to you, never published.")
    btn = lambda slot: (f'<p style="margin:10px 0 0"><a href="{esc(_reply_link(cfg, day, slot), quote=True)}" '  # noqa: E731
                        f'style="display:inline-block;padding:8px 14px;border-radius:999px;background:#2563eb;color:#fff;'
                        f'text-decoration:none;font-size:14px">✍ Add your take on this ({esc(slot)})</a></p>')
    card = 'style="padding:16px 18px;background:#fff;border:1px solid #e5e7eb;border-radius:12px;margin:0 0 12px"'
    P = 'style="margin:0 0 8px;font-size:15px;line-height:1.55;color:#111827"'
    H = [f'<div style="max-width:660px;margin:0 auto;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif">',
         f'<p {P}>{esc(intro)}</p>'
         f'<p {P}><a href="{esc(page)}#takes=__OWNERT__" style="display:inline-block;padding:8px 14px;'
         f'border-radius:999px;background:#111827;color:#fff;text-decoration:none">✍ Read and comment on the site'
         f'</a> &nbsp; one box after each section, one Submit (your private link, valid two days).</p>'
         f'<p {P}><a href="{esc(page)}">Read today\'s page as readers will see it</a>.</p>']
    L = [subject(day), "", intro, "", f"Read and comment on the site (private link): {page}#takes=__OWNERT__",
         f"Today's page: {page}", ""]
    H.append(f'<div {card}><div style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#6b7280">'
             f'0 · The day overall</div><p {P}>{_li(b.get("brief", ""))}</p>{btn("0")}</div>')
    L += ["0: The day overall", "   " + mailer._strip_md(b.get("brief", "")), ""]
    if b.get("top"):
        lis = "".join(f'<li style="margin:0 0 6px;font-size:15px;line-height:1.5">{_li(x)}</li>' for x in b["top"])
        H.append(f'<div {card}><div style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#6b7280">'
                 f'T · Top of mind</div><ul style="margin:6px 0 0;padding-left:20px">{lis}</ul>{btn("T")}</div>')
        L += ["T: Top of mind"] + [f"   - {mailer._strip_md(x)}" for x in b["top"]] + [""]
    for n, s in enumerate(b.get("must", []), 1):
        slot = str(n)
        if slot not in sl:
            continue
        rows = [f'<div style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#6b7280">{esc(slot)} · '
                f'Must read</div><div style="font-size:17px;font-weight:600;margin:4px 0 6px">{esc(s["headline"])}</div>']
        for label, key in (("What happened", "what"), ("In today's deep dive", "deep"), ("Evidence check", "crit"),
                           (s.get("editor_label") or "Our read", "editor"), ("For early-stage", "early"),
                           (s.get("other_label") or "", "other")):
            if s.get(key):
                rows.append(f'<p {P}><span style="color:#6b7280">{esc(label)}:</span> {_li(s[key])}</p>')
        if s.get("url"):
            rows.append(f'<p style="margin:0;font-size:13px"><a href="{esc(s["url"])}">Source</a></p>')
        H.append(f'<div {card}>{"".join(rows)}{btn(slot)}</div>')
        L += [f"{slot}: {s['headline']}", "   " + mailer._strip_md(s.get("what", "")), ""]
    if b.get("worth") and "W" in sl:
        lis = "".join(f'<li style="margin:0 0 6px;font-size:15px;line-height:1.5">{_li(x)}</li>' for x in b["worth"])
        H.append(f'<div {card}><div style="font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#6b7280">'
                 f'W · Worth knowing</div><ul style="margin:6px 0 0;padding-left:20px">{lis}</ul>{btn("W")}</div>')
        L += ["W: Worth knowing"] + [f"   - {mailer._strip_md(x)}" for x in b["worth"]] + [""]
    H.append('<p style="color:#6b7280;font-size:13px">Or reply to this email with one take per line: "1: ...", '
             '"T: ...", "0: ...", then "done".</p></div>')
    L += ["Reply with one take per line, e.g.:", "1: The margin story matters more than the headline.", "done"]
    return {"subject": subject(day), "text": "\n".join(L), "html": "".join(H)}


def send_email(root: Path, cfg: dict, day: str, log=print) -> str:
    st = state(root, day)
    if st.get("emailed_at"):
        return f"takes email already sent at {st['emailed_at'][11:16]}"
    from . import mailer
    m = build_email(root, cfg, day)
    to = mailer.ecfg(cfg).get("test_to")
    if not to:
        return "takes email skipped: email.test_to (the owner's address) is not set"
    # content is defused (no placeholder can come from a story); only this template adds the takes token
    fill = lambda s: mailer.defuse(s).replace(TOKEN_MARK, "{{OWNERT}}")  # noqa: E731
    r = mailer.call(cfg, "send", subject=m["subject"], html=fill(m["html"]), text=fill(m["text"]), to=to)
    st["emailed_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_state(root, day, st)
    return "takes email sent to the owner" + ("" if (r or {}).get("ok", True) else f" (mailer: {r})")


# ---------------------------------------------------------------- parsing
def tidy(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", " ", text or "")).strip()


def parse(text: str) -> dict:
    """A reply -> {"takes": {slot: text}, "done": bool, "skip": bool}. Continuation lines join the take above."""
    takes, cur, done, skip = {}, None, False, False
    for ln in (text or "").replace("\r\n", "\n").split("\n"):
        if _DONE.match(ln):
            done = True
            cur = None
            continue
        if _SKIP.match(ln):
            skip = True
            cur = None
            continue
        m = _SLOT.match(ln)
        if m:
            cur = m.group(1).upper()
            takes[cur] = (m.group(2) or "").strip()
            continue
        if cur and ln.strip():
            takes[cur] = (takes[cur] + " " + ln.strip()).strip()
        elif not ln.strip():
            cur = None
    return {"takes": {k: tidy(v) for k, v in takes.items() if tidy(v)}, "done": done, "skip": skip}


def fetch_replies(root: Path, cfg: dict, day: str, log=print) -> list:
    """Owner replies to today's takes email, oldest first: [{received, takes, done, skip}]. Read-only."""
    import email
    import email.utils
    from . import feedback, mailsource
    from .mailsource import _body, _hdr
    from .textutil import html_to_text
    editor = {a.lower() for a in feedback.fcfg(cfg)["editor"]}
    box = mailsource.connect(cfg, "feedback")
    out = []
    try:
        typ, _ = box.select(feedback.fcfg(cfg)["label"], readonly=True)       # the same calls feedback.fetch makes
        if typ != "OK":
            raise RuntimeError(f"Gmail label {feedback.fcfg(cfg)['label']!r} not found")
        since = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).strftime("%d-%b-%Y")
        typ, data = box.search(None, "SINCE", since)
        for u in (data[0].split() if typ == "OK" and data and data[0] else [])[-200:]:
            typ, msg_data = box.fetch(u, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subj = _hdr(msg, "Subject")
            if "your takes" not in subj.lower() or subject(day).split("· ", 2)[-1].lower() not in subj.lower():
                continue
            addr = email.utils.parseaddr(_hdr(msg, "From"))[1].lower()
            if addr not in editor:
                continue
            html, text = _body(msg)
            body = feedback.reply_text(text or html_to_text(html))
            try:
                when = email.utils.parsedate_to_datetime(msg.get("Date")).isoformat()
            except (TypeError, ValueError):
                when = ""
            out.append({"received": when, **parse(body)})
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    return sorted(out, key=lambda r: r["received"])


def fetch_site(cfg: dict, day: str) -> list:
    """Takes Steven submitted on the site page (Apps Script 'takes' tab), as reply-like rows, oldest first."""
    from . import mailer
    r = mailer.call(cfg, "takes_pull", d=day)
    rows = sorted((x for x in (r.get("takes") or []) if isinstance(x, dict)), key=lambda x: str(x.get("at", "")))
    out = []
    for x in rows:
        if x.get("done") or str(x.get("slot")) == "DONE":
            out.append({"received": str(x.get("at", "")), "takes": {}, "done": True, "skip": False, "via": "site"})
            continue
        slot = str(x.get("slot", "")).upper()
        if re.fullmatch(r"\d{1,2}|T|W", slot) and str(x.get("text", "")).strip():
            out.append({"received": str(x.get("at", "")), "takes": {slot: tidy(str(x["text"]))}, "done": False,
                        "skip": False, "via": "site"})
    return out


def fetch_all(root: Path, cfg: dict, day: str, log=print) -> list:
    """Email replies and site takes together, oldest first (a later take for a slot replaces an earlier one)."""
    rows = []
    try:
        rows += fetch_replies(root, cfg, day, log)
    except Exception as e:  # noqa: BLE001
        log(f"takes: mailbox read failed ({e})")
    try:
        rows += fetch_site(cfg, day)
    except Exception as e:  # noqa: BLE001
        log(f"takes: site takes read failed ({e})")
    return sorted(rows, key=lambda r: str(r.get("received", "")))


# ---------------------------------------------------------------- Slack
def slack_text(text: str) -> str:
    """Steven's own words in a Slack post: links, mentions and channel refs removed."""
    t = re.sub(r"<(?:https?://|mailto:)[^>]*>", "", text or "")
    t = re.sub(r"<[@#!][^>]*>", "", t)
    t = re.sub(r"https?://\S+", "", t)
    return tidy(t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def add_slack(root: Path, rows: list):
    if not rows:
        return
    from .archive import append_jsonl
    p = root / SLACK
    p.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if p.exists():
        for x in p.read_text("utf-8").splitlines():
            try:
                r = json.loads(x)
                seen.add((r.get("ts"), r.get("id")))
            except ValueError:
                pass
    append_jsonl(p, [r for r in rows if (r.get("ts"), r.get("id")) not in seen])


def slack_takes(root: Path, day: str, sl: list, hours: int = 30) -> dict:
    """{slot: text} from Steven's own Slack posts in the last `hours` that link one of today's stories."""
    p = root / SLACK
    if not p.exists():
        return {}
    end = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(23, 59)).astimezone()
    start = end - dt.timedelta(hours=hours + 24)
    by_id = {}
    for s in sl:
        for i in s.get("ids", []) + [s["key"]]:
            by_id[i] = s["slot"]
    out = {}
    for x in p.read_text("utf-8").splitlines():
        try:
            r = json.loads(x)
            when = dt.datetime.fromisoformat(r["at"])
        except (ValueError, KeyError):
            continue
        if not (start <= when <= end) or not r.get("text"):
            continue
        slot = by_id.get(r.get("id"))
        if slot:
            out[slot] = r["text"]
    return out


# ---------------------------------------------------------------- privacy
def problems(text: str, cfg: dict) -> list:
    """Why a take can't be published as written (empty = fine). Same tests the site and email gates apply."""
    from . import links, stages
    out = []
    _, hits = stages.scrub_private(text, stages.private_names(), ())
    if hits:
        out.append("a private name: " + ", ".join(sorted(set(hits)))[:80])
    _, gone = links.scrub_output(text, cfg)
    if gone:
        out.append("a personal link or address")
    if links.DISCLOSURE_FLAG.search(text):
        out.append("a disclosure phrase the site gate blocks")
    try:
        from .owner import addresses
        if any(a and a.lower() in text.lower() for a in addresses()):
            out.append("one of the owner's addresses")
    except Exception:  # noqa: BLE001
        pass
    try:
        from .export import MARKER                         # the confidential edition's marker (private module)
    except ImportError:
        MARKER = ""
    if MARKER and MARKER.upper() in text.upper().replace(" ", "-"):
        out.append("the confidential marker")
    return out


# ---------------------------------------------------------------- collect and wait
def collect(root: Path, cfg: dict, day: str, replies: list | None = None, log=print) -> dict:
    """Merge reply and Slack takes, check each, publish the clean ones to commentary. -> state."""
    from dashboard import notes
    t = tcfg(cfg)
    st = state(root, day)
    sl = slots(root, day)
    by_slot = {s["slot"]: s for s in sl}
    merged, origin = {}, {}
    if t["slack"]:
        for k, v in slack_takes(root, day, sl).items():
            merged[k], origin[k] = v, "slack"
    st["skip"] = any(r.get("skip") for r in replies or [])      # from this read of the replies, not sticky
    st["done"] = any(r.get("done") for r in replies or [])
    for r in replies or []:
        for k, v in r["takes"].items():
            merged[k], origin[k] = v, "reply"
    if st.get("skip"):
        merged = {}
    published, held, unknown = [], [], []
    for k, text in sorted(merged.items()):
        s = by_slot.get(k)
        if not s:
            unknown.append({"slot": k, "text": text[:200]})
            continue
        text = text[:t["max_chars"]]
        why = problems(text, cfg)
        if why:
            held.append({"slot": k, "title": s["title"], "text": text, "why": why, "from": origin[k]})
            continue
        cur = notes.load(root, day).get("notes", {}).get(s["key"], {})
        if cur.get("text") != text:
            notes.save(root, day, s["key"], text, title=s["title"])
        published.append({"slot": k, "key": s["key"], "title": s["title"], "text": text, "from": origin[k]})
    st.update({"published": published, "held": held, "unknown": unknown,
               "collected_at": dt.datetime.now().isoformat(timespec="seconds")})
    _save_state(root, day, st)
    return st


def _slack_refresh(root: Path, cfg: dict, log=print):
    """Pick up Slack posts Steven makes while the edition waits (his words only; links are not briefed today)."""
    if not tcfg(cfg)["slack"] or not (cfg.get("slack") or {}).get("enabled"):
        return
    try:
        from . import slacksource
        lg = type("L", (), {"info": staticmethod(lambda *a: None), "warning": staticmethod(lambda *a: None)})()
        slacksource.fetch(root, cfg, "takes", lg, lookback_hours=12)
    except Exception as e:  # noqa: BLE001
        log(f"takes: Slack read failed ({e})")


def _cutoff(cfg: dict, day: str) -> dt.datetime:
    h, m = (int(x) for x in tcfg(cfg)["cutoff"].split(":"))
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(h, m))


def wait(root: Path, cfg: dict, day: str, log=print, now=dt.datetime.now, sleep=time.sleep, fetch=None) -> dict:
    """Poll for replies until the cutoff, "done" or "skip"; then collect. Never raises: no takes = today as before."""
    fetch = fetch or (lambda: (_slack_refresh(root, cfg, log), fetch_all(root, cfg, day, log))[1])
    end = _cutoff(cfg, day)
    replies = []
    while True:
        try:
            replies = fetch()
        except Exception as e:  # noqa: BLE001
            log(f"takes: mailbox read failed ({e}); trying again")
        if any(r.get("done") or r.get("skip") for r in replies) or now() >= end or \
                state(root, day).get("release_requested"):
            break
        left = (end - now()).total_seconds()
        sleep(max(1.0, min(max(30.0, tcfg(cfg)["poll_minutes"] * 60), left)))
    st = collect(root, cfg, day, replies, log)
    log(f"takes: {len(st['published'])} published, {len(st['held'])} held"
        + (" (skip)" if st.get("skip") else "") + (" (done)" if st.get("done") else " (cutoff)"))
    return st


def report_email(root: Path, cfg: dict, day: str, st: dict) -> str:
    """Tell Steven what was held (only when something was): the text stays with him, never published."""
    if not st.get("held") and not st.get("unknown"):
        return ""
    from . import mailer
    L = [f"Takes for {day}: {len(st.get('published', []))} published."]
    for h in st.get("held", []):
        L.append(f"HELD {h['slot']} ({h['title'][:60]}): {'; '.join(h['why'])}. Reword and reply again, or leave it.")
    for u in st.get("unknown", []):
        L.append(f"No slot {u['slot']} today: {u['text'][:80]}")
    text = "\n".join(L)
    html = "".join(f"<p>{htmllib.escape(x)}</p>" for x in L)
    to = mailer.ecfg(cfg).get("test_to")
    mailer.call(cfg, "send", subject=f"AI Briefing · Your takes · held back · {day}", html=mailer.defuse(html),
                text=mailer.defuse(text), to=to)
    return "held-takes note sent to the owner"


# ---------------------------------------------------------------- audio
def audio_parts(parts: list, st: dict) -> list:
    """Insert each published take after its section: story N after 'Story N', T after the intro, 0 before the close."""
    from . import speech
    pub = {p["slot"]: p["text"] for p in st.get("published", [])}
    if not pub:
        return parts
    table = speech.load_table(Path(__file__).resolve().parent.parent)
    say = lambda s: speech.spoken(s, table)  # noqa: E731
    out = []
    for name, text in parts:
        if name == "Close" and "0" in pub:
            out.append(("Take overall", say(f"And {LABEL} on the day. {pub['0']}")))
        out.append((name, text))
        if name == "Quick hits" and "W" in pub:
            out.append(("Take worth", say(f"{LABEL} on the quick hits. {pub['W']}")))
        if name == "Intro" and "T" in pub:
            out.append(("Take top", say(f"{LABEL} on the top of the day. {pub['T']}")))
        m = re.fullmatch(r"Story (\d+)", name)
        if m and m.group(1) in pub:
            out.append((f"Take {m.group(1)}", say(f"Here's {LABEL}. {pub[m.group(1)]}")))
    voiced = {m.group(1) for n, _ in parts for m in [re.fullmatch(r"Story (\d+)", n)] if m}
    rest = [p for p in st.get("published", []) if p["slot"].isdigit() and p["slot"] != "0" and p["slot"] not in voiced]
    if rest:                                     # stories the episode covers only as quick hits (or not at all)
        extra = [(f"Take {p['slot']}", say(f"On {p.get('title') or 'another story'}, here's {LABEL}. {p['text']}"))
                 for p in rest]
        i = next((k + 1 for k, (n, _) in enumerate(out) if n == "Quick hits"),
                 next((k for k, (n, _) in enumerate(out) if n in ("Take overall", "Close")), len(out)))
        out[i:i] = extra
    if "0" in pub and not any(n == "Take overall" for n, _ in out):
        out.append(("Take overall", say(f"And {LABEL} on the day. {pub['0']}")))
    return out


def read_spoken(path: Path) -> list:
    parts, name, buf = [], None, []
    for ln in path.read_text("utf-8").split("\n"):
        m = re.fullmatch(r"\[(.+)\]", ln.strip())
        if m:
            if name is not None:
                parts.append((name, "\n".join(buf).strip()))
            name, buf = m.group(1), []
        elif name is not None:
            buf.append(ln)
    if name is not None:
        parts.append((name, "\n".join(buf).strip()))
    return parts


def revoice(root: Path, cfg: dict, day: str, st: dict, log=print) -> str:
    """Re-render the briefing MP3 with the takes spliced in (from the take-free spoken text, so it's repeatable)."""
    from . import audio
    if not st.get("published") or not tcfg(cfg)["audio"]:
        return "audio unchanged (no takes)"
    bdir = root / cfg["paths"]["briefings"]
    base = bdir / f"{day}.spoken.txt"
    if not base.exists():
        return "audio unchanged (no spoken script)"
    parts = audio_parts(read_spoken(base), st)
    (bdir / f"{day}.spoken-takes.txt").write_text("\n\n".join(f"[{n}]\n{t}" for n, t in parts) + "\n", "utf-8")
    eng = audio.engine_from(cfg)
    title = audio.parse_briefing((bdir / f"{day}.md").read_text("utf-8"))["title"]
    mp3 = bdir / f"{day}.mp3"
    minutes = audio.render_mp3(eng, parts, mp3, title, (cfg.get("audio") or {}).get("bitrate", "64k"))
    delivered = audio.deliver(cfg, mp3, type("L", (), {"info": staticmethod(log), "warning": staticmethod(log)})())
    return f"audio re-rendered with {len(st['published'])} take(s): {minutes:.1f} min ({delivered})"
