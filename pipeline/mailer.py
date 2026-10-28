"""Daily email to subscribers, sent through Steven's Google Apps Script (scripts/apps-script/Code.gs).

The list lives in Steven's Google Sheet, never in this repo. This module only:
  - renders the briefing as an email in the public site's look (email-safe: tables + inline styles)
  - asks the script to list / add / remove subscribers or send (key EMAIL_SCRIPT_KEY in .env)
  - logs each send (counts only, no addresses) to data/email-log.jsonl

config.yaml  email.enabled, email.script_url, email.subject, email.mailing_address
.env         EMAIL_SCRIPT_KEY=<same as the script's SECRET property>
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import os
import re
from pathlib import Path

from .archive import append_jsonl, read_jsonl

LOG = "data/email-log.jsonl"
C = {"bg": "#07131f", "panel": "#0c2236", "card": "#112a42", "border": "#23415d", "text": "#eff7ff",
     "muted": "#9cc4df", "strong": "#d7ecff", "accent": "#67e6a8", "accent_ink": "#06221a", "link": "#d9f7ff",
     "brand": "#3e7e8a", "brand_deep": "#36707c", "brand_ink": "#e8f5f7"}   # brand: the teal of Steven's photo
TAGLINE = "Slowly, then fast. Every morning."                  # Steven 2026-10-27; email.tagline overrides
DD_TAGLINE = "One story, slowly. Down to the details."          # the deep dive's line (Steven 2026-10-27)
PHOTO = "steven-woods.jpg"                                     # assets/, copied to the site root on each build
FONT = "'Avenir Next','Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,Arial,sans-serif"


class MailError(RuntimeError):
    pass


def ecfg(cfg: dict) -> dict:
    return {"enabled": False, "script_url": "", "subject": "AI Briefing · {date}: {lead}", "mailing_address": "",
            "ratings": False,          # true once the deployed Code.gs has the rate action (stars in the email)
            **(cfg.get("email") or {})}


def key() -> str:
    from .vault import get
    return get("EMAIL_SCRIPT_KEY")


def ready(cfg: dict) -> str:
    """'' when everything is set up, else what is missing."""
    e = ecfg(cfg)
    if not e["script_url"].startswith("https://script.google.com/"):
        return "email.script_url is not set in config.yaml (see docs/EMAIL-SETUP.md)"
    if len(key()) < 24:
        return "EMAIL_SCRIPT_KEY is not set in .env (at least 24 characters, same as the script's SECRET)"
    return ""


READ_ACTIONS = ("list", "ratings", "ddactions", "companylist", "takes_pull", "getapprovals")   # change nothing
OWNER_ONLY = ("approvalmail",)    # the script sends these to OWNER_EMAIL only: never gated (an approval unblocks the gate)


def call(cfg: dict, action: str, _alert: bool = False, **params) -> dict:
    missing = ready(cfg)
    if missing:
        raise MailError(missing)
    from .env import mark_subject, staging
    from .release import ROOT as _root
    owners = {a.strip().lower() for a in [ecfg(cfg).get("test_to") or ""] if a.strip()}
    to_owner = action == "send" and str(params.get("to", "")).strip().lower() in owners
    if staging(_root):                           # development checkout: reads, and review copies to the owner only
        if action not in READ_ACTIONS and not to_owner:
            raise MailError(f"email {action} is switched off in staging (only sends to the owner's own address)")
        if "subject" in params:
            params["subject"] = mark_subject(params["subject"])
    if _alert:                                   # pipeline/alerts.py: owner-only action-needed email, never gated
        if not to_owner:
            raise MailError("alert emails go to the owner address only")
    elif action in OWNER_ONLY:
        if staging(_root):
            raise MailError(f"email {action} is switched off in staging")
    elif action not in READ_ACTIONS:             # anything that sends or changes: release gate first
        from .release import ReleaseBlocked, require
        try:
            require(_root, cfg, f"email {action}", staging_ok=to_owner)
        except ReleaseBlocked as e:
            raise MailError(str(e)) from e
    import httpx
    try:
        r = httpx.post(ecfg(cfg)["script_url"], data={"action": action, "key": key(), **params},
                       follow_redirects=True, timeout=180)
    except Exception as e:  # noqa: BLE001
        raise MailError(f"script call {action} failed: {type(e).__name__}: {e}"[:300]) from e
    try:
        out = r.json()
    except ValueError:
        # Apps Script answers with an HTML page when the script itself fails (e.g. needs re-authorizing)
        body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", r.text)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
        raise MailError(f"script returned HTTP {r.status_code}, not JSON: {text[:300]}")
    if not out.get("ok"):
        raise MailError(f"script {action}: {out.get('error', out)}")
    return out


def subscribers(cfg: dict) -> dict:
    return call(cfg, "list")


def ratings(cfg: dict) -> list:
    """Star ratings from the email and the site (no addresses): [{day, who, score, note, at, src, id}]."""
    return call(cfg, "ratings").get("ratings") or []


def stars_block(day: str, big: bool = True) -> str:
    """Five one-click stars; each recipient's {{RATE}} link is filled in by the script."""
    size = 34 if big else 24
    cells = "".join(
        f'<td align="center" style="padding:0 4px"><a href="{{{{RATE}}}}&amp;s={n}" title="{n} of 5" '
        f'style="text-decoration:none;color:#ffd166;font-size:{size}px;line-height:1">&#9733;</a>'
        f'<div style="font-size:11px;color:{C["muted"]};margin-top:2px">{n}</div></td>' for n in range(1, 6))
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 4px"><tr>{cells}</tr></table>')


