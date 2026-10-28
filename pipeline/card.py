"""The daily card: a branded image for the morning Slack post (Steven, 2026-10-28), in the newsletter's colours.

card.render(root, cfg, day, out) -> Path. 1600x900 PNG: the teal masthead (wordmark, photo, date), the day's three
leads, one of Steven's takes in his words, and the deep dive on a deep-teal band. Pillow, with the Inter files in
assets/fonts (OFL) so it looks the same on every machine. Text is already-published content only.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

TEAL, DEEP, PALE, INK, MUTED = "#3e7e8a", "#1e4a52", "#eef4f5", "#14272b", "#5b6d71"
W, H = 1600, 900


def _font(root: Path, weight: str, size: int):
    from PIL import ImageFont
    p = root / "assets" / "fonts" / f"Inter-{weight}.otf"
    try:
        return ImageFont.truetype(str(p), size)
    except OSError:
        return ImageFont.load_default()


def _plain(s: str) -> str:
    s = re.sub(r"\s*\[\d+\]\(https?://[^)]+\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return s.replace("**", "").replace("*", "").strip()


def leads(md: str, n: int = 3) -> list:
    """The bold lead phrases of the top section (Top of mind or Today in 30 seconds)."""
    sec = ""
    for head in ("## Today in 30 seconds", "## Top of mind"):
        if head in md:
            sec = md.split(head, 1)[1].split("\n## ", 1)[0]
            break
    out = []
    for m in re.finditer(r"(?m)^- \*\*(.+?)\.?\*\*", sec):
        out.append(_plain(m.group(1)).rstrip("."))
        if len(out) >= n:
            break
    return out


def pick_take(notes: dict, dd_take: str = "") -> tuple:
    """(text, where): the take with the most bite we can quote: 10-60 words, a full sentence, prefer stories."""
    cands = []
    for k, v in (notes or {}).items():
        t = _plain(str(v.get("text") or "")).strip()
        if t:
            cands.append((t, str(v.get("title") or "")))
    if dd_take:
        cands.append((_plain(dd_take), "the deep dive"))
    best = None
    for t, where in cands:
        sents = re.split(r"(?<=[.!?])\s+", t)
        quote = ""
        for s in sents:                                  # the first sentence(s) that fit
            if len((quote + " " + s).split()) > 45:
                break
            quote = (quote + " " + s).strip()
        words = len(quote.split())
        if words < 8:
            continue
        score = words + (10 if quote.rstrip().endswith((".", "?", "!")) else 0) + (5 if where != "The day overall" else 0)
        if best is None or score > best[0]:
            best = (score, quote, where)
    return (best[1], best[2]) if best else ("", "")


def _wrap(draw, text: str, font, width: int) -> list:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render(root: Path, day: str, md: str, notes: dict, dd_title: str = "", dd_line: str = "", dd_take: str = "",
           out: Path | None = None) -> Path:
    from PIL import Image, ImageDraw, ImageOps
    out = out or root / "data" / "cards" / f"{day}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (W, H), PALE)
    d = ImageDraw.Draw(img)
    # masthead
    d.rectangle([0, 0, W, 170], fill=TEAL)
    d.text((64, 44), "AI Briefing", font=_font(root, "Bold", 64), fill="white")
    date = dt.date.fromisoformat(day).strftime("%A, %B %-d, %Y")
    d.text((66, 118), f"{date}  ·  Slowly, then fast. Every morning.", font=_font(root, "Regular", 26), fill="#d8e9ec")
    photo = root / "assets" / "steven-woods.jpg"
    if photo.exists():
        p = Image.open(photo).convert("RGB")
        p = ImageOps.fit(p, (112, 112))
        mask = Image.new("L", (112, 112), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, 111, 111], fill=255)
        ring = Image.new("RGB", (120, 120), "white")
        rmask = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(rmask).ellipse([0, 0, 119, 119], fill=255)
        img.paste(ring, (W - 64 - 120, 25), rmask)
        img.paste(p, (W - 64 - 116, 29), mask)
    # leads
    y = 222
    d.text((64, y), "TODAY", font=_font(root, "SemiBold", 20), fill=TEAL)
    y += 40
    f_lead = _font(root, "SemiBold", 40)
    for lead in leads(md):
        d.ellipse([64, y + 16, 76, y + 28], fill=TEAL)
        for ln in _wrap(d, lead, f_lead, W - 64 - 96)[:2]:
            d.text((96, y), ln, font=f_lead, fill=INK)
            y += 50
        y += 12
    # take
    take, where = pick_take(notes, dd_take)
    if take:
        y += 22
        d.text((96, y), "STEVEN'S TAKE" + (f"  \u00b7  on {where}" if where and where != "The day overall" else ""),
               font=_font(root, "SemiBold", 20), fill=TEAL)
        y += 34
        f_q = _font(root, "Regular", 32)
        lines = _wrap(d, "\u201c" + take + "\u201d", f_q, W - 64 - 140)[:3]
        for i, ln in enumerate(lines):
            d.text((96, y + i * 42), ln, font=f_q, fill=INK)
        d.rectangle([64, y - 36, 70, y + len(lines) * 42 - 6], fill=TEAL)
        y += len(lines) * 42
    # the waveform motif from the cover, above the deep-dive band
    import random
    rnd = random.Random(day)
    x = 64
    while x < W - 64:
        h = rnd.choice([6, 10, 14, 20, 26, 32])
        d.rounded_rectangle([x, H - 170 - 26 - h, x + 8, H - 170 - 26], radius=3, fill="#b9d3d7")
        x += 16
    # deep dive band
    if dd_title:
        d.rectangle([0, H - 170, W, H], fill=DEEP)
        d.text((64, H - 138), "DEEP DIVE  ·  One story, slowly. Down to the details.", font=_font(root, "SemiBold", 20), fill="#9fcfd6")
        f_t = _font(root, "Bold", 42)
        tl = _wrap(d, dd_title, f_t, W - 128)[:1]
        d.text((64, H - 102), tl[0] if tl else dd_title, font=f_t, fill="white")
        if dd_line:
            f_l = _font(root, "Regular", 25)
            ll = _wrap(d, dd_line, f_l, W - 128)[:1]
            d.text((64, H - 48), ll[0], font=f_l, fill="#d8e9ec")
    img.save(out, "PNG", optimize=True)
    return out
