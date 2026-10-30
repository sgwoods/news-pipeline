"""The day's edition and deep dive as Google Docs in Drive (Steven, 2026-10-26).

The mail script writes them into the mailer account's "Briefings" folder, which is shared with Steven, so he can
read them anywhere (and give feedback, e.g. while driving) and Claude can read them through Drive. Two moments:

- pre-release (the takes email): "<day> · AI Briefing (draft, held for your takes) · <lead>" and the deep dive;
- published: the draft is renamed "<day> · AI Briefing · <lead>" and rewritten with Steven's takes; the deep dive
  doc is rewritten (with his take on it, when there is one).

Names start with the date so the folder sorts by day. A rerun rewrites the same doc; nothing is ever deleted.
Drive is a copy for reading: a failure here never holds the edition.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path


def _lead(md: str) -> str:
    """The first Top of mind headline (what the subscriber email's subject uses), else the edition title."""
    from .textutil import legacy_top
    md = legacy_top(md)
    m = re.search(r"(?m)^-\s+\*\*(.+?)\*\*", md.split("## Top of mind", 1)[-1]) if "## Top of mind" in md else None
    if m:
        return m.group(1).strip().rstrip(".")
    first = md.splitlines()[0].lstrip("# ").strip() if md.startswith("# ") else "AI Briefing"
    return first.split("·", 1)[-1].strip()


def names(day: str, md: str) -> tuple:
    lead = _lead(md)[:110]
    return f"{day} · AI Briefing (draft, held for your takes) · {lead}", f"{day} · AI Briefing · {lead}"


def deepdive_name(day: str, title: str) -> str:
    return f"{day} · Deep dive · {title.removeprefix('Deep dive: ').strip()[:110]}"


def _takes_md(root: Path, day: str) -> str:
    try:
        notes = json.loads((root / "data" / "commentary" / f"{day}.json").read_text("utf-8")).get("notes", {})
    except (OSError, ValueError):
        return ""
    rows = [f"- **{n.get('title') or k}:** {n['text']}" for k, n in notes.items() if str(n.get("text", "")).strip()]
    return "## Steven's takes\n\n" + "\n".join(rows) + "\n" if rows else ""


def briefing_md(root: Path, cfg: dict, day: str, final: bool) -> str:
    md = (root / cfg["paths"]["briefings"] / f"{day}.md").read_text("utf-8")
    return md.rstrip() + "\n\n" + (_takes_md(root, day) if final else "")


def deepdive_md(root: Path, cfg: dict, day: str) -> tuple:
    """(title, markdown) of DAY's deep dive: show notes, then the article, then the sources; ('', '') if none."""
    from . import deepdive
    p = root / deepdive.DIR / f"{day}.md"
    if not p.exists():
        return "", ""
    notes = p.read_text("utf-8")
    title = notes.splitlines()[0].lstrip("# ").strip()
    head, _, srcs = notes.partition("## Sources")
    head = re.sub(r"(?m)^\*\*Why today\.\*\*.*\n?", "", head)     # the article has its own "Why today" section
    body = deepdive.written_md(root, day)
    return title, head.rstrip() + "\n\n" + body + ("\n\n## Sources" + srcs if srcs else "")


FLAGS = re.compile("[\U0001F1E6-\U0001F1FF]")                # flag emoji: garbled in Docs (10-26)


def _save(cfg: dict, name: str, md: str, replace: str = "") -> dict:
    from . import mailer
    md = re.sub(r"[ \t]+(?=[·\n])", " ", FLAGS.sub("", md))
    return mailer.call(cfg, "savedoc", name=name, text=md, **({"replace": replace} if replace else {}))


def save_day(root: Path, cfg: dict, day: str, final: bool, log=print) -> dict:
    """Write DAY's edition (draft or published) and its deep dive to Drive. -> {"briefing": url, "deepdive": url}."""
    if not (cfg.get("drive") or {}).get("enabled", True):
        return {}
    out = {}
    try:
        md = (root / cfg["paths"]["briefings"] / f"{day}.md").read_text("utf-8")
        draft, published = names(day, md)
        r = _save(cfg, published if final else draft, briefing_md(root, cfg, day, final), replace=draft if final else "")
        out["briefing"] = r.get("url", "") if r.get("ok") else ""
        if r.get("ok"):
            _stamp(root, day, "briefing", published if final else draft)
        title, dmd = deepdive_md(root, cfg, day)
        if dmd:
            r = _save(cfg, deepdive_name(day, title), dmd, replace=draft_name(day, title))
            out["deepdive"] = r.get("url", "") if r.get("ok") else ""
            if r.get("ok"):
                _stamp(root, day, "deepdive", deepdive_name(day, title))
        log(f"Drive: {'published' if final else 'draft'} edition" + (" and deep dive" if dmd else "") + " saved to Briefings")
    except Exception as e:  # noqa: BLE001 - a copy for reading; never holds the edition
        log(f"Drive copy skipped: {e}"[:200])
    return out


# ---------- Steven's edits in the Docs count as his takes (Steven, 2026-10-28) ----------
# He writes a first take in the morning boxes, then augments it in the car with Claude editing the shared Doc.
# The published Doc's "Steven's takes" section and the deep-dive Doc's "Steven's take" are read back; a line that
# differs from what the pipeline last wrote is a new take for that slot, and goes through the same privacy check
# as every other take (takes.collect). The pipeline keeps the time of its own last write per doc so its own text
# is never mistaken for an edit.

STAMP = "data/state/drive-docs.json"
TAKES_HEAD, DD_HEAD, NOTES_HEAD = "Steven's takes", "Steven's take", "Notes for the editor"


def _stamp_load(root: Path) -> dict:
    try:
        return json.loads((root / STAMP).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _stamp(root: Path, day: str, which: str, name: str) -> None:
    d = _stamp_load(root)
    d.setdefault(day, {})[which] = {"name": name, "saved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    p = root / STAMP
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), "utf-8")


def read_doc(cfg: dict, name: str) -> dict:
    from . import mailer
    return mailer.call(cfg, "readdoc", name=name)


def _section(text: str, head: str, stop: tuple = ("Sources",)) -> str:
    lines = text.replace("\r", "").split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.strip() == head), -1)
    if i < 0:
        return ""
    out = []
    for ln in lines[i + 1:]:
        if ln.strip() in stop or ln.strip() in (TAKES_HEAD, DD_HEAD, NOTES_HEAD):
            break
        out.append(ln)
    return "\n".join(out).strip()


