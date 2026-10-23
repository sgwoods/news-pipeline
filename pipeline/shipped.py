"""Shipped editions don't break (v0.1.7). Once a day's email has gone out, that day is SHIPPED:

  data/state/shipped.json   {day: {at, md (sha256 of briefings/DAY.md), dd (deep dive md sha256 or ""),
                                   pages [site paths], audio [site audio file names]}}
  data/state/corrections.jsonl   every change to a shipped edition: {day, at, note, md_before, md_after}

Rules, enforced before every production publish (guard) and after it (verify_live):
  - every shipped page (day page, deep dive) is still in the new site, unless the owner hid the day;
  - a shipped edition's text (briefing or deep dive) changes only through a correction, which is shown on the
    page ("Corrected <date>: ..."): ./np correct DAY "what changed" after a hand edit, or
    ./np rebrief DAY --correct "what changed";
  - every shipped MP3 inside the retention window (publish.audio_days) still resolves: a remaster adds a new file
    and the old one is carried over from the live site, so no URL breaks;
  - the home page and both feeds exist, and no podcast episode inside the retention window leaves the feed;
  - after the push, the newest shipped pages, both feeds and the latest MP3 must answer; if not, the previous
    site is put back (./np publish restore does the same by hand) and the owner is emailed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

FILE = "data/state/shipped.json"
CORRECTIONS = "data/state/corrections.jsonl"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def load(root: Path) -> dict:
    try:
        return json.loads((root / FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save(root: Path, d: dict) -> None:
    p = root / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", "utf-8")


def _entry(root: Path, day: str, live: Path | None) -> dict:
    live = live or root / ".publish"
    pages = [f"{day}/index.html"] + ([f"{day}/deep-dive/index.html"] if (live / day / "deep-dive" / "index.html").exists() else [])
    audio = sorted(p.name for p in (live / "audio").glob("*.mp3")
                   if p.name.startswith(day) or p.name.startswith(f"deepdive-{day}")) if (live / "audio").exists() else []
    return {"at": dt.datetime.now().isoformat(timespec="seconds"), "md": _sha(root / "briefings" / f"{day}.md"),
            "dd": _sha(root / "briefings" / "deepdives" / f"{day}.md"), "pages": pages, "audio": audio}


def record(root: Path, day: str, live: Path | None = None) -> dict:
    """Mark DAY shipped (called after its email went out). Keeps audio names already recorded."""
    d = load(root)
    e = _entry(root, day, live)
    e["audio"] = sorted(set(e["audio"]) | set((d.get(day) or {}).get("audio") or []))
    d[day] = e
    save(root, d)
    return e


def backfill(root: Path, live: Path | None = None) -> int:
    """First run: every day already emailed counts as shipped."""
    from .mailer import sent_days
    d, n = load(root), 0
    for day in sorted(sent_days(root)):
        if day not in d and (root / "briefings" / f"{day}.md").exists():
            d[day] = _entry(root, day, live)
            n += 1
    if n:
        save(root, d)
    return n


def is_shipped(root: Path, day: str) -> bool:
    return day in load(root)


def corrections(root: Path, day: str | None = None) -> list:
    p = root / CORRECTIONS
    rows = [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []
    return [r for r in rows if day is None or r.get("day") == day]


def correct(root: Path, day: str, note: str, before: str = "") -> dict:
    """Record a correction to a shipped edition (after it was rebuilt or edited by hand), and accept its new text
    (briefing and deep dive). The note is shown on the day page and the deep-dive page."""
    note = note.strip()
    if not note:
        raise ValueError("say what the correction changes")
    d = load(root)
    before = before or (d.get(day) or {}).get("md", "")
    after = _sha(root / "briefings" / f"{day}.md")
    row = {"day": day, "at": dt.datetime.now().isoformat(timespec="seconds"), "note": note[:300],
           "md_before": before, "md_after": after}
    p = root / CORRECTIONS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    if day in d:
        d[day]["md"] = after
        d[day]["dd"] = _sha(root / "briefings" / "deepdives" / f"{day}.md")
        save(root, d)
    return row


def carry_audio(root: Path, site: Path, live: Path, audio_days: int, today: dt.date | None = None) -> list:
    """Shipped MP3s inside the retention window that the new build no longer has (a remaster renamed them):
    copied over from the live site, so their URLs keep working."""
    cutoff = ((today or dt.date.today()) - dt.timedelta(days=audio_days - 1)).isoformat()
    carried = []
    for day, e in load(root).items():
        if day < cutoff:
            continue
        for name in e.get("audio") or []:
            src, dst = live / "audio" / name, site / "audio" / name
            if not dst.exists() and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                carried.append(name)
    return carried


def _episode_days(xml_path: Path) -> set:
    """The days the podcast feed has episodes for (from each item's link)."""
    if not xml_path.exists():
        return set()
    items = re.findall(r"<item>(.*?)</item>", xml_path.read_text("utf-8"), re.S)
    return {m.group(1) for it in items for m in [re.search(r"(\d{4}-\d{2}-\d{2})", it)] if m}


def guard(root: Path, site: Path, live: Path, audio_days: int, today: dt.date | None = None) -> list:
    """Problems that would break something a reader already has (empty = safe to publish)."""
    from .episodes import hidden_days
    hidden = hidden_days(root)
    cutoff = ((today or dt.date.today()) - dt.timedelta(days=audio_days - 1)).isoformat()
    bad = []
    for day, e in sorted(load(root).items()):
        if day in hidden:
            continue
        for page in e.get("pages") or []:
            if not (site / page).exists():
                bad.append(f"shipped page missing: {page}")
        now = _sha(root / "briefings" / f"{day}.md")
        if e.get("md") and now != e["md"]:
            bad.append(f"{day}: shipped edition changed without a correction (./np correct {day} \"what changed\")")
        dd_now = _sha(root / "briefings" / "deepdives" / f"{day}.md")
        if e.get("dd") and dd_now != e["dd"]:
            bad.append(f"{day}: shipped deep dive changed without a correction (./np correct {day} \"what changed\")")
        if day >= cutoff:
            for name in e.get("audio") or []:
                if not (site / "audio" / name).exists():
                    bad.append(f"shipped audio missing: audio/{name}")
    for f in ("index.html", "feed.xml", "podcast.xml"):
        if not (site / f).exists():
            bad.append(f"{f} missing")
    lost = sorted(d for d in _episode_days(live / "podcast.xml") - _episode_days(site / "podcast.xml")
                  if d >= cutoff and d not in hidden)
    if lost:                                             # episodes still inside the retention window must stay
        bad.append(f"podcast feed would drop episode(s): {', '.join(lost[:5])}")
    return bad


def live_urls(root: Path, base: str, n: int = 7) -> list:
    """What must answer after a publish: the newest shipped pages, both feeds, the newest shipped MP3."""
    base = base.rstrip("/")
    d = load(root)
    days = sorted(d)[-n:]
    urls = [f"{base}/", f"{base}/feed.xml", f"{base}/podcast.xml"]
    urls += [f"{base}/{p}" for day in days for p in d[day].get("pages") or []]
    for day in reversed(days):
        if d[day].get("audio"):
            urls.append(f"{base}/audio/{d[day]['audio'][-1]}")
            break
    return urls


def verify_live(root: Path, base: str, client=None, log=print) -> list:
    """-> URLs that don't answer 200 (empty = the readers' experience is intact)."""
    if not base:
        return []
    if client is None:
        from .netguard import client as guarded
        client = guarded(follow_redirects=True, timeout=20, headers={"Cache-Control": "no-cache"})
    bad = []
    for u in live_urls(root, base):
        try:
            r = client.head(u) if u.endswith(".mp3") else client.get(u)
            if r.status_code != 200:
                bad.append(f"{u} -> {r.status_code}")
        except Exception as e:  # noqa: BLE001
            bad.append(f"{u} -> {type(e).__name__}")
    return bad
