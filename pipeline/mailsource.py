"""Newsletters as a source: read a Gmail label over IMAP and archive each email like any other item.

Setup (docs/NEWSLETTERS.md): subscribe with you+briefing@example.com, a Gmail filter applies the label
`AI-Briefing/Sources` and skips the inbox, an app password goes in .env as GMAIL_APP_PASSWORD.
newsletters.yaml maps senders to a name, tier and Steven's bias note.

Read-only: the mailbox is opened read-only, nothing is moved or marked. Every message's text is data.
"""
from __future__ import annotations

import datetime as dt
import email
import email.utils
import imaplib
import json
import os
import re
from email.header import decode_header, make_header
from pathlib import Path

from .textutil import UTC, clean_url, html_to_text, iso, item_id

SEEN = "data/state/email-seen.json"
CONFIRM_RE = re.compile(r"confirm (your )?(\S+ ){0,3}(subscription|email|sign.?up)|verify your (email|address)|activate your"
                        r"|^\W*welcome(\b(?! week)|!)|thanks? (you )?for (subscribing|joining)|login code|verification code"
                        r"|one.time code|you'?re on the list|you are on the list", re.I)
# Only these need Steven to click something; "Welcome to ..." / "Thanks for subscribing" mean it's already active.
ACTION_RE = re.compile(r"confirm (your )?(\S+ ){0,3}(subscription|email|sign.?up)|verify your (email|address)|activate your"
                       r"|login code|verification code|one.time code|finali[sz]e your", re.I)
VIEW_RE = re.compile(r'href="(https?://[^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*(?:view (?:this |it )?(?:in|on)[^<]{0,30}browser'
                     r'|read online|view online|open in browser|read in browser)', re.I)


PERMALINK_RE = re.compile(r"(?:View this (?:post|email|issue) (?:on the web|online|in (?:your|a) browser) at|Read (?:it )?online:?|"
                          r"View in browser:?)\s*\(?(https?://[^\s)>\]]+)", re.I)


class MailError(RuntimeError):
    pass


def mcfg(cfg: dict) -> dict:
    from .owner import get as owner
    o = owner()
    return {"enabled": False, "account": o["account"], "label": "AI-Briefing/Sources", "lookback_days": 3,
            "day_labels": True, "day_label_prefix": "AI-Briefing/Briefing", "cited_label": "AI-Briefing/Cited",
            "max_chars": 20000, "host": "imap.gmail.com",
            "forwarders": list(o["forwarders"]), **(cfg.get("email_sources") or {})}


def password() -> str:
    from .vault import get
    return get("GMAIL_APP_PASSWORD").replace(" ", "")


def load_newsletters(root: Path) -> list:
    import yaml
    p = root / "newsletters.yaml"
    rows = (yaml.safe_load(p.read_text("utf-8")) if p.exists() else None) or []
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        out.append({"name": str(r["name"]), "from": [str(x).lower() for x in (r.get("from") or [])],
                    "web": str(r.get("web") or ""), "tier": str(r.get("tier") or "follow"),
                    "scrutiny": bool(r.get("scrutiny")), "flags": [str(x) for x in (r.get("flags") or [])],
                    "bias": " ".join(str(r.get("bias") or "").split()), "note": str(r.get("note") or ""),
                    "subject": str(r.get("subject") or "")})
    return out


def match_sender(addr: str, newsletters: list, subject: str = ""):
    """The entry for this sender; when several entries share a sender (TLDR's editions), the optional
    `subject` regex picks one. A sender listed only with subject patterns that all miss -> "skip"."""
    a = (addr or "").lower()
    dom = a.split("@")[-1]
    hit = []
    for n in newsletters:
        for f in n["from"]:
            if f == a or (("@" not in f) and (dom == f or dom.endswith("." + f))):
                hit.append(n)
                break
    if not hit:
        return None
    for n in hit:
        if n.get("subject") and re.search(n["subject"], subject or "", re.I):
            return n
    for n in hit:
        if not n.get("subject"):
            return n
    return "skip"


# ---------- IMAP ----------

def _hdr(msg, name: str) -> str:
    try:
        return str(make_header(decode_header(msg.get(name, "") or "")))
    except Exception:  # noqa: BLE001
        return str(msg.get(name, "") or "")