def parse_notes(text: str) -> str:
    """The "Notes for the editor" section, without a closing "done"."""
    t = " ".join(_section(text, NOTES_HEAD).split())
    return re.sub(r"(?i)\s*\bdone\.?\s*$", "", t).strip()


def draft_name(day: str, title: str) -> str:
    return deepdive_name(day, title) + " (draft)"


def save_deepdive_draft(root: Path, cfg: dict, day: str, log=print) -> str:
    """Tomorrow's draft as a Doc with empty take and notes sections at the end. -> the Doc's url ('' if not saved)."""
    title, dmd = deepdive_md(root, cfg, day)
    if not dmd:
        return ""
    dmd = dmd.replace("## Sources", f"## {DD_HEAD}\n\n\n\n## {NOTES_HEAD}\n\n\n\n## Sources", 1) if "## Sources" in dmd \
        else dmd + f"\n\n## {DD_HEAD}\n\n\n\n## {NOTES_HEAD}\n\n"
    try:                                         # what the fact check couldn't settle: Steven decides in his notes
        from .audit import load_deepdive_check
        held = load_deepdive_check(root, day).get("held") or []
    except Exception:  # noqa: BLE001
        held = []
    if held:
        fc = "## Fact check: please look\n\n" + "\n".join(
            f"- {h['claim'][:240]} ({h.get('verdict', '')}: {h.get('why', '')[:160]})" for h in held[:10]) + \
            "\n\nSay in Notes for the editor what to keep, change or cut; otherwise the morning run checks it again.\n\n"
        dmd = dmd.replace(f"## {DD_HEAD}", fc + f"## {DD_HEAD}", 1)
    dmd = "*Draft for tomorrow. Read it; then write your take and any notes for the editor in the two sections near " \
          "the end. The morning run revises the draft from your notes and records it with your take.*\n\n" + dmd
    r = _save(cfg, draft_name(day, title), dmd)
    if r.get("ok"):
        _stamp(root, day, "deepdive", draft_name(day, title))
        log(f"Drive: tomorrow's deep-dive draft saved to Briefings")
        return r.get("url", "")
    return ""


def fetch_deepdive_draft(root: Path, cfg: dict, day: str, log=print) -> dict:
    """{"take", "notes"} from DAY's draft Doc (what Steven wrote in the two sections), or {}."""
    title, _ = deepdive_md(root, cfg, day)
    if not title or not (cfg.get("drive") or {}).get("enabled", True):
        return {}
    try:
        r = read_doc(cfg, draft_name(day, title))
    except Exception as e:  # noqa: BLE001
        log(f"Drive: draft doc not read ({e})"[:200])
        return {}
    if not r.get("found"):
        return {}
    text = r.get("text", "")
    return {"take": parse_dd_take(text), "notes": parse_notes(text)}