def add(cfg: dict, email: str, confirmed_note: str = "", source: str = "dashboard") -> dict:
    return call(cfg, "add", email=email.strip(), confirmed=confirmed_note, source=source)


def remove(cfg: dict, email: str) -> dict:
    return call(cfg, "remove", email=email.strip())


def remind(cfg: dict, emails: list | None = None) -> dict:
    """One reminder to pending sign-ups (all, or these); the mail script sends each at most once a week."""
    return call(cfg, "remind", emails=",".join(emails or []))


def expire(cfg: dict) -> dict:
    """Pending 14 days after their reminder -> expired (Steven, 2026-10-27). They can always sign up again."""
    return call(cfg, "expire")


def counts(cfg: dict, subs: list) -> dict:
    """Subscriber counts by status, without the owner's own addresses (his test copy; Steven, 2026-10-27)."""
    owners = {a.strip().lower() for a in [ecfg(cfg).get("test_to") or ""] if a.strip()}
    try:
        from .owner import addresses
        owners |= {a.lower() for a in addresses() if a}
    except Exception:  # noqa: BLE001
        pass
    out = {}
    for x in subs:
        e = str(x.get("email", "")).lower()
        if e in owners or e.split("+")[0] + "@" + e.split("@")[-1] in owners:
            continue
        out[x.get("status", "?")] = out.get(x.get("status", "?"), 0) + 1
    return out


# ---------- rendering ----------

def _inline(md: str, light: bool = False) -> str:
    """One line of briefing Markdown → safe inline HTML (bold, links), styled for email (dark, or light=True for
    a white background such as the private takes email)."""
    s = htmllib.escape(md, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", rf'<strong style="color:{"#111827" if light else C["strong"]}">\1</strong>', s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               lambda m: f'<a href="{htmllib.escape(m.group(2))}" style="color:{"#2563eb" if light else C["link"]}">'
                         f'{m.group(1)}</a>', s)
    return s


def _strip_refs(s: str) -> str:
    return re.sub(r"\s*\[\d+\]\(https?://[^)]+\)", "", s).strip()


