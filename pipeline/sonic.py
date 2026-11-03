"""Audio branding (Steven, 2026-11-03): a short sound logo at the open and close, a soft sting between stories and
before the deep dive. Everything is synthesised here from sine partials (no samples, no licences), deterministic,
so the same style always sounds the same. Three styles to choose from on the dashboard (/audio-brand); the choice
is kept in data/state/audio-brand.json ("off" until Steven picks one).

    sounds(root, style)  -> {"logo": wav, "sting": wav, "close": wav} in data/sonic/<style>/ (made once, cached)
    chosen(root)         -> "A" | "B" | "C" | ""     (the dashboard choice; "" = no branding)
    placement(parts)     -> per part: the sound to play before it ("logo", "sting" or None), and whether to close
"""
from __future__ import annotations

import json
import math
from pathlib import Path

RATE = 24000
DIR = "data/sonic"
STATE = "data/state/audio-brand.json"
STYLES = {
    "A": "Warm: a soft chord that opens into a rising three-note bell motif",
    "B": "Bright: a quick marimba-like four-note figure",
    "C": "Minimal: a low pulse and a single clear bell",
}
NOTE = {"C4": 261.63, "E4": 329.63, "G4": 392.0, "A4": 440.0, "C5": 523.25, "D5": 587.33, "E5": 659.25,
        "G5": 783.99, "A5": 880.0, "C6": 1046.5, "G3": 196.0, "C3": 130.81}


def _np():
    import numpy as np
    return np


def _env(n, attack, decay_tau, rate=RATE):
    np = _np()
    t = np.arange(n) / rate
    a = np.minimum(1.0, t / max(attack, 1e-4))
    return a * np.exp(-t / decay_tau)


def _tone(freq, dur, kind="bell", amp=0.5, rate=RATE):
    np = _np()
    n = int(dur * rate)
    t = np.arange(n) / rate
    if kind == "bell":          # sine + soft inharmonic partials, long decay
        w = np.sin(2 * math.pi * freq * t) + 0.35 * np.sin(2 * math.pi * freq * 2.76 * t) * np.exp(-t / 0.25) \
            + 0.15 * np.sin(2 * math.pi * freq * 5.4 * t) * np.exp(-t / 0.08)
        e = _env(n, 0.004, dur / 3.0)
    elif kind == "marimba":     # fundamental + 4th partial, quick decay
        w = np.sin(2 * math.pi * freq * t) + 0.25 * np.sin(2 * math.pi * freq * 4.0 * t) * np.exp(-t / 0.05)
        e = _env(n, 0.002, 0.18)
    elif kind == "pad":         # detuned sines, slow swell and release
        w = sum(np.sin(2 * math.pi * freq * d * t) for d in (0.997, 1.0, 1.003)) / 3
        e = np.minimum(1.0, t / (dur * 0.35)) * np.minimum(1.0, (dur - t) / (dur * 0.4)).clip(0, 1)
    else:                       # "pulse": low soft thump
        w = np.sin(2 * math.pi * freq * t) * (1 + 0.3 * np.sin(2 * math.pi * 2 * t))
        e = _env(n, 0.01, 0.35)
    return amp * w * e


def _mix(total, events, rate=RATE):
    """events: [(start_seconds, samples)]."""
    np = _np()
    out = np.zeros(int(total * rate), dtype="float64")
    for start, s in events:
        i = int(start * rate)
        j = min(len(out), i + len(s))
        out[i:j] += s[: j - i]
    peak = np.max(np.abs(out)) or 1.0
    out = out / peak * 0.7                                       # headroom; the episode is loudness-normalised later
    fade = int(0.05 * rate)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