def parse_takes(text: str, slots: list) -> dict:
    """The Doc's takes section -> {slot: text}. A line is "<title>: <take>"; titles are matched against the slots,
    longest first, so a headline with a colon in it still matches."""
    sec = _section(text, TAKES_HEAD)
    if not sec:
        return {}
    titles = sorted(((s["title"], s["slot"]) for s in slots if s.get("title")), key=lambda x: -len(x[0]))
    out, cur = {}, None
    for ln in sec.split("\n"):
        ln = ln.strip().lstrip("-•* ").strip()
        if not ln:
            continue
        hit = next(((t, sl) for t, sl in titles if ln.lower().startswith(t.lower().rstrip(".") + ":")), None)
        if hit:
            cur = hit[1]
            out[cur] = ln[len(hit[0].rstrip(".")) + 1:].strip()
        elif cur:
            out[cur] = (out[cur] + " " + ln).strip()       # a continuation line joins the take above
    return {k: v for k, v in out.items() if v}


def parse_dd_take(text: str) -> str:
    return " ".join(_section(text, DD_HEAD).split())


def _changed(root: Path, day: str, which: str, modified: str) -> bool:
    st = (_stamp_load(root).get(day) or {}).get(which) or {}
    if not st.get("saved"):
        return True                                       # never written by us: anything there is Steven's
    try:
        saved = dt.datetime.fromisoformat(st["saved"].replace("Z", "+00:00"))
        mod = dt.datetime.fromisoformat(modified.replace("Z", "+00:00"))
    except ValueError:
        return True
    return mod > saved + dt.timedelta(seconds=90)


def fetch_takes(root: Path, cfg: dict, day: str, log=print) -> dict:
    """{"rows": reply-like rows for takes.collect, "deepdive": the deep-dive take or None}. Only Docs edited after
    the pipeline's own last write count."""
    from . import takes
    out = {"rows": [], "deepdive": None}
    if not (cfg.get("drive") or {}).get("enabled", True):
        return out
    md_file = root / cfg["paths"]["briefings"] / f"{day}.md"
    if md_file.exists():
        draft, published = names(day, md_file.read_text("utf-8"))
        try:                                              # before the edition ships the Doc is the draft (held for takes)
            r = read_doc(cfg, published)
            if not r.get("found"):
                r = read_doc(cfg, draft)
        except Exception as e:  # noqa: BLE001
            log(f"Drive takes: edition doc not read ({e})"[:200])
            r = {}
        if r.get("found") and _changed(root, day, "briefing", r.get("modified", "")):
            sl = takes.slots(root, day)
            got = parse_takes(r.get("text", ""), sl)
            try:                                          # only takes that differ from what is already saved
                cur = json.loads((root / "data" / "commentary" / f"{day}.json").read_text("utf-8")).get("notes", {})
            except (OSError, ValueError):
                cur = {}
            key_of = {s["slot"]: s["key"] for s in sl}
            got = {k: v for k, v in got.items()
                   if takes.tidy(v) != takes.tidy(str((cur.get(key_of.get(k, "")) or {}).get("text") or ""))}
            if got:
                out["rows"].append({"received": r.get("modified", ""), "takes": {k: takes.tidy(v) for k, v in got.items()},
                                    "done": False, "skip": False, "via": "drive"})
    title, _ = deepdive_md(root, cfg, day)
    if title:
        try:
            r = read_doc(cfg, deepdive_name(day, title))
            if not r.get("found"):
                r = read_doc(cfg, draft_name(day, title))
        except Exception as e:  # noqa: BLE001
            log(f"Drive takes: deep-dive doc not read ({e})"[:200])
            r = {}
        if r.get("found") and _changed(root, day, "deepdive", r.get("modified", "")):
            t = parse_dd_take(r.get("text", ""))
            from . import deepdive
            rec = deepdive.latest(root, day) or {}
            qid = (rec.get("pick") or {}).get("queue_id")
            have = next((str(x.get("take") or "") for x in deepdive.load_queue(root) if x.get("id") == qid), "") if qid else ""
            if t and takes.tidy(t) != takes.tidy(have):
                out["deepdive"] = t
    return out


SYNC_MINUTES = 20


def sync_due(root: Path, now: dt.datetime | None = None) -> bool:
    """Is it time to look at today's Docs again? (The runner ticks every minute; the Docs are read every 20.)"""
    now = now or dt.datetime.now()
    st = _stamp_load(root).get("_sync") or {}
    try:
        last = dt.datetime.fromisoformat(st.get("at", ""))
    except ValueError:
        return True
    return (now - last) >= dt.timedelta(minutes=SYNC_MINUTES)


def mark_sync(root: Path, changed: bool, now: dt.datetime | None = None) -> None:
    d = _stamp_load(root)
    d["_sync"] = {"at": (now or dt.datetime.now()).isoformat(timespec="seconds"), "changed": changed}
    (root / STAMP).parent.mkdir(parents=True, exist_ok=True)
    (root / STAMP).write_text(json.dumps(d, indent=1), "utf-8")


def pending_edits(root: Path, cfg: dict, day: str, log=print) -> bool:
    """Has Steven edited today's Docs since we last wrote them? (Cheap: two reads, nothing applied.)"""
    got = fetch_takes(root, cfg, day, log)
    return bool(got["rows"] or got["deepdive"])
