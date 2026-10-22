"""Steven's commentary on a briefing: storage, page injection, and the mail-out roll-up.

data/commentary/<day>.json        current notes: {"day", "notes": {key: {text, updated, run_id, title}}}
data/commentary/<day>.log.jsonl   every save, append-only (nothing you write is ever lost)

Keys: "top" (Top of mind), "also" (Also seen), "overall", or the item id of a story
(derived from the story's source link, so it survives re-renders of the same day).
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
from pathlib import Path

from pipeline.archive import append_jsonl
from pipeline.textutil import item_id

KEY_RE = re.compile(r"^(top|also|worth|brief|overall|[0-9a-f]{16})$")


def _dir(root: Path) -> Path:
    return root / "data" / "commentary"


def load(root: Path, day: str) -> dict:
    p = _dir(root) / f"{day}.json"
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    return {"day": day, "notes": {}}


def save(root: Path, day: str, key: str, text: str, run_id: str = "", title: str = "") -> dict:
    d = load(root, day)
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    d["notes"][key] = {"text": text, "updated": now, "run_id": run_id, "title": title[:200]}
    d["updated"] = now
    out = _dir(root)
    out.mkdir(parents=True, exist_ok=True)
    append_jsonl(out / f"{day}.log.jsonl", [{"key": key, "text": text, "at": now, "run_id": run_id}])
    tmp = out / f"{day}.json.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(out / f"{day}.json")
    return d["notes"][key]


def _box(key: str, label: str, note: dict, title: str) -> str:
    text = htmllib.escape((note or {}).get("text", ""))
    when = (note or {}).get("updated", "")[:16].replace("T", " ")
    return (f'<div class="note" data-key="{key}" data-title="{htmllib.escape(title, quote=True)}">'
            f'<label>{label}</label><textarea rows="2" placeholder="Your take (saved automatically)">{text}</textarea>'
            f'<span class="saved small muted">{("saved " + when) if when else ""}</span></div>')


def inject(html: str, notes: dict) -> str:
    """Wrap each section/story in <section> and add a commentary box after it."""
    chunks = re.split(r"(?=<h[23]>)", html)
    out = []
    for ch in chunks:
        m = re.match(r"<h([23])>(.*?)</h\1>", ch, re.S)
        if not m:
            out.append(ch)
            continue
        level, heading = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if level == "3":
            href = re.search(r'href="(https?://[^"]+)"', ch)
            key = item_id(htmllib.unescape(href.group(1))) if href else None
            if key:
                out.append(f'<section class="story" data-key="{key}">{ch}'
                           f'{_box(key, "Your commentary", notes.get(key), heading)}</section>')
                continue
        elif heading.lower().startswith("top of mind"):
            out.append(f'<section class="story" data-key="top">{ch}{_box("top", "Your commentary on Top of mind", notes.get("top"), heading)}</section>')
            continue
        elif heading.lower().startswith("worth knowing"):
            out.append(f'<section class="story" data-key="worth">{ch}{_box("worth", "Your commentary on Worth knowing", notes.get("worth"), heading)}</section>')
            continue
        elif heading.lower().startswith(("also seen", "in brief")):
            out.append(f'<section class="story" data-key="also">{ch}{_box("also", "Your commentary on these", notes.get("also"), heading)}</section>')
            continue
        out.append(f'<section class="story">{ch}</section>')
    out.append(_box("overall", "Your overall take for the day", notes.get("overall"), "Overall"))
    return "".join(out)


def mailout(md: str, notes: dict, day: str) -> str:
    """Markdown roll-up: Top of mind + only the stories you commented on, with your notes."""
    def note(k):
        return (notes.get(k) or {}).get("text", "").strip()

    title = md.splitlines()[0].lstrip("# ").strip() if md.startswith("# ") else f"AI Briefing — {day}"
    L = [f"# {title}", ""]
    if note("overall"):
        L += [note("overall"), ""]
    tom = md.split("## Top of mind", 1)[1].split("\n## ", 1)[0].strip() if "## Top of mind" in md else ""
    if tom:
        L += ["## Top of mind", "", tom, ""]
        if note("top"):
            L += [f"**My take:** {note('top')}", ""]
    stories = re.split(r"(?m)^### ", md)[1:]
    picked = []
    for s in stories:
        head = s.splitlines()[0]
        url = re.search(r"\((https?://[^)]+)\)", s)
        k = item_id(url.group(1)) if url else ""
        if k and note(k):
            claim = re.search(r"\*\*(?:What happened|Claim):\*\* (.+)", s)
            crit = re.search(r"\*\*(?:Critical pass|Evidence check):\*\* (.+)", s)
            body = [f"### {re.sub(r'^[0-9]+[.] ', '', head)}", ""]
            if claim:
                body.append(claim.group(1).strip())
            if crit:
                body += ["", f"*Evidence check:* {crit.group(1).strip()[:300]}"]
            body += ["", f"**My take:** {note(k)}", "", f"[Source]({url.group(1)})", ""]
            picked += body
    if picked:
        L += ["## What I'm watching", ""] + picked
    if note("worth"):
        L += ["## Also worth knowing", "", note("worth"), ""]
    if note("also"):
        L += ["## Also", "", note("also"), ""]
    return "\n".join(L).rstrip() + "\n"
