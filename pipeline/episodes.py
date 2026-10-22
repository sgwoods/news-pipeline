"""Which days are published: hide an episode (and its page) from the public site and podcast feed,
or delete its MP3. The text briefing always stays in the archive (append-only).

data/episodes.json  {day: {"hidden": true, "note": "...", "at": "..."}}   committed with the archive
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

FILE = "data/episodes.json"


def load(root: Path) -> dict:
    try:
        return json.loads((root / FILE).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def hidden_days(root: Path) -> set:
    return {d for d, v in load(root).items() if d != "versions" and isinstance(v, dict) and v.get("hidden")}


def set_hidden(root: Path, day: str, hidden: bool, note: str = "") -> dict:
    st = load(root)
    st[day] = {"hidden": bool(hidden), "note": note[:300], "at": dt.datetime.now().isoformat(timespec="seconds")}
    p = root / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return st[day]


def delete_audio(root: Path, cfg: dict, day: str, icloud: bool = False) -> list:
    """Delete the day's MP3 (rebuildable with ./np audio DAY). Returns the files removed."""
    removed = []
    mp3 = root / cfg.get("paths", {}).get("briefings", "briefings") / f"{day}.mp3"
    if mp3.is_file():
        mp3.unlink()
        removed.append(str(mp3.relative_to(root)))
    from .env import staging
    if icloud and not staging():
        d = os.path.expanduser((cfg.get("audio") or {}).get("icloud_dir", ""))
        f = Path(d) / f"{day}.mp3" if d else None
        if f and f.is_file():
            f.unlink()
            removed.append(str(f))
    return removed


# ---------- versions: a rebuilt episode is a NEW episode (new GUID, new file); the old one leaves the feed ----------
# data/episodes.json also holds {"versions": {key: {"version": n, "published": n}}}; key = day or "deepdive:<day>".

def _versions(st: dict) -> dict:
    return st.setdefault("versions", {})


def version(root: Path, key: str) -> int:
    return int(((load(root).get("versions") or {}).get(key) or {}).get("version", 1))


def audio_file(root: Path, key: str) -> str:
    """File name under the site's audio/: '2026-10-13.mp3', '2026-10-13-v2.mp3', 'deepdive-2026-10-13.mp3'."""
    v = version(root, key)
    stem = key.replace("deepdive:", "deepdive-")
    return f"{stem}.mp3" if v == 1 else f"{stem}-v{v}.mp3"


def guid(root: Path, key: str) -> str:
    v = version(root, key)
    base = "ai-briefing-" + key.replace("deepdive:", "deepdive-")
    return base if v == 1 else f"{base}-v{v}"


def mark_published(root: Path, keys: list) -> None:
    st = load(root)
    vs = _versions(st)
    for k in keys:
        cur = vs.setdefault(k, {"version": 1})
        cur["published"] = cur.get("version", 1)
    p = root / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1) + "\n", "utf-8")


def rebuilt(root: Path, key: str) -> int:
    """Call when an episode's MP3 is (re)made. If the current version was already published, the new audio
    becomes the next version, so podcast apps see a new episode and the old one drops out. -> version."""
    st = load(root)
    vs = _versions(st)
    cur = vs.setdefault(key, {"version": 1})
    if cur.get("published") == cur.get("version", 1):
        cur["version"] = cur.get("version", 1) + 1
        cur["rebuilt_at"] = dt.datetime.now().isoformat(timespec="seconds")
        p = root / FILE
        p.write_text(json.dumps(st, indent=1) + "\n", "utf-8")
    return cur["version"]
