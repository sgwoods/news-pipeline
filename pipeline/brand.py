"""The AI Briefing brand (Steven, 2026-10-31): brand/brand.yaml is the one place for colours, type, the author image,
the waveform and the taglines. Every surface reads it: the website's style sheet (site.css), the email's palette
(email_palette), the Slack cards (card.py), the channel banner and covers (render_*), the feeds and the dashboard.

    ./np brand show | build [--covers]

`build` makes the author image sizes (assets/steven-woods.jpg, the 512 px icon), the Slack channel banner and, with
--covers, the two podcast covers. Images are made with Pillow and the Inter files in assets/fonts.
"""
from __future__ import annotations

import functools
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = "brand/brand.yaml"


@functools.lru_cache(maxsize=4)
def _load(path: str) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text("utf-8")) or {}


def load(root: Path | None = None) -> dict:
    """brand.yaml, with the colour tokens merged so every name has a light and a dark value."""
    f = (root or ROOT) / FILE
    d = dict(_load(str(f if f.is_file() else ROOT / FILE)))     # a checkout without its own brand file uses the repo's
    c = dict(d.get("colors") or {})
    d["colors"], d["dark"] = c, {**c, **(d.get("dark") or {})}
    return d


def color(name: str, root: Path | None = None, dark: bool = False) -> str:
    return load(root)["dark" if dark else "colors"][name]


def tagline(name: str, root: Path | None = None) -> str:
    return (load(root).get("taglines") or {}).get(name, "")


def author(root: Path | None = None) -> dict:
    return load(root).get("author") or {}


def font(root: Path, weight: str, size: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(root / "assets" / "fonts" / f"Inter-{weight}.otf"), size)
    except OSError:
        return ImageFont.load_default()


# ---------------------------------------------------------------- the author image
def author_image(root: Path, size: int, ring: int = 0, ring_color: str = "#ffffff"):
    """The author image as a round RGBA image of SIZE px, with a RING px ring (0 = none)."""
    from PIL import Image, ImageDraw
    f = root / author(root).get("image", "brand/author-master.png")
    src = Image.open(f if f.is_file() else ROOT / author(root).get("image", "brand/author-master.png")).convert("RGB")
    inner = size - 2 * ring
    w, h = src.size
    s = min(w, h)
    src = src.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((inner, inner), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if ring:
        rm = Image.new("L", (size, size), 0)
        ImageDraw.Draw(rm).ellipse([0, 0, size - 1, size - 1], fill=255)
        out.paste(Image.new("RGB", (size, size), ring_color), (0, 0), rm)
    m = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(m).ellipse([0, 0, inner - 1, inner - 1], fill=255)
    out.paste(src, (ring, ring), m)
    return out


def paste_author(img, root: Path, size: int, xy: tuple, ring: int = 4):
    a = author_image(root, size, ring)
    img.paste(a, xy, a)


def waveform(draw, x0: int, x1: int, base: int, seed: str, fill: str, heights=(6, 10, 14, 20, 26, 32),
             bar: int = 8, step: int = 16):
    rnd = random.Random(seed)
    x = x0
    while x < x1:
        h = rnd.choice(heights)
        draw.rounded_rectangle([x, base - h, x + bar, base], radius=bar // 2 - 1, fill=fill)
        x += step


# ---------------------------------------------------------------- images made from the brand
def render_banner(root: Path, out: Path | None = None) -> Path:
    """The #cto-ai-newsletter banner (1600x600), pinned in the channel."""
    from PIL import Image, ImageDraw
    b = load(root)
    c, t = b["colors"], b["taglines"]
    out = out or root / "brand" / "slack-channel-banner.png"
    W, H = 1600, 600
    im = Image.new("RGB", (W, H), c["teal"])
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - 120, W, H], fill=c["deep"])
    paste_author(im, root, 316, (W - 80 - 316, 92), ring=8)
    d.text((80, 92), b.get("name", "AI Briefing"), font=font(root, "Bold", 120), fill="white")
    d.text((84, 250), t["main"], font=font(root, "Regular", 44), fill=c["on_teal"])
    d.text((84, 316), t["channel"], font=font(root, "Regular", 30), fill=c["on_teal"])
    waveform(d, 84, W - 460, 420, "banner", c["wave"], (8, 14, 20, 28, 36), bar=10, step=20)
    d.text((84, H - 82), f'{t["audience"]}  ·  {t["byline"]}', font=font(root, "Regular", 30), fill=c["on_teal"])
    site = "sgwoods.github.io/ai-briefing"
    d.text((W - 80 - d.textlength(site, font=font(root, "SemiBold", 30)), H - 82), site,
           font=font(root, "SemiBold", 30), fill=c["on_deep"])
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, optimize=True)
    return out


