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
    """Per-section coverage: the share of each section's words found, in order, in the transcript. Each row also
    carries the span of transcript words it matched (first/last index), so a second pass can find its time window."""
    hw = _words(heard)
    sw, owner = [], []
    for i, (_, t) in enumerate(sections):
        w = _words(t)
        sw += w
        owner += [i] * len(w)
    hit = [0] * len(sections)
    span = [[None, None] for _ in sections]
    for blk in difflib.SequenceMatcher(None, sw, hw, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            i = owner[blk.a + k]
            hit[i] += 1
            j = blk.b + k
            span[i][0] = j if span[i][0] is None else min(span[i][0], j)
            span[i][1] = j if span[i][1] is None else max(span[i][1], j)
    rows = []
    for i, (n, t) in enumerate(sections):
        total = len(_words(t))
        cov = round(hit[i] / total, 2) if total else 1.0
        rows.append({"section": n, "words": total, "coverage": cov, "flag": total >= 8 and cov < LOW,
                     "heard_span": span[i]})
    total = sum(r["words"] for r in rows) or 1
    return {"overall": round(sum(hit) / total, 2), "sections": rows,
            "missing": [r["section"] for r in rows if r["flag"]]}


def _word_times(segs: list) -> list:
    """(start, end) per transcript word, in the order _words() produces them from the joined text."""
    out = []
    for s in segs:
        n = len(_words(s.get("text", "")))
        out += [(float(s.get("start", 0)), float(s.get("end", 0)))] * n
    return out


def window_for(rows: list, i: int, segs: list, pad: float = 1.5) -> tuple | None:
    """The time window where section i should be: after the last word heard from an earlier section and before the
    first word heard from a later one (2026-11-14: the deep-dive opener sat right after the sound logo and Whisper
    returned nothing for that whole 30 s window, so the check called a fine opener 'missing')."""
    wt = _word_times(segs)
    if not wt:
        return None
    start = 0.0
    for r in reversed(rows[:i]):
        if r["heard_span"][1] is not None:
            start = wt[min(r["heard_span"][1], len(wt) - 1)][1]
            break
    end = wt[-1][1]
    for r in rows[i + 1:]:
        if r["heard_span"][0] is not None:
            end = wt[min(r["heard_span"][0], len(wt) - 1)][0]
            break
    start, end = max(0.0, start - pad), end + pad
    return (start, end) if end - start >= 2.0 else None


def second_pass(mp3: Path, sections: list, res: dict, segs: list, stt, log=print, run=None) -> dict:
    """Re-transcribe each flagged section's own window on its own (cut with ffmpeg) before calling it missing. A
    section heard on the second pass is unflagged and noted; one that is still not heard keeps the flag, now with
    the window's timestamp so the owner knows where to listen."""
    import shutil
    import subprocess
    import tempfile
    run = run or subprocess.run
    if not res.get("missing") or not shutil.which("ffmpeg"):
        return res
    rows = res["sections"]
    still = []
    for i, r in enumerate(rows):
        if not r["flag"]:
            continue
        win = window_for(rows, i, segs)
        if win is None:
            still.append(r["section"])
            continue
        a, b = win
        r["window"] = f"{int(a // 60)}:{int(a % 60):02d}-{int(b // 60)}:{int(b % 60):02d}"
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "clip.wav"
            try:
                run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{a:.2f}", "-i", str(mp3), "-t", f"{b - a:.2f}",
                     "-ac", "1", "-ar", "16000", str(clip)], check=True)
                heard2 = " ".join(x["text"] for x in stt(clip))
            except Exception as e:  # noqa: BLE001
                log(f"listen: second pass failed for {r['section']}: {e}"[:160])
                still.append(r["section"])
                continue
        cov2 = compare([(r["section"], sections[i][1])], heard2)["sections"][0]["coverage"]
        r["coverage_second_pass"] = cov2
        if cov2 >= LOW:
            r["flag"] = False
            r["note"] = f"heard on a second pass of {r['window']} ({int(cov2 * 100)}%)"
            log(f"listen: {r['section']} heard on a second pass of {r['window']} ({int(cov2 * 100)}%)")
        else:
            still.append(r["section"])
    res["missing"] = still
    return res