def parse(md: str) -> dict:
    from .textutil import is_merged, legacy_top
    merged = is_merged(md)
    md = legacy_top(md)
    title = md.splitlines()[0].lstrip("# ").strip() if md.startswith("# ") else "AI Briefing"
    brief = re.search(r"\*\*The day in brief\.\*\* (.+)", md)
    secs = {m.group(1).strip(): m.group(2) for m in re.finditer(r"(?ms)^## (.+?)\n(.*?)(?=^## |^---|\Z)", md)}
    top = [_strip_refs(ln[2:]) for ln in secs.get("Top of mind", "").splitlines() if ln.startswith("- ")]
    must = []
    for block in re.split(r"(?m)^### ", secs.get("Must read", ""))[1:]:
        lines = block.strip().splitlines()
        head = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
        who = re.sub(r"\s*·\s*\[source\]\(.*", "", lines[1] if len(lines) > 1 else "").replace("**", "").strip()
        src = re.search(r"\[source\]\((https?://[^)]+)\)", block)
        what = re.search(r"- \*\*What happened:\*\* (.+)", block)
        crit = re.search(r"- \*\*(?:Critical pass|Evidence check):\*\* (.+)", block)
        ed = re.search(r"- \*\*(Editor's view|Our read):\*\* (.+)", block)
        ol = re.search(r"- \*\*(The (?:AGI-forward|AI-realist|sceptic's|market|policy) view):\*\* (.+)", block)
        dev = re.search(r"^\*(Developing story[^*]+)\*$", block, re.M)
        es = re.search(r"- \*\*For early-stage:\*\* (.+)", block)
        dd = re.search(r"- \*\*Today's deep dive:\*\* (.+)", block)
        must.append({"headline": head, "who": who, "url": src.group(1) if src else "",
                     "what": what.group(1) if what else "", "crit": crit.group(1) if crit else "",
                     "editor": ed.group(2) if ed else "", "editor_label": ed.group(1) if ed else "",
                     "other": ol.group(2) if ol else "", "other_label": ol.group(1) if ol else "", "developing": dev.group(1) if dev else "",
                     "early": es.group(1) if es else "", "deep": dd.group(1) if dd else ""})
    worth = [re.sub(r"^\*\*\d+\.\s*", "**", ln[2:]) for ln in secs.get("Worth knowing", "").splitlines() if ln.startswith("- ")]
    questions = [_strip_refs(ln[2:]) for ln in secs.get("Open questions", "").splitlines() if ln.startswith("- ")]
    rr = None
    rs = secs.get("Recommended reading", "")
    m = re.search(r"\*\*\[(.+?)\]\((https?://[^)]+)\)\*\*\s*·?\s*(.*)", rs)
    if m:
        why = re.search(r"\*Why it matters:\*\s*(.+)", rs)
        rr = {"title": m.group(1), "url": m.group(2), "who": m.group(3).strip(), "why": why.group(1).strip() if why else ""}
    return {"title": title, "brief": brief.group(1).strip() if brief else "", "top": top, "must": must,
            "worth": worth, "questions": questions, "reading": rr, "merged": merged}


def _not_org() -> str:
    """", not your firm's" (the owner's employer, owner.yaml org), or nothing."""
    from .owner import get as owner
    org = owner()["org"]
    return f", not {htmllib.escape(org)}'s" if org else ""


def _btn(href: str, label: str, primary: bool = True) -> str:
    bg, ink, bd = (C["accent"], C["accent_ink"], C["accent"]) if primary else (C["card"], C["text"], C["border"])
    return (f'<a href="{htmllib.escape(href)}" style="display:inline-block;padding:11px 18px;border-radius:999px;'
            f'background:{bg};color:{ink};border:1px solid {bd};text-decoration:none;font-weight:600;font-size:14px;'
            f'letter-spacing:.03em;margin:4px 6px 4px 0">{label}</a>')


def _label(t: str) -> str:
    return (f'<div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:{C["muted"]};'
            f'margin:0 0 10px">{t}</div>')


def defuse(s: str) -> str:
    """Content can never carry a mail-script placeholder ({{UNSUBSCRIBE}}, {{RATE}}, {{OWNER}}, {{SCRIPT}}):
    the script fills them per recipient, so one inside a story would hand out readers' or Steven's tokens
    (security review 2026-10-18, H1). Braces in content are broken up; only the template adds placeholders."""
    return re.sub(r"\{\s*\{|%7B%7B|&#123;&#123;", "{ {", str(s or ""), flags=re.I).replace("}}", "} }")


TEMPLATE_PLACEHOLDERS = {"{{UNSUBSCRIBE}}", "{{RATE}}"}