def render_cover(root: Path, kind: str = "podcast", out: Path | None = None, size: int = 3000) -> Path:
    """A podcast cover (3000x3000): 'podcast' (teal) or 'deepdive' (deep teal), as the covers of 2026-10-27."""
    from PIL import Image, ImageDraw
    b = load(root)
    c, t = b["colors"], b["taglines"]
    k = size / 1932                                  # laid out on the 1932 px drawing of the original covers
    S = lambda v: int(v * k)  # noqa: E731
    deep = kind == "deepdive"
    im = Image.new("RGB", (size, size), c["deep"] if deep else c["teal"])
    d = ImageDraw.Draw(im)
    d.rectangle([0, S(1545), size, size], fill=c["teal"] if deep else "#2e6670")
    if deep:
        paste_author(im, root, S(480), (S(1312), S(134)), ring=S(14))
        d.rounded_rectangle([S(155), S(213), S(702), S(342)], radius=S(64), fill=c["teal"])
        d.text((S(203), S(240)), b.get("name", "AI Briefing"), font=font(root, "SemiBold", S(84)), fill="white")
        d.text((S(160), S(726)), b.get("deep_dive_name", "Deep Dive"), font=font(root, "Bold", S(285)), fill="white")
        lines = t["deep_dive"].replace(". ", ".\n", 1).split("\n")
        foot = [t["audience"], t["byline"]]
    else:
        paste_author(im, root, S(582), (S(140), S(134)), ring=S(14))
        d.text((S(160), S(778)), b.get("name", "AI Briefing"), font=font(root, "Bold", S(285)), fill="white")
        lines = t["main"].replace(". ", ".\n", 1).split("\n")
        foot = [f'Daily · {t["audience"][0].lower() + t["audience"][1:]}', t["byline"]]
        waveform(d, S(162), S(1800), S(1500), "cover", c["wave"], tuple(S(v) for v in (30, 40, 60, 95)),
                 bar=S(28), step=S(50))
    y = S(1100)
    for ln in lines:
        d.text((S(163), y), ln.strip(), font=font(root, "Regular", S(80)), fill=c["on_teal"])
        y += S(105)
    y = S(1650)
    for ln in foot:
        d.text((S(163), y), ln, font=font(root, "Regular", S(62)), fill=c["on_teal"])
        y += S(90)
    out = out or root / "assets" / f"{'deepdive' if deep else 'podcast'}-cover.png"
    im.save(out, optimize=True)
    return out


def build(root: Path, covers: bool = False, log=print) -> list:
    """The images made from the brand: author image sizes, the channel banner, and (covers=True) the covers."""
    from PIL import Image
    made = []
    a = author_image(root, 512).convert("RGB")
    sq = Image.new("RGB", (512, 512), color("teal", root))
    sq.paste(author_image(root, 512), (0, 0), author_image(root, 512))
    p = root / "assets" / "steven-woods.jpg"                   # email masthead, site masthead, og fallback
    sq.resize((240, 240), Image.LANCZOS).save(p, quality=90)
    made.append(p)
    p = root / "brand" / "author-icon-512.png"                 # the Slack app icon (upload in the app's settings)
    sq.save(p, optimize=True)
    made.append(p)
    made.append(render_banner(root))
    if covers:
        made += [render_cover(root, "podcast"), render_cover(root, "deepdive")]
    for m in made:
        log(f"brand: wrote {m.relative_to(root)}")
    del a
    return made


# ---------------------------------------------------------------- web and email
def css_tokens(root: Path | None = None) -> str:
    """The :root block for the website: light values, the reader's dark mode, Inter."""
    b = load(root)
    c, k = b["colors"], b["dark"]
    names = ("teal", "deep", "pale", "ink", "muted", "wave", "line", "panel", "on_teal", "on_deep", "gold")
    light = ";".join(f"--{n.replace('_', '-')}:{c[n]}" for n in names)
    dark = ";".join(f"--{n.replace('_', '-')}:{k[n]}" for n in names)
    return (f":root{{{light};--font:{b['fonts']['stack']}}}\n"
            f"@media (prefers-color-scheme:dark){{:root{{{dark}}}}}\n")


def email_palette(root: Path | None = None) -> dict:
    """The email's colours (mail apps take inline styles only): pale surface, white cards, teal accents."""
    c = load(root)["colors"]
    return {"bg": c["pale"], "panel": c["panel"], "card": c["pale"], "border": c["line"], "text": c["ink"],
            "muted": c["muted"], "strong": c["ink"], "accent": c["teal"], "accent_ink": "#ffffff", "link": c["teal"],
            "brand": c["teal"], "brand_deep": c["deep"], "brand_ink": c["on_teal"], "gold": c["gold"]}
