"""Listen to what was published (Steven, 2026-10-27): the as-published transcript of the day's podcast episode.

After the morning publish, the pipeline reads the public podcast feed (the same podcast.xml listeners get), downloads
the day's episode, transcribes it on this Mac with Whisper (free, local; mlx-whisper on Apple silicon) and compares
it with the script it was voiced from. A section that is missing or garbled in the audio (10-27: "the audio today
has no introduction") shows as low coverage, and the owner gets one action-needed email.

The transcript is kept (data/transcripts/<day>.json) and written as WebVTT next to the episode, so the next publish
adds it to the feed (podcast:transcript) and to the day's page. Nothing here changes the published audio.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from pathlib import Path

DIR = "data/transcripts"
MODEL = "mlx-community/whisper-large-v3-turbo"
LOW = 0.6                    # a section with less than this share of its words heard is flagged


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", (text or "").lower().replace("’", "'"))


def script_sections(root: Path, cfg: dict, day: str) -> list:
    """[(section, text)] in the order voiced: the briefing (with takes, if any), then the deep dive."""
    from .takes import read_spoken
    bdir = root / cfg["paths"]["briefings"]
    out = []
    for p in (bdir / f"{day}.spoken-takes.txt", bdir / f"{day}.spoken.txt"):
        if p.exists():
            out += read_spoken(p)
            break
    d = bdir / "deepdives" / f"{day}.spoken.txt"
    if d.exists():
        out += [(f"Deep dive · {n}", t) for n, t in read_spoken(d)]
    return out


def compare(sections: list, heard: str) -> dict:
    """Per-section coverage: the share of each section's words found, in order, in the transcript."""
    hw = _words(heard)
    sw, owner = [], []
    for i, (_, t) in enumerate(sections):
        w = _words(t)
        sw += w
        owner += [i] * len(w)
    hit = [0] * len(sections)
    for blk in difflib.SequenceMatcher(None, sw, hw, autojunk=False).get_matching_blocks():
        for k in range(blk.a, blk.a + blk.size):
            hit[owner[k]] += 1
    rows = []
    for i, (n, t) in enumerate(sections):
        total = len(_words(t))
        cov = round(hit[i] / total, 2) if total else 1.0
        rows.append({"section": n, "words": total, "coverage": cov, "flag": total >= 8 and cov < LOW})
    total = sum(r["words"] for r in rows) or 1
    return {"overall": round(sum(hit) / total, 2), "sections": rows,
            "missing": [r["section"] for r in rows if r["flag"]]}


def episode_url(feed_xml: str, day: str) -> str:
    """The day's main episode in the published feed: its enclosure URL ('' if none)."""
    for item in re.findall(r"<item>(.*?)</item>", feed_xml, re.S):
        if f"ai-briefing-{day}" in item and "deepdive" not in re.search(r"<guid[^>]*>(.*?)</guid>", item).group(1):
            m = re.search(r'<enclosure url="([^"]+)"', item)
            if m:
                return m.group(1)
    return ""


def transcribe(path: Path) -> list:
    import mlx_whisper                                   # pip install mlx-whisper (Apple silicon)
    r = mlx_whisper.transcribe(str(path), path_or_hf_repo=MODEL, language="en", condition_on_previous_text=False)
    return [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()} for s in r["segments"]]


def vtt(segs: list) -> str:
    def ts(x):
        h, rem = divmod(x, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    return "WEBVTT\n\n" + "\n\n".join(f"{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}" for s in segs) + "\n"


def check(root: Path, cfg: dict, day: str, log=print, fetch=None, stt=None) -> dict:
    """Download DAY's published episode from the public feed, transcribe it, compare it with the script, save it."""
    import httpx
    base = ((cfg.get("publish") or {}).get("site_url") or "").rstrip("/")
    if not base:
        return {"day": day, "ok": False, "error": "publish.site_url is not set"}
    get = fetch or (lambda url: httpx.get(url, timeout=120, follow_redirects=True))
    feed = get(f"{base}/podcast.xml?check={dt.datetime.now():%H%M%S}")
    url = episode_url(feed.text, day)
    if not url:
        return {"day": day, "ok": False, "error": "no episode for the day in the published feed"}
    cache = Path.home() / ".cache" / "np-listen"
    cache.mkdir(parents=True, exist_ok=True)
    mp3 = cache / url.rsplit("/", 1)[-1]
    mp3.write_bytes(get(url).content)
    segs = (stt or transcribe)(mp3)
    heard = " ".join(s["text"] for s in segs)
    res = {"day": day, "url": url, "checked": dt.datetime.now().isoformat(timespec="seconds"),
           **compare(script_sections(root, cfg, day), heard)}
    res["ok"] = not res["missing"] and res["overall"] >= 0.8
    d = root / DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{day}.json").write_text(json.dumps({**res, "model": MODEL, "segments": segs}, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (d / f"{day}.vtt").write_text(vtt(segs), "utf-8")
    log(f"Listen check {day}: {int(res['overall'] * 100)}% of the script heard"
        + (f"; missing or garbled: {', '.join(res['missing'])}" if res["missing"] else "; every section present"))
    return res


def transcript_for(root: Path, day: str) -> Path | None:
    p = root / DIR / f"{day}.vtt"
    return p if p.exists() else None