def _body(msg) -> tuple:
    """(html, text) of the best parts."""
    html, text = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        ct = p.get_content_type()
        if ct not in ("text/html", "text/plain") or p.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = p.get_payload(decode=True) or b""
            s = payload.decode(p.get_content_charset() or "utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if ct == "text/html" and len(s) > len(html):
            html = s
        elif ct == "text/plain" and len(s) > len(text):
            text = s
    return html, text


def _internal_domain(dom: str) -> bool:
    """Mail from the owner's organization (owner.yaml org_domains) is internal: never quoted in public."""
    from .owner import get as owner
    return any(dom == d or dom.endswith("." + d) for d in (x.lower() for x in owner()["org_domains"]))


def _internal_link(url: str) -> bool:
    from .owner import get as owner
    o = owner()
    host = re.sub(r"^https?://([^/?#]+).*$", r"\1", url.lower())
    return _internal_domain(host) or bool(o["org"] and o["org"].lower() in url.lower())


# forwarded material marked as not for redistribution stays links-only, whoever sent it
RESTRICTED_RE = re.compile(r"(?i)not for (?:re)?distribution|for internal use only|strictly confidential|"
                           r"do not (?:forward|distribute|share)|privileged (?:and|&) confidential|confidential information of")
_FOOTER_RE = re.compile(r"(?is)\n\s*(?:this (?:e-?mail|message|communication)[^\n]{0,80}(?:confidential|intended)|"
                        r"disclaimer|to unsubscribe|unsubscribe from|if you (?:no longer|wish to stop))")


def _cut_footer(body: str) -> str:
    """Drop the legal footer / unsubscribe tail of a forwarded email (it is not content)."""
    m = _FOOTER_RE.search(body or "")
    return (body[: m.start()] if m and m.start() > 400 else body).strip()


def _to_share_address(msg) -> bool:
    """Addressed to one of the owner's shareable routes (owner.yaml share_addresses, e.g. stevenwoods.ai+briefing@):
    what arrives there from the owner's own addresses is cleared for public use, internal origin included."""
    from .owner import get as owner
    targets = {a.lower() for a in owner().get("share_addresses") or []}
    if not targets:
        return False
    for h in ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To"):
        for v in msg.get_all(h) or []:
            if targets & {a.lower() for _, a in email.utils.getaddresses([str(v)])}:
                return True
    return False




def parse_message(raw: bytes, newsletters: list, cfg_m: dict, run_id: str, now: dt.datetime) -> dict | None:
    msg = email.message_from_bytes(raw)
    from_name, from_addr = email.utils.parseaddr(_hdr(msg, "From"))
    subject = _hdr(msg, "Subject").strip()
    n = match_sender(from_addr, newsletters, subject)
    if n == "skip":                                   # a listed sender's other edition (e.g. TLDR Web Dev)
        return None
    mid = (msg.get("Message-ID") or "").strip()
    try:
        pub = email.utils.parsedate_to_datetime(msg.get("Date", ""))
        pub = pub.astimezone(UTC) if pub.tzinfo else pub.replace(tzinfo=UTC)
    except Exception:  # noqa: BLE001
        pub = now
    html, text = _body(msg)
    body = html_to_text(html) if html else text
    from .links import scrub_inbound
    body = scrub_inbound(body, {"email_sources": cfg_m})
    body = re.sub(r"\n{3,}", "\n\n", body or "").strip()[: cfg_m["max_chars"]]
    m = VIEW_RE.search(html or "")
    url = clean_url(m.group(1)) if m else ""
    if not url:                      # Substack and others put the permalink in the plain-text part
        pm = PERMALINK_RE.search(text or "") or PERMALINK_RE.search(html_to_text(html) if html else "")
        url = clean_url(pm.group(1)) if pm else ""
    web = (n or {}).get("web") or ""
    key = mid.strip("<>") or item_id(subject + pub.isoformat())
    if not url:
        # a stable, non-fetchable address for the archive; the public link is the newsletter's home page
        # plus a unique fragment, so two issues never look like the same page downstream
        url = f"email:{key}"
    from .links import is_tracker
    public = url if url.startswith("http") and not is_tracker(url) else (f"{web.rstrip('/')}/#issue-{item_id(key)[:8]}" if web else "")
    name = n["name"] if n else f"Unlisted: {from_name or from_addr}"
    by_owner = from_addr.lower() in [f.lower() for f in cfg_m.get("forwarders", [])]
    forwarded = by_owner and re.match(r"^\s*(fwd?|fw)\s*:", subject, re.I)
    shared = by_owner and _to_share_address(msg)     # sent to the shareable route: Steven says it can be used publicly
    if by_owner and shared and not forwarded:
        # Steven's own note or material sent straight to the shareable address: a source in its own right.
        name, n = "Shared by the editor", {"tier": "follow closely", "flags": ["SHARED"], "scrutiny": False,
                                          "bias": "The editor sent this to the briefing to be used publicly: weigh it like "
                                                  "any source and credit the original source it points to."}
        body = _cut_footer(body)
    if forwarded:
        # Steven forwarded something to the briefing address: a strong "read this" signal. The original
        # sender is in the body's forwarded header when the mail client kept one.
        subject = re.sub(r"^\s*(fwd?|fw)\s*:\s*", "", subject, flags=re.I)
        body0 = body
        om = re.search(r"From:\s*(.{1,120}?)\s*(?:<([^>]+)>)?\s*\n", body)
        orig = (om.group(1).strip(" '\"*") if om else "") or "unknown sender"
        name, n = "Forwarded by Steven", {"tier": "follow closely", "flags": ["FORWARDED"], "scrutiny": False,
                                          "bias": f"Steven forwarded this himself (originally from {orig}): he wants it read "
                                                  f"and weighed, not taken as true. Cite the original source, never the forward."}
        body = re.sub(r"^.*?(?:-{5,}\s*Forwarded message\s*-{5,}|_{10,}|-{3,}\s*Original Message\s*-{3,})\s*", "",
                      body, count=1, flags=re.S)                  # Steven's own note above the forward is dropped
        body = re.sub(r"^(?:(?:From|Sent|Date|Subject|To|Cc):[^\n]*\n)+\s*", "", body.lstrip(), count=1)
        orig_addr = (om.group(2) or "").strip().lower() if om else ""
        if not orig_addr:                                # Outlook: "From: Name [mailto:addr]"
            mm = re.search(r"From:[^\n]*?\[mailto:([^\]\s]+)\]", body0)
            orig_addr = mm.group(1).lower() if mm else ""
            orig = re.sub(r"\s*\[mailto:[^\]]*\]", "", orig).strip(" '\"*")
        known = bool(orig_addr) and match_sender(orig_addr, newsletters, subject) not in (None, "skip")
        orig_dom = orig_addr.split("@", 1)[1] if "@" in orig_addr else ""
        internal = _internal_domain(orig_dom)
        restricted = bool(RESTRICTED_RE.search(body))
        if shared and internal and not restricted and orig_dom:
            # Internal material Steven sent to the shareable address (stevenwoods.ai+briefing@): he has cleared it
            # for public use. Credited to the firm, never to the colleague who wrote it; footers are cut.
            body = _cut_footer(body)
            from .owner import get as owner
            n = {**n, "flags": [*n["flags"], "SHARED"], "bias": n["bias"] + " Shared for public use by the editor; "
                 "credit the firm, not individuals, and check its claims like any other source."}
            name = f"{owner()['org'] or 'The editor'} (shared)"
            known = True
        if not known and not internal and not restricted and orig_dom:
            # Steven forwarded outside material to the briefing address (a bank's market update, a report): he is
            # saying it is shareable. Keep the body as a source, credited to the original sender's organisation;
            # signatures and legal footers are cut; it is still data, never instructions.
            org = (orig or orig_dom).split("|")[0].strip()
            body = _cut_footer(body)
            n = {**n, "bias": n["bias"] + " Forwarded outside material (not a listed newsletter): treat it as that "
                 "organisation's own view or research, credit it to them, and check its claims like any other source."}
            name = f"{org} (forwarded)"
            known = True
        if not known:
            # Not a listed newsletter: could be an internal or personal email. Only its public links travel;
            # the body is never archived, sent to a model or published.
            from .links import is_tracker, personal
            from .slacksource import private_link
            hrefs = re.findall(r'href="(https?://[^"]+)"', html or "") + re.findall(r"https?://[^\s<>()\]]+", text or "")
            keep = []
            for h in hrefs:
                h = clean_url(h.rstrip(".,;"))
                if h not in keep and not personal(h, {"email_sources": cfg_m}) and not is_tracker(h) and not private_link(h) \
                        and not re.search(r"(?i)unsubscribe|mailto:|google\.com/maps", h) and not _internal_link(h):
                    keep.append(h)
            body = ("Steven forwarded an email that is not from a listed newsletter; only its public links are kept:\n"
                    + "\n".join(keep[:15]))
            n = {**n, "bias": n["bias"] + " Only the links were kept: treat each linked page as the source."}
    return {"id": item_id(url), "url": url, "public_url": public,
            "title": subject or "(no subject)", "author": from_name or from_addr, "published": iso(pub),
            "text": body, "text_chars": len(body), "person": name, "tier": (n or {}).get("tier", "unlisted"),
            "flags": (n or {}).get("flags", []), "scrutiny": bool((n or {}).get("scrutiny")),
            "source_kind": "email", "source_url": f"gmail:{cfg_m['label']}", "source_label": "",
            "source_note": (n or {}).get("bias", ""), "from_addr": from_addr, "message_id": mid,
            "fetched_at": iso(now), "run_id": run_id, "unlisted": n is None, "forwarded": bool(forwarded)}


def _seen(root: Path) -> dict:
    try:
        return json.loads((root / SEEN).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_seen(root: Path, seen: dict) -> None:
    p = root / SEEN
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = dict(sorted(seen.items(), key=lambda kv: kv[1])[-5000:])
    p.write_text(json.dumps(keep, indent=0) + "\n", "utf-8")


def connect(cfg: dict, purpose: str = "newsletters"):
    """A GUARDED mailbox connection (pipeline/mailguard.py): only the briefing labels, read-only except adding
    AI-Briefing/ labels. The raw IMAP object never leaves this function."""
    from .mailguard import GuardedIMAP
    m = mcfg(cfg)
    pw = password()
    if not pw:
        raise MailError("GMAIL_APP_PASSWORD is not set (Keychain or .env; see docs/NEWSLETTERS.md)")
    try:
        box = imaplib.IMAP4_SSL(m["host"])
        box.login(m["account"], pw)
    except Exception as e:  # noqa: BLE001
        raise MailError(f"Gmail IMAP login failed for {m['account']}: {type(e).__name__}"[:300]) from e
    finally:
        pw = None
    return GuardedIMAP(box, cfg, purpose)


def fetch(root: Path, cfg: dict, run_id: str, log, lookback_days: int | None = None) -> dict:
    """New emails under the label → items (same shape as fetch.py's) + per-newsletter stats."""
    m = mcfg(cfg)
    newsletters = load_newsletters(root)
    now = dt.datetime.now(UTC)
    since = now - dt.timedelta(days=lookback_days or m["lookback_days"])
    seen = _seen(root)
    box = connect(cfg)
    items, stats = [], {n["name"]: {"new": 0, "latest": ""} for n in newsletters}
    stats["Forwarded by Steven"] = {"new": 0, "latest": ""}
    unlisted, confirms = {}, {}
    arrived_any = set()
    try:
        typ, _ = box.select(m["label"], readonly=True)
        if typ != "OK":
            raise MailError(f"Gmail label {m['label']!r} not found: create it and the filter (docs/NEWSLETTERS.md)")
        typ, data = box.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        uids = (data[0].split() if typ == "OK" and data and data[0] else [])
        acct = m["account"].lower()
        fresh = [u for u in uids if f"{acct}:{u.decode()}" not in seen]
        log.info("  gmail %s: %d message(s) since %s, %d not seen", m["label"], len(uids), since.date(), len(fresh))
        for u in fresh[-200:]:
            typ, parts = box.fetch(u, "(RFC822)")
            if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            it = parse_message(parts[0][1], newsletters, m, run_id, now)
            seen[f"{acct}:{u.decode()}"] = iso(now)
            if not it:
                continue
            if CONFIRM_RE.search(it["title"]):
                # a sign-up email under the label: never an item. Only a real "confirm" needs Steven's click;
                # a welcome means the subscription is already active.
                if ACTION_RE.search(it["title"]):
                    confirms[it["from_addr"]] = {"subject": it["title"], "date": it["published"][:10]}
                continue
            arrived_any.add(it["from_addr"])
            if it["unlisted"]:
                unlisted[it["from_addr"]] = {"name": it["author"], "subject": it["title"], "date": it["published"][:10]}
                continue                    # remembered for the Sources page; Steven adds it to newsletters.yaml
            items.append(it)
            st = stats.setdefault(it["person"], {"new": 0, "latest": ""})
            st["new"] += 1
            st["latest"] = max(st["latest"], it["published"][:10])
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    _save_seen(root, seen)
    if unlisted:
        p = root / "data" / "state" / "email-unlisted.json"
        old = {}
        try:
            old = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        old.update(unlisted)
        p.write_text(json.dumps(old, indent=1, ensure_ascii=False) + "\n", "utf-8")
    p = root / "data" / "state" / "email-confirm.json"
    try:
        old = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        old = {}
    if confirms or old:
        old.update(confirms)
        cutoff = (now - dt.timedelta(days=14)).strftime("%Y-%m-%d")
        arrived = arrived_any | {it["from_addr"] for it in items}   # a real issue from that sender: the click happened
        old = {a: u for a, u in old.items() if a not in arrived and (u.get("date") or "") >= cutoff
               and ACTION_RE.search(u.get("subject", ""))}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(old, indent=1, ensure_ascii=False) + "\n", "utf-8")
    if confirms:
        log.warning("  %d subscription(s) need a confirm click (under the label): %s",
                    len(confirms), ", ".join(confirms))
    per = [{"person": n, "kind": "email", "url": f"gmail:{m['label']}", "status": "ok", **s} for n, s in stats.items()]
    return {"items": items, "sources": per, "unlisted": unlisted, "confirms": confirms}


def _day_emails(root: Path, cfg: dict, day: str) -> tuple:
    """(assessed, cited): message-ids of the source emails assessed for DAY's briefing, and those it cited."""
    def rows(p):
        out = []
        if p.exists():
            for ln in p.read_text("utf-8").splitlines():
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
        return out
    paths = cfg.get("paths", {})
    brief = [b for b in rows(root / paths.get("briefings_log", "data/briefings.jsonl")) if b.get("day") == day]
    last = brief[-1] if brief else {}
    considered, cited_ids = set(last.get("considered_ids", [])), set(last.get("item_ids", []))
    index = {r["id"]: r.get("raw", "") for r in rows(root / paths.get("index", "data/index.jsonl"))}
    files = {f"{paths.get('raw', 'data/raw')}/{day}/items.jsonl"} | {index[i] for i in considered | cited_ids if index.get(i)}
    assessed, cited = set(), set()
    for f in files:
        for it in rows(root / f):
            if it.get("source_kind") != "email" or not it.get("message_id"):
                continue
            if f.endswith(f"/{day}/items.jsonl") or it["id"] in considered or it["id"] in cited_ids:
                assessed.add(it["message_id"])
            if it["id"] in cited_ids:
                cited.add(it["message_id"])
    return assessed, cited


def label_day(root: Path, cfg: dict, day: str, log=print) -> dict:
    """Gmail labels on the source emails behind DAY's briefing: <prefix>/<DAY> on every email assessed for it,
    and <cited label> on those it cited. Labels only; nothing is moved, read-marked or deleted."""
    from .release import require
    require(root, cfg, "Gmail label writes")
    m = mcfg(cfg)
    day_label = f"{m['day_label_prefix'].rstrip('/')}/{day}"
    assessed, cited = _day_emails(root, cfg, day)
    if not assessed:
        log(f"Gmail labels: no source emails were assessed for {day}")
        return {"assessed": 0, "labelled": 0, "cited": 0}
    box = connect(cfg, "day-labels")
    done = cited_n = missing = 0
    try:
        typ, _ = box.select(m["label"], readonly=False)
        if typ != "OK":
            raise MailError(f"Gmail label {m['label']!r} not found")
        for mid in sorted(assessed):
            q = mid.strip().strip("<>")
            if not re.fullmatch(r"[\x21-\x7e]{1,250}", q) or '"' in q or "\\" in q:   # Message-ID is attacker-controlled
                missing += 1
                continue
            typ, data = box.uid("SEARCH", None, "X-GM-RAW", f'"rfc822msgid:{q}"')
            uids = data[0].split() if typ == "OK" and data and data[0] else []
            if not uids:
                missing += 1
                continue
            labels = [day_label] + ([m["cited_label"]] if mid in cited else [])
            for u in uids:
                box.uid("STORE", u, "+X-GM-LABELS", "(" + " ".join(f'"{x}"' for x in labels) + ")")
            done += 1
            cited_n += mid in cited
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
    log(f"Gmail labels: {done} source email(s) labelled {day_label}, {cited_n} also {m['cited_label']}"
        + (f"; {missing} not found under {m['label']}" if missing else ""))
    return {"assessed": len(assessed), "labelled": done, "cited": cited_n, "missing": missing}


def status(root: Path, cfg: dict) -> dict:
    """For the Sources page / ./np newsletters: each newsletter with how many items are archived and the newest."""
    from .archive import read_jsonl
    idx = read_jsonl(root / cfg.get("paths", {}).get("index", "data/index.jsonl"))
    by = {}
    for r in idx:
        if r.get("source_kind") == "email":
            b = by.setdefault(r.get("person"), {"count": 0, "latest": ""})
            b["count"] += 1
            b["latest"] = max(b["latest"], (r.get("published") or "")[:10])
    rows = []
    for n in load_newsletters(root):
        b = by.get(n["name"], {"count": 0, "latest": ""})
        rows.append({**n, **b})
    def _j(name):
        try:
            return json.loads((root / "data" / "state" / name).read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {"newsletters": rows, "unlisted": _j("email-unlisted.json"), "confirms": _j("email-confirm.json"),
            "config": mcfg(cfg), "password_set": bool(password())}