def privacy_gate(msg: dict, cfg: dict) -> list:
    """The last check before subscribers get an email (security review 2026-10-18, H3): problems, empty = send."""
    from . import stages
    from .links import DISCLOSURE_FLAG, is_tracker, personal, personal_addresses
    text = "\n".join(str(msg.get(k, "")) for k in ("subject", "text", "html"))
    plain = re.sub(r"<[^>]+>", " ", htmllib.unescape(text))
    bad = []
    names = stages.private_names()
    _, hits = stages.scrub_private(plain, names, stages.allowed_names(names, []))
    bad += [f"private name: {h}" for h in sorted(set(hits))]
    bad += [f"owner or board-seat mention: {m.group(0)[:40]}" for m in DISCLOSURE_FLAG.finditer(plain)][:3]
    for u in re.findall(r'href="([^"]+)"', str(msg.get("html", ""))) + re.findall(r"https?://\S+", str(msg.get("text", ""))):
        u = htmllib.unescape(u)
        if "{{" in u:
            continue
        if personal(u, cfg) or is_tracker(u):
            bad.append(f"personal or tracking link: {u[:70]}")
    bad += [f"address: {a}" for a in personal_addresses(cfg) if "@" in a and a in text.lower()]
    stray = set(re.findall(r"\{\{[A-Z_]+\}\}", text)) - TEMPLATE_PLACEHOLDERS
    bad += [f"unexpected placeholder: {p}" for p in sorted(stray)]
    return list(dict.fromkeys(bad))[:10]


def day_takes(root: Path, day: str) -> dict:
    """Steven's published takes for DAY ({key: text}): data/commentary/<day>.json (pipeline/takes.py, dashboard)."""
    p = root / "data" / "commentary" / f"{day}.json"
    try:
        notes = json.loads(p.read_text("utf-8")).get("notes", {})
    except (OSError, ValueError):
        return {}
    return {k: str(v.get("text", "")).strip() for k, v in notes.items() if str(v.get("text", "")).strip()}


def _take_html(text: str) -> str:
    from .takes import LABEL
    return (f'<p style="margin:8px 0 0;padding:8px 12px;border-left:3px solid {C["strong"]};background:{C["card"]};'
            f'border-radius:0 12px 12px 0;color:{C["text"]};font-size:14px;line-height:1.5">'
            f'<span style="color:{C["strong"]};font-size:11px;letter-spacing:.12em;text-transform:uppercase">'
            f'{htmllib.escape(LABEL)}</span><br>{htmllib.escape(defuse(text))}</p>')