_COMMON = {"The", "This", "That", "These", "Those", "But", "And", "For", "With", "From", "After", "Before", "When", "Where",
           "What", "Why", "How", "Here", "There", "Today", "Yesterday", "Tomorrow", "Monday", "Tuesday", "Wednesday",
           "Thursday", "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December", "Must", "Worth", "Money", "Top", "Open", "Quick",
           "Deep", "Editor", "Sources", "Source", "Read", "Briefing", "Also", "Still", "Then", "Now", "Its", "His", "Her",
           "Their", "Our", "You", "Your", "They", "One", "Two", "Three", "Four", "Five", "Six", "Not", "Yes", "Both",
           "First", "Second", "Third", "Last", "Next", "New", "Old", "Big", "Meanwhile", "Instead", "Elsewhere", "Over",
           "Under", "Inside", "Outside", "Some", "Many", "Most", "More", "Less", "Each", "Every", "Another", "Other",
           "Even", "Only", "Just", "Like", "Unlike", "Since", "While", "Until", "Because", "Although", "Though", "Whether",
           "Nothing", "Something", "Everything", "Anyone", "Someone", "Everyone", "Who", "Which", "Whose", "Than",
           "Take", "Takes", "Developing", "Recommended", "Reading", "Hits", "Questions", "Views", "Mind", "Day", "Brief"}
_NAME = re.compile(r"(?<![\w'’])([A-Z][a-zA-Z'’-]{2,}|[A-Z][A-Za-z]*[A-Z][A-Za-z]*)(?![\w])")
_ACRONYM = re.compile(r"^[A-Z0-9&-]{2,5}$")