def design(style: str) -> dict:
    """The three sounds of a style as sample arrays."""
    if style == "A":
        logo = _mix(2.8, [(0.0, _tone(NOTE["C4"], 2.6, "pad", 0.35)), (0.0, _tone(NOTE["G4"], 2.6, "pad", 0.25)),
                          (0.35, _tone(NOTE["C5"], 2.2, "bell", 0.5)), (0.65, _tone(NOTE["E5"], 1.9, "bell", 0.45)),
                          (0.95, _tone(NOTE["G5"], 1.8, "bell", 0.45))])
        sting = _mix(1.0, [(0.0, _tone(NOTE["E5"], 0.9, "bell", 0.4)), (0.18, _tone(NOTE["G5"], 0.8, "bell", 0.35))])
        close = _mix(2.6, [(0.0, _tone(NOTE["G5"], 1.6, "bell", 0.4)), (0.3, _tone(NOTE["E5"], 1.6, "bell", 0.4)),
                           (0.6, _tone(NOTE["C5"], 2.0, "bell", 0.45)), (0.6, _tone(NOTE["C4"], 2.0, "pad", 0.3))])
    elif style == "B":
        notes = ["G4", "C5", "D5", "G5"]
        logo = _mix(1.9, [(0.13 * i, _tone(NOTE[n], 0.9, "marimba", 0.6)) for i, n in enumerate(notes)]
                    + [(0.52, _tone(NOTE["G4"], 1.3, "pad", 0.2))])
        sting = _mix(0.7, [(0.0, _tone(NOTE["D5"], 0.5, "marimba", 0.5)), (0.11, _tone(NOTE["G5"], 0.5, "marimba", 0.45))])
        close = _mix(1.9, [(0.13 * i, _tone(NOTE[n], 0.9, "marimba", 0.6)) for i, n in enumerate(reversed(notes))]
                     + [(0.52, _tone(NOTE["C4"], 1.3, "pad", 0.2))])
    elif style == "C":
        logo = _mix(2.2, [(0.0, _tone(NOTE["C3"], 0.6, "pulse", 0.7)), (0.45, _tone(NOTE["C3"], 0.6, "pulse", 0.6)),
                          (0.9, _tone(NOTE["A5"], 1.3, "bell", 0.45))])
        sting = _mix(0.8, [(0.0, _tone(NOTE["A5"], 0.75, "bell", 0.35))])
        close = _mix(2.0, [(0.0, _tone(NOTE["A5"], 1.1, "bell", 0.4)), (0.6, _tone(NOTE["C3"], 0.7, "pulse", 0.6))])
    else:
        raise ValueError(f"unknown style {style!r}")
    return {"logo": logo, "sting": sting, "close": close}


def sounds(root: Path, style: str) -> dict:
    from .audio import _write_wav
    d = Path(root) / DIR / style
    out = {k: d / f"{k}.wav" for k in ("logo", "sting", "close")}
    if not all(p.exists() for p in out.values()):
        d.mkdir(parents=True, exist_ok=True)
        for k, s in design(style).items():
            _write_wav(out[k], s, RATE)
    return out


def chosen(root: Path) -> str:
    try:
        v = json.loads((Path(root) / STATE).read_text("utf-8")).get("style", "")
    except (OSError, ValueError):
        return ""
    return v if v in STYLES else ""


def choose(root: Path, style: str, who: str = "Steven") -> dict:
    import datetime as dt
    if style not in STYLES and style != "off":
        raise ValueError(f"unknown style {style!r}")
    rec = {"style": "" if style == "off" else style, "at": dt.datetime.now().isoformat(timespec="seconds"), "by": who}
    p = Path(root) / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec) + "\n", "utf-8")
    return rec


def placement(parts: list) -> list:
    """For each (name, text) part: the sound before it. The logo opens the episode; a sting goes before each story,
    the quick hits and the deep dive's hand-off (never twice in a row, never before the first part)."""
    out = []
    for i, (name, _) in enumerate(parts):
        n = str(name).lower()
        if i == 0:
            out.append("logo")
        elif n.startswith(("story", "quick hits", "deep dive", "the deep dive", "why_today", "why today")) or n == "outro":
            out.append("sting" if n != "outro" else None)
        else:
            out.append(None)
    return out


def demo(root: Path, style: str, out: Path) -> Path:
    """logo, a beat of silence, a sting, a beat, the close: what the style sounds like, for the dashboard."""
    import numpy as np
    from .audio import _write_wav
    s = design(style)
    gap = np.zeros(int(0.8 * RATE))
    _write_wav(out, np.concatenate([s["logo"], gap, s["sting"], gap, s["close"]]), RATE)
    return out


def for_audio(root: Path) -> dict | None:
    """The chosen style's sounds for render_mp3, or None (no branding chosen, or numpy missing)."""
    style = chosen(root)
    if not style:
        return None
    try:
        return {k: str(v) for k, v in sounds(root, style).items()}
    except Exception:  # noqa: BLE001 - branding never stops an episode
        return None