def render(day: str, md: str, cfg: dict, has_audio: bool = False, deep: dict | None = None,
           takes: dict | None = None) -> dict:
    """→ {"subject", "html", "text"} with {{UNSUBSCRIBE}} where each recipient's link goes.
    takes: {key: text} from day_takes(): "overall", "top", or a story's item id."""
    from .textutil import item_id
    takes = takes or {}
    md = defuse(md)
    if deep:
        deep = {k: (defuse(v) if isinstance(v, str) else v) for k, v in deep.items()}
    from .site import site_cfg
    sc = site_cfg(cfg)
    e = ecfg(cfg)
    b = parse(md)
    base = ((cfg.get("publish") or {}).get("site_url") or "https://sgwoods.github.io/ai-briefing/").rstrip("/")
    page = f"{base}/{day}/"
    feed = f"{base}/podcast.xml"
    lead = re.sub(r"\*\*(.+?)\.?\*\*.*", r"\1", b["top"][0]) if b["top"] else b["title"]
    date = dt.date.fromisoformat(day)
    subject = e["subject"].format(date=f"{date.strftime('%a %b')} {date.day}", lead=lead.rstrip("."), title=b["title"])[:150]
    cell = f'style="padding:22px 26px;background:{C["panel"]};border:1px solid {C["border"]};border-radius:20px"'
    P = f'style="margin:0 0 12px;color:{C["text"]};font-size:16px;line-height:1.6"'
    H = []
    # masthead: Steven's photo and colour, the name and the tagline (v0.2.12)
    who = sc.get("name") or "Steven Woods"
    H.append(f'<tr><td style="padding:16px 20px;background:{C["brand"]};border-radius:20px">'
             f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>'
             f'<td width="64" style="width:64px;padding:0 14px 0 0;vertical-align:middle">'
             f'<img src="{htmllib.escape(base)}/{PHOTO}" width="64" height="64" alt="{htmllib.escape(who)}" '
             f'style="display:block;width:64px;height:64px;border-radius:50%;border:2px solid {C["brand_ink"]}"></td>'
             f'<td style="vertical-align:middle"><div style="font-size:24px;font-weight:700;letter-spacing:.01em;'
             f'color:#ffffff;line-height:1.15">AI Briefing</div>'
             f'<div style="font-size:15px;color:{C["brand_ink"]};margin:3px 0 0;line-height:1.35">'
             f'{htmllib.escape(e.get("tagline") or TAGLINE)}</div>'
             f'<div style="font-size:12px;color:{C["brand_ink"]};opacity:.85;margin:4px 0 0">Curated by '
             f'{htmllib.escape(who)} · for early-stage investors</div></td></tr></table></td></tr>'
             f'<tr><td style="height:12px"></td></tr>')
    # header
    H.append(f'<tr><td {cell}>'
             f'<div style="display:inline-block;padding:6px 12px;border-radius:999px;background:{C["brand_deep"]};color:#ffffff;'
             f'font-size:11px;letter-spacing:.14em;text-transform:uppercase">Daily AI briefing</div>'
             f'<h1 style="margin:14px 0 8px;font-size:26px;line-height:1.2;color:{C["text"]}">{htmllib.escape(b["title"])}</h1>'
             + (f'<p {P}>{_inline(b["brief"])}</p>' if b["brief"] and not b.get("merged") else "")
             + (_take_html(takes["overall"]) if takes.get("overall") else "")
             + _btn(page, "Read the full briefing") + (_btn(page, "Listen to the episode", False) if has_audio else "")
             + "</td></tr>")
    stars = bool(e.get("ratings"))
    if stars:
        H.append(f'<tr><td style="height:12px"></td></tr><tr><td {cell}>'
                 f'<div style="font-size:17px;font-weight:600;color:{C["text"]};margin:0 0 2px">How is today\'s briefing?</div>'
                 f'<div style="font-size:13px;color:{C["muted"]};margin:0 0 6px">One click: 1 is poor, 5 is excellent. '
                 f'You can add a comment on the next page.</div>{stars_block(day)}</td></tr>')
    if b["top"]:
        lis = "".join(f'<li style="margin:0 0 10px;color:{C["text"]};font-size:16px;line-height:1.55">{_inline(t)}</li>' for t in b["top"])
        q = (f'<p {P}><b>{_inline(b["brief"].split(":", 1)[0])}:</b>{_inline(b["brief"].split(":", 1)[1])}</p>'
             if b.get("merged") and ":" in b["brief"] else "")
        H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>'
                 f'{_label("Today in 30 seconds" if b.get("merged") else "Top of mind")}'
                 f'<ul style="margin:0;padding-left:20px">{lis}</ul>{q}'
                 + (_take_html(takes["top"]) if takes.get("top") else "") + '</td></tr>')
    if b["must"]:
        items = []
        for n, s in enumerate(b["must"], 1):
            rows = [f'<div style="font-size:18px;font-weight:600;line-height:1.35;margin:0 0 4px">'
                    f'<a href="{htmllib.escape(page)}" style="color:{C["text"]};text-decoration:none">{n}. {htmllib.escape(s["headline"])}</a></div>',
                    f'<div style="font-size:13px;color:{C["muted"]};margin:0 0 8px">{htmllib.escape(s["who"])}'
                    + (f' · <a href="{htmllib.escape(s["url"])}" style="color:{C["link"]}">source</a>' if s["url"] else "")
                    + (f' · <span style="color:{C["accent"]}">{htmllib.escape(s["developing"])}</span>' if s["developing"] else "")
                    + "</div>"]
            if s["what"]:
                rows.append(f'<p style="margin:0 0 8px;color:{C["text"]};font-size:15px;line-height:1.55">{_inline(s["what"])}</p>')
            if s["crit"]:
                rows.append(f'<p style="margin:0 0 6px;color:{C["strong"]};font-size:14px;line-height:1.5">'
                            f'<span style="color:{C["muted"]}">Evidence check:</span> {_inline(s["crit"])}</p>')
            if s["editor"]:
                rows.append(f'<p style="margin:0;padding:8px 12px;border-left:3px solid {C["accent"]};background:{C["card"]};'
                            f'border-radius:0 12px 12px 0;color:{C["text"]};font-size:14px;line-height:1.5">'
                            f'<span style="color:{C["accent"]};font-size:11px;letter-spacing:.12em;text-transform:uppercase">'
                            f'{s["editor_label"]}</span><br>{_inline(s["editor"])}</p>')
            if s.get("early"):
                rows.append(f'<p style="margin:6px 0 0;color:{C["text"]};font-size:14px;line-height:1.5">'
                            f'<span style="color:{C["accent"]};font-size:11px;letter-spacing:.12em;text-transform:uppercase">'
                            f'For early-stage</span><br>{_inline(s["early"])}</p>')
            if s.get("deep"):
                rows.append(f'<p style="margin:0 0 6px;color:{C["text"]};font-size:15px;line-height:1.55">'
                            f'<span style="color:{C["muted"]}">In today\'s deep dive:</span> {_inline(s["deep"])}</p>')
            if s.get("other"):
                rows.append(f'<p style="margin:6px 0 0;padding:6px 12px;color:{C["muted"]};font-size:13px;line-height:1.5">'
                            f'<span style="font-size:11px;letter-spacing:.12em;text-transform:uppercase">{s["other_label"]}</span>'
                            f'<br>{_inline(s["other"])}</p>')
            tk = takes.get(item_id(s["url"])) if s.get("url") else ""
            if tk:
                rows.append(_take_html(tk))
            items.append(f'<div style="padding:14px 0;border-top:1px solid {C["border"]}">{"".join(rows)}</div>')
        H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{_label("Must read")}{"".join(items)}</td></tr>')
    if deep:
        dd_label = _label("This week's deep dive · two voices" if deep.get("flagship") else "Today's deep dive")
        dd_label += f'<div style="font-size:13px;color:{C["muted"]};margin:-2px 0 8px;font-style:italic">{DD_TAGLINE}</div>'
        H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{dd_label}'
                 f'<div style="font-size:18px;font-weight:600;line-height:1.35;margin:0 0 6px;color:{C["text"]}">'
                 f'{htmllib.escape(deep["title"])}</div>'
                 + (f'<p {P}>{_inline(deep["summary"])}</p>' if deep.get("summary") else "")
                 + f'<p style="margin:0 0 10px;color:{C["muted"]};font-size:13px">About {deep.get("minutes") or 10} minutes, '
                   f'right after the briefing in your podcast feed, or read it on the site.</p>'
                   + _btn(deep["url"] + "#listen", "▶ Listen to the deep dive") + _btn(deep["url"] + "#read", "Read it", False)
                   + f'<p style="margin:10px 0 0;font-size:13px;color:{C["muted"]}">The deep dives are also a podcast of '
                     f'their own: <a href="{base}/deepdive.xml" style="color:{C["link"]}">subscribe to the deep dives</a>.</p>'
                   + "</td></tr>")
    if b.get("reading"):
        rr = b["reading"]
        H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{_label("Recommended reading")}'
                 f'<div style="font-size:17px;font-weight:600;line-height:1.35;margin:0 0 4px">'
                 f'<a href="{htmllib.escape(rr["url"])}" style="color:{C["link"]};text-decoration:none">{htmllib.escape(rr["title"])}</a></div>'
                 f'<div style="font-size:13px;color:{C["muted"]};margin:0 0 8px">{htmllib.escape(rr["who"])}</div>'
                 + (f'<p style="margin:0;color:{C["text"]};font-size:15px;line-height:1.55"><span style="color:{C["accent"]}">'
                    f'Why it matters:</span> {_inline(rr["why"])}</p>' if rr["why"] else "") + "</td></tr>")
    if b["worth"]:
        lis = "".join(f'<li style="margin:0 0 8px;color:{C["text"]};font-size:15px;line-height:1.5">{_inline(t)}</li>' for t in b["worth"])
        H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{_label("Worth knowing")}'
                 f'<ul style="margin:0;padding-left:20px">{lis}</ul>'
                 + (_take_html(takes["worth"]) if takes.get("worth") else "") + '</td></tr>')
    if b["questions"]:
        lis = "".join(f'<li style="margin:0 0 8px;color:{C["text"]};font-size:15px;line-height:1.5">{_inline(t)}</li>' for t in b["questions"])
        H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{_label("Open questions")}'
                 f'<ul style="margin:0;padding-left:20px">{lis}</ul></td></tr>')
    # listen + share + footer
    H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{_label("Listen")}'
             f'<p {P}>Get every episode in your podcast app: add <a href="{feed}" style="color:{C["link"]}">{feed}</a> by URL.</p>'
             + _btn(page, "Open today's briefing") + "</td></tr>")
    H.append(f'<tr><td style="height:16px"></td></tr><tr><td {cell}>{_label("Share it")}'
             f'<p {P}>Know someone who would find this useful? Forward this email, or send them today\'s page.</p>'
             + _btn(page, "Today's page to share", False) + _btn(f"{base}/#email", "Subscribe a friend", False)
             + f'<p style="margin:10px 0 0;color:{C["muted"]};font-size:13px">Was this forwarded to you? '
               f'<a href="{base}/#email" style="color:{C["link"]}">Get your own copy each morning</a>.</p></td></tr>')
    addr = f'<br>{htmllib.escape(e["mailing_address"])}' if e.get("mailing_address") else ""
    H.append(f'<tr><td style="padding:18px 8px;color:{C["muted"]};font-size:12px;line-height:1.6">'
             f'Written and read by AI from public sources; every claim links to its source. Curated by '
             f'<a href="{htmllib.escape(sc["home_url"])}" style="color:{C["link"]}">{htmllib.escape(sc["name"])}</a> '
             f'({htmllib.escape(sc["role"])}). Opinions are personal{_not_org()}. You get this because you subscribed at '
             f'<a href="{base}/" style="color:{C["link"]}">{base.split("://", 1)[-1]}</a>.{addr}<br>'
             f'<a href="{{{{UNSUBSCRIBE}}}}" style="color:{C["link"]}">Unsubscribe</a> (one click)</td></tr>')
    H.insert(len(H) - 1, f'<tr><td style="padding:14px 8px 0;color:{C["strong"]};font-size:14px;line-height:1.5">'
             + (f'<b>Rate today\'s edition</b>{stars_block(day, big=False)}Or reply with anything that would make it more '
                f'useful: a wrong figure, a story we missed. Every reply is read.' if stars else
                f'<b>Tell us what you think.</b> Reply with a number from 1 to 5 for today\'s edition, and anything that '
                f'would make it more useful: a wrong figure, a story we missed. Every reply is read.') + '</td></tr>')
    html = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">'
            f'<title>{htmllib.escape(b["title"])}</title></head>'
            f'<body style="margin:0;padding:0;background:{C["bg"]}">'
            f'<div style="display:none;max-height:0;overflow:hidden">{htmllib.escape(_strip_md(b["brief"])[:140])}</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C["bg"]}"><tr><td align="center" style="padding:20px 10px">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;font-family:{FONT};color:{C["text"]}">'
            + "".join(H) + "</table></td></tr></table></body></html>")
    from .takes import LABEL
    tk_line = lambda k: [f"   {LABEL}: {defuse(takes[k])}"] if takes.get(k) else []  # noqa: E731
    text = "\n".join([f"AI Briefing · {e.get('tagline') or TAGLINE}", b["title"], "", _strip_md(b["brief"])] + (["", f"{LABEL}: {defuse(takes['overall'])}"]
                      if takes.get("overall") else []) + ["", "TOP OF MIND"] + [f"- {_strip_md(t)}" for t in b["top"]]
                     + tk_line("top")
                     + ["", "MUST READ"] + [x for n, s in enumerate(b["must"], 1)
                                            for x in [f"{n}. {s['headline']} ({s['who']})\n   {_strip_md(s['what'])}"]
                                            + (tk_line(item_id(s["url"])) if s.get("url") else [])]
                     + ([ "", f"TODAY'S DEEP DIVE: {deep['title']}", deep.get("summary", ""), deep["url"],
                          f"The deep dives as their own podcast: {base}/deepdive.xml"] if deep else [])
                     + ([ "", "RECOMMENDED READING", f"{b['reading']['title']} ({b['reading']['who']})", b["reading"]["url"],
                          f"Why it matters: {b['reading']['why']}"] if b.get("reading") else [])
                     + ["", f"Full briefing: {page}", f"Podcast feed: {feed}", "",
                        (f"Rate today's edition (1-5): {{{{RATE}}}}" if stars else
                         "Feedback? Reply with a number from 1 to 5 for today's edition, plus anything we should change. Every reply is read."),
                        f"Share it: {page} · Subscribe: {base}/#email",
                        "Written and read by AI from public sources. Unsubscribe: {{UNSUBSCRIBE}}"])
    return {"subject": subject, "html": html, "text": text}