def script_names(md: str) -> list:
    """Proper nouns and acronyms in the written briefing, in order, with the plain text around them: what a
    listener should hear by name. Sentence-initial words count only when they appear capitalized elsewhere too."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)                 # links -> their text
    text = re.sub(r"https?://\S+|[*_`#>|]", " ", text)
    cands = []
    for m in _NAME.finditer(text):
        w = m.group(1).rstrip("'’s") if m.group(1).endswith(("'s", "’s")) else m.group(1)
        if w in _COMMON or len(w) < 3 and not _ACRONYM.match(w):
            continue
        before = text[max(0, m.start() - 2):m.start()]
        initial = m.start() == 0 or before.strip() in ("", ".", "!", "?", ":", "-", "–", "—") or before.endswith("\n")
        cands.append((w, initial))
    mid = {w for w, initial in cands if not initial}
    out, seen = [], set()
    for w, initial in cands:
        if (initial and w not in mid and not _ACRONYM.match(w)) or w.lower() in seen:
            continue
        seen.add(w.lower())
        out.append(w)
    return out


def _heard_forms(word: str) -> set:
    """Ways a correctly voiced word shows up in a Whisper transcript (lowercase tokens)."""
    w = word.lower().replace("’", "'")
    forms = {w, w.replace("-", ""), w.replace("'", "")}
    if _ACRONYM.match(word):
        forms.add(" ".join(word.lower()))                       # "a m d" when said letter by letter
        forms.add("".join(c for c in word.lower() if c.isalnum()))
    return forms


def names_check(spoken: str, heard: str, table: dict | None = None) -> list:
    """Names in the voiced script that the transcript does not contain, with what was heard in their place (Steven,
    2026-11-12: "Huang" read as "H-wong", "AMD" as "a, MD"). `spoken` is what the voice read (respellings and phoneme
    markup from pronunciations.yaml included); a respelled word is reported under its real spelling with `entry`
    True, so the entry itself can be tuned. Only short substitutions count (one to three heard words): a name with
    nothing in its place was cut or skipped, not mispronounced. A Whisper mis-hearing of a well-said name looks the
    same, so these are candidates to audition (./np say), not verdicts."""
    table = table or {}
    hw = _words(heard)
    heard_blob = " " + " ".join(hw) + " "
    text = re.sub(r"\[([^\]]+)\]\(/[^)]*/\)", r"\1", spoken)             # [Hwang](/hwɑŋ/) -> Hwang
    back = {}                                                           # respelling word -> real spelling
    for real, said in table.items():
        said_plain = re.sub(r"\[([^\]]+)\]\(/[^)]*/\)", r"\1", said)
        rw, sw_ = said_plain.split(), real.split()
        if len(rw) == len(sw_):
            for a, b in zip(rw, sw_):
                if a != b:
                    back[a] = b
        elif len(sw_) == 1:
            back[said_plain] = real
    sw = _words(text)
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())  # noqa: E731
    repl = {}
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, sw, hw, autojunk=False).get_opcodes():
        if tag == "replace" and a1 - a0 <= 4 and b1 - b0 <= 6:
            for k in range(a0, a1):                            # the heard words closest in sound to this script word
                best, score = " ".join(hw[b0:b1]), -1.0
                for i in range(b0, b1):
                    for j in range(i + 1, min(b1, i + 3) + 1):
                        cand = " ".join(hw[i:j])
                        r = difflib.SequenceMatcher(None, norm(sw[k]), norm(cand)).ratio() - 0.01 * (j - i)
                        if r > score:
                            best, score = cand, r
                repl.setdefault(sw[k], best)
    out, seen = [], set()
    for w in script_names(text):
        real = back.get(w, w)
        if any(f" {f} " in heard_blob for f in _heard_forms(real) | _heard_forms(w)):
            continue
        toks = _words(w)
        heard_as = repl.get(toks[0], "") if toks else ""
        if not heard_as or len(heard_as.split()) > 3 or real.lower() in seen or w.startswith(("I'", "I’")):
            continue
        ratio = difflib.SequenceMatcher(None, norm(real), norm(heard_as)).ratio()
        split_acronym = _ACRONYM.match(real) and " " in heard_as         # "a md": the letters were not said as a unit
        if ratio >= 0.9 and not split_acronym:                 # the same sound, spelled Whisper's way (Clearlake / clear lake)
            continue
        seen.add(real.lower())
        out.append({"word": real, "said": w if w != real else "", "heard": heard_as, "close": ratio >= 0.7,
                    "entry": real in table or any(k.split()[-1] == real for k in table), "acronym": bool(_ACRONYM.match(real))})
    return out


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
    sections = script_sections(root, cfg, day)
    res = {"day": day, "url": url, "checked": dt.datetime.now().isoformat(timespec="seconds"),
           **compare(sections, heard)}
    res = second_pass(mp3, sections, res, segs, stt or transcribe, log=log)
    res["ok"] = not res["missing"] and res["overall"] >= 0.8
    try:                                         # names the listener did not hear as written (11-12)
        from .speech import load_table
        res["names"] = names_check(" ".join(t for _, t in sections), heard, load_table(root))
        if res["names"]:
            log("Listen check: names not heard as written: "
                + ", ".join(f"{x['word']}→{x['heard'] or '?'}" for x in res["names"][:8]))
    except Exception as e:  # noqa: BLE001 - a hint, never a failure
        res["names"] = []
        log(f"name check skipped: {e}")
    d = root / DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{day}.json").write_text(json.dumps({**res, "model": MODEL, "segments": segs}, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (d / f"{day}.vtt").write_text(vtt(segs), "utf-8")
    log(f"Listen check {day}: {int(res['overall'] * 100)}% of the script heard"
        + (f"; not heard: {', '.join(res['missing'])}" if res["missing"] else "; every section present"))
    return res


def transcript_for(root: Path, day: str) -> Path | None:
    p = root / DIR / f"{day}.vtt"
    return p if p.exists() else None


def recent_names(root: Path, days: int = 7) -> list:
    """Names not heard as written over the last DAYS listen checks, merged: [{word, heard, days, n, entry, acronym,
    close}] most frequent first. For the Quality page's pronunciation candidates and ./np pronounce lint."""
    out = {}
    files = sorted((root / DIR).glob("????-??-??.json"), reverse=True)[:days]
    for f in files:
        try:
            rec = json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        for x in rec.get("names") or []:
            k = x["word"].lower()
            e = out.setdefault(k, {"word": x["word"], "heard": x.get("heard", ""), "days": [], "n": 0, "entry": x.get("entry"),
                                   "acronym": x.get("acronym"), "close": x.get("close"), "said": x.get("said", "")})
            e["n"] += 1
            e["days"].append(f.stem)
            e["entry"] = e["entry"] or x.get("entry")
    return sorted(out.values(), key=lambda e: (-e["n"], e["word"]))