def _strip_md(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", s or "")
    return s.replace("**", "").replace("*", "")


# ---------- sending ----------

def sent_days(root: Path) -> set:
    return {r["day"] for r in read_jsonl(root / LOG) if r.get("ok") and not r.get("test")}


def deep_dive_for(root: Path, cfg: dict, day: str) -> dict | None:
    """DAY's published deep dive, for the email: {"title", "summary", "url", "minutes"} or None."""
    try:
        from .deepdive import DIR, records
    except ImportError:
        return None
    rec = next((r for r in reversed(records(root)) if r.get("day") == day and r.get("status") == "published"), None)
    if not rec or not (root / DIR / f"{day}.mp3").is_file():
        return None
    md = (root / DIR / f"{day}.md").read_text("utf-8") if (root / DIR / f"{day}.md").exists() else ""
    summ = re.search(r"\*\n\n(.+?)\n", md)
    base = ((cfg.get("publish") or {}).get("site_url") or "https://sgwoods.github.io/ai-briefing/").rstrip("/")
    return {"title": rec.get("title", ""), "summary": summ.group(1) if summ else "", "url": f"{base}/{day}/deep-dive/",
            "minutes": int(round(rec.get("minutes") or 10)), "flagship": rec.get("format") == "flagship"}


def send_new(root: Path, cfg: dict, day: str) -> dict:
    """DAY's edition to active subscribers who confirmed after it was emailed (one send each, nobody twice).
    The log keeps counts only, never addresses."""
    sends = [r for r in read_jsonl(root / LOG) if r.get("day") == day and r.get("ok") and not r.get("test")]
    if not sends:
        raise MailError(f"{day} has not been emailed yet; use ./np email send {day}")
    since = max(dt.datetime.fromisoformat(r["at"]).astimezone() for r in sends)

    def confirmed_at(x):
        try:
            return dt.datetime.fromisoformat(str(x.get("confirmed") or "").replace("Z", "+00:00")).astimezone()
        except ValueError:
            return None
    new = [x["email"] for x in subscribers(cfg)["subscribers"]
           if x.get("status") == "active" and (confirmed_at(x) or since) > since]
    if not new:
        return {"day": day, "ok": True, "sent": 0, "note": "no one has confirmed since it was emailed"}
    bdir = root / cfg.get("paths", {}).get("briefings", "briefings")
    msg = render(day, (bdir / f"{day}.md").read_text("utf-8"), cfg, (bdir / f"{day}.mp3").is_file(),
                 deep_dive_for(root, cfg, day), day_takes(root, day))
    bad = privacy_gate(msg, cfg)
    if bad:
        raise MailError("privacy gate blocked the email: " + "; ".join(bad))
    sent, failed = 0, 0
    for addr in new:
        try:
            out = call(cfg, "send", subject=msg["subject"], html=msg["html"], text=msg["text"], to=addr, day=day)
            sent += int(out.get("sent", 0))
        except MailError:
            failed += 1
    rec = {"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "ok": failed == 0, "sent": sent,
           "failed": failed, "test": False, "catch_up": True, "subject": msg["subject"]}
    append_jsonl(root / LOG, [rec])
    return rec


def send_day(root: Path, cfg: dict, day: str, to: str = "", force: bool = False) -> dict:
    """Send DAY's briefing to every active subscriber (or only to `to`, as a test)."""
    from .episodes import hidden_days
    bdir = root / cfg.get("paths", {}).get("briefings", "briefings")
    md_file = bdir / f"{day}.md"
    if not md_file.exists():
        raise MailError(f"no briefing for {day}")
    if not to and day in hidden_days(root):
        raise MailError(f"{day} is hidden from the public site; not emailing it")
    if not to and day in sent_days(root) and not force:
        return {"ok": True, "skipped": f"{day} already emailed"}
    msg = render(day, md_file.read_text("utf-8"), cfg, (bdir / f"{day}.mp3").is_file(), deep_dive_for(root, cfg, day),
                 day_takes(root, day))
    bad = privacy_gate(msg, cfg)
    if bad:
        raise MailError("privacy gate blocked the email: " + "; ".join(bad))
    out = call(cfg, "send", subject=msg["subject"], html=msg["html"], text=msg["text"], to=to, day=day)
    rec = {"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "ok": bool(out.get("ok")),
           "sent": out.get("sent", 0), "failed": len(out.get("failed") or []), "quota_left": out.get("quota"),
           "test": bool(to), "subject": msg["subject"]}
    append_jsonl(root / LOG, [rec])
    if rec["ok"] and not to:                       # the edition is now SHIPPED: it must not break (pipeline/shipped.py)
        try:
            from . import shipped
            shipped.record(root, day)
        except Exception as e:  # noqa: BLE001 - the send already happened
            print(f"shipped record skipped: {e}"[:200])
    return rec
