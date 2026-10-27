"""Static, phone-friendly public site: briefings + Steven's commentary (+ recent MP3s).

Builds into site/ (gitignored here). `./np publish` pushes it to a SEPARATE public repo
served by GitHub Pages. Only briefings, notes and audio are published: never data/
(it holds the full text of other people's articles).
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import shutil
from email.utils import format_datetime
from pathlib import Path

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CSS = '''
:root{--bg:#07131f;--bg2:#10253b;--panel-bg:rgba(7,19,31,.68);--panel-glow:rgba(103,230,168,.14);
--card-bg:rgba(255,255,255,.05);--card-border:rgba(255,255,255,.08);--panel-border:rgba(177,222,255,.18);
--button-bg:rgba(121,184,255,.18);--button-border:rgba(121,184,255,.28);--text:#eff7ff;--muted:#9cc4df;
--muted-strong:#d7ecff;--accent:#67e6a8;--link:#d9f7ff;--shadow:0 18px 40px rgba(0,0,0,.28)}
/* tokens from sgwoods.github.io/public/assets/public-site.css, so this site matches Steven's public pages */
*{box-sizing:border-box}html{color-scheme:dark;-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;color:var(--text);font:17px/1.6 "Avenir Next","Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,sans-serif;
background:radial-gradient(circle at top left,rgba(103,230,168,.18),transparent 26%),radial-gradient(circle at top right,rgba(121,184,255,.22),transparent 32%),linear-gradient(160deg,var(--bg),var(--bg2)) fixed}
a{color:var(--link)}a:hover{color:var(--accent)}
.shell{max-width:1100px;margin:0 auto;padding:32px 20px 72px}.shell--narrow{max-width:780px}
.hero,.panel{border:1px solid var(--panel-border);border-radius:28px;box-shadow:var(--shadow);
background:linear-gradient(160deg,rgba(12,34,54,.88),rgba(7,19,31,.72)),radial-gradient(circle at 20% 0%,var(--panel-glow),transparent 32%)}
.hero{padding:34px 34px 30px}.panel{margin-top:22px;padding:26px 28px;background:var(--panel-bg)}
.heroTop{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px;flex-wrap:wrap}
.eyebrow{display:inline-flex;align-items:center;gap:10px;padding:7px 12px;border-radius:999px;background:rgba(255,255,255,.08);
color:var(--muted-strong);font-size:12px;letter-spacing:.14em;text-transform:uppercase}
.heroHomeLink{font-size:14px;color:var(--muted);text-decoration:none}.heroHomeLink:hover{color:var(--accent)}
.hero h1{font-size:44px;line-height:1.08;margin:6px 0 10px;letter-spacing:-.01em}.lead{font-size:19px;color:var(--muted-strong);max-width:720px;margin:0 0 20px}
.actions{display:flex;flex-wrap:wrap;gap:10px}
.button,button,select{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 16px;border-radius:999px;
background:var(--button-bg);border:1px solid var(--button-border);color:var(--text);text-decoration:none;font:inherit;font-size:14px;letter-spacing:.04em;cursor:pointer}
.button:hover,button:hover,.button:focus{background:rgba(121,184,255,.26);color:var(--text)}
.button.primary{background:var(--accent);border-color:var(--accent);color:#06221a;font-weight:600}.button.primary:hover{background:#86f0bd;color:#06221a}
.button.ghost{background:rgba(255,255,255,.04)}button.on{background:var(--accent);border-color:var(--accent);color:#06221a}
.card,.entry{padding:18px;border-radius:20px;background:var(--card-bg);border:1px solid var(--card-border)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.panel>h2,.sectionTitle{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 14px;border:0;padding:0}
.k{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.latest h3{font-size:26px;line-height:1.2;margin:6px 0 12px}.latest h3 a{text-decoration:none;color:var(--text)}
.latest ul{padding-left:20px}.latest li{margin-bottom:8px}.latest li strong{color:var(--accent);font-weight:600}
.bio{display:flex;gap:20px;align-items:flex-start}.bio img{width:112px;height:112px;border-radius:50%;object-fit:cover;
border:2px solid var(--panel-border);box-shadow:0 0 0 6px rgba(103,230,168,.08);flex:none}
.bio h3{margin:0 0 4px;font-size:22px}.bio .role{color:var(--accent);font-size:14px;margin:0 0 10px}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.pills .button{padding:7px 12px;font-size:13px}
.how b{display:block;margin-bottom:4px}.how span{color:var(--muted);font-size:14px}
.feedrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
.feedrow code{font-size:13px;word-break:break-all;background:rgba(255,255,255,.06);border:1px solid var(--card-border);padding:7px 10px;border-radius:10px}
.muted{color:var(--muted)}.small{font-size:14px}
.day{padding:14px 0;border-bottom:1px solid var(--card-border)}.day:last-child{border-bottom:0}.day a.d{font-weight:600;font-size:18px;text-decoration:none}
audio{width:100%;margin:10px 0;border-radius:999px}
/* share, subscribe, rate */
.sharebox{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:14px 0;padding:14px 16px;border-radius:20px;
background:rgba(103,230,168,.07);border:1px solid rgba(103,230,168,.22)}
.sharebox .lbl{font-weight:600;margin-right:4px}.sharebox .button{padding:8px 14px;font-size:14px}
.stars{display:flex;gap:4px;align-items:center;flex-wrap:wrap}.stars a{font-size:34px;line-height:1;color:#ffd166;text-decoration:none;padding:0 2px}
.stars a:hover,.stars a:focus{transform:scale(1.15)}.endbox{margin-top:34px;padding-top:6px;border-top:1px solid var(--card-border)}
.baracts{margin-left:auto;display:inline-flex;gap:8px}.bar .button{padding:8px 14px}
.ddread{margin-top:10px;padding-top:4px;border-top:1px solid var(--card-border)}.ddread p{margin:0 0 14px}
.dive h3{font-size:19px;line-height:1.3;margin:6px 0 6px}.dive h3 a{color:var(--text);text-decoration:none}
.dive .actions{margin-top:10px}.dive .button{padding:8px 14px;font-size:13px}
.subform{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
.subform input[type=email]{flex:1;min-width:220px;font:inherit;font-size:15px;padding:10px 14px;border-radius:999px;
border:1px solid var(--button-border);background:rgba(255,255,255,.06);color:var(--text)}
/* briefing pages */
header.site{max-width:780px;margin:0 auto;padding:22px 20px 0;display:flex;justify-content:space-between;align-items:center;gap:12px}
header.site a{color:var(--text);text-decoration:none;font-weight:600}header.site a.home{color:var(--muted);font-weight:400;font-size:14px}
main{max-width:780px;margin:16px auto 0;padding:24px 28px 40px;border:1px solid var(--panel-border);border-radius:28px;background:var(--panel-bg);box-shadow:var(--shadow)}
main h1{font-size:30px;line-height:1.2;margin:8px 0 12px}main h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:34px 0 10px;border-bottom:1px solid var(--card-border);padding-bottom:6px}
main h3{font-size:19px;margin:24px 0 4px;line-height:1.35}ul{padding-left:20px}li{margin-bottom:6px}main li strong{color:var(--muted-strong)}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--card-border);padding:6px 8px;text-align:left}
.take{background:rgba(103,230,168,.08);border-left:3px solid var(--accent);padding:10px 14px;border-radius:0 14px 14px 0;margin:8px 0 18px}
.take b{display:block;font-size:12px;color:var(--accent);text-transform:uppercase;letter-spacing:.12em;margin-bottom:2px}
.bar{position:sticky;top:0;background:rgba(7,19,31,.92);backdrop-filter:blur(8px);display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid var(--card-border);z-index:5}
section.speaking{outline:2px solid var(--accent);outline-offset:6px;border-radius:6px}
footer{max-width:1100px;margin:28px auto 0;padding:0 20px 40px;font-size:13px;color:var(--muted)}
@media(max-width:640px){.shell{padding:18px 14px 56px}.hero{padding:24px 20px;border-radius:22px}.hero h1{font-size:34px}
.panel{padding:20px 18px;border-radius:22px}main{padding:18px 16px 30px;border-radius:22px;margin:12px 10px 0}
.bio{flex-direction:column}.lead{font-size:17px}
.bar{gap:6px}.bar button,.bar .button{padding:7px 11px;font-size:13px;letter-spacing:.02em}.baracts{gap:6px}}
.doc img{max-width:100%;height:auto;margin:12px 0}.doc table{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}.doc td,.doc th{border:1px solid #d9dde3;padding:6px 8px;text-align:left;vertical-align:top}.doc pre{overflow:auto;padding:10px;background:rgba(127,127,127,.08)}.doc code{font-size:.92em}
'''

LISTEN_JS = """
(() => {
  const mp3 = document.getElementById("mp3"), synth = window.speechSynthesis;
  const bR = document.getElementById("read"), bL = document.getElementById("listen"), ctl = document.getElementById("ctl");
  const rate = () => parseFloat(document.getElementById("rate").value);
  let q = [];
  function clear(){document.querySelectorAll("section.speaking").forEach(s=>s.classList.remove("speaking"));}
  function stop(){ if(mp3) mp3.pause(); if(synth){q=[];synth.cancel();} clear(); }
  function next(){ if(!q.length){clear();return;} const el=q.shift(); clear(); el.classList.add("speaking");
    el.scrollIntoView({behavior:"smooth",block:"start"});
    const c=el.cloneNode(true); c.querySelectorAll("a").forEach(a=>a.remove());
    const u=new SpeechSynthesisUtterance(c.innerText.replace(/\\s*·\\s*/g,". ")); u.rate=rate(); u.onend=next; synth.speak(u); }
  function play(){ if(mp3){mp3.hidden=false; mp3.playbackRate=rate(); mp3.play(); return;}
    if(!synth){alert("No speech support in this browser.");return;} stop(); q=[...document.querySelectorAll("#brief section")]; next(); }
  function mode(l){ bR.classList.toggle("on",!l); bL.classList.toggle("on",l); ctl.hidden=!l; if(!l) stop(); }
  bR.onclick=()=>mode(false); bL.onclick=()=>mode(true);
  document.getElementById("play").onclick=play; document.getElementById("stop").onclick=stop;
})();
"""


def _md_to_html(text: str) -> str:
    import markdown
    out = markdown.markdown(text.replace("&", "&amp;").replace("<", "&lt;"), extensions=["tables"])
    out = re.sub(r'href="(?!https?://|#)[^"]*"', 'href="#"', out)
    return out.replace("<a href=\"http", "<a rel=\"noopener\" target=\"_blank\" href=\"http")


def _take(text: str) -> str:
    body = "<br>".join(htmllib.escape(p) for p in text.strip().splitlines())
    return f'<div class="take"><b>Steven\'s take</b>{body}</div>'


def _with_takes(page: str, notes: dict) -> str:
    from .textutil import item_id
    def note(k):
        return (notes.get(k) or {}).get("text", "").strip()
    out = []
    for ch in re.split(r"(?=<h[23]>)", page):
        m = re.match(r"<h([23])>(.*?)</h\1>", ch, re.S)
        key = None
        if m:
            head = re.sub(r"<[^>]+>", "", m.group(2)).strip().lower()
            if m.group(1) == "3":
                href = re.search(r'href="(https?://[^"]+)"', ch)
                key = item_id(htmllib.unescape(href.group(1))) if href else None
            elif head.startswith("top of mind"):
                key = "top"
            elif head.startswith("worth knowing"):
                key = "worth"
            elif head.startswith(("in brief", "also seen")):
                key = "also"
        extra = _take(note(key)) if key and note(key) else ""
        out.append(f"<section>{ch}{extra}</section>" if m else f"<section>{ch}</section>")
    if note("overall"):
        out.append(f"<section>{_take(note('overall'))}</section>")
    return "".join(out)


TAKES_JS = r"""
// Steven's takes on the site page (pipeline/takes.py): shown only with his signed link (#takes=<token>, from his
// private takes email). The token never leaves this page except in the form he submits to the mail script, which
// checks it; a visitor without it sees nothing. Boxes go after the day in brief (0), Top of mind (T), each Must-read
// story (its number) and Worth knowing (W); one Submit sends them all.
(function () {
  var started = false;
  function start() {
  if (started) return;
  var m = /(?:^|[#&])takes=([A-Za-z0-9_-]{8,64})/.exec(location.hash || "");
  var s = document.querySelector("script[data-takes]");
  var root = document.getElementById("brief");
  if (!m || !s || !root) return;
  var url = s.getAttribute("data-script"), day = s.getAttribute("data-day");
  if (!/^https:\/\/script\.google\.com\//.test(url || "") || !/^\d{4}-\d{2}-\d{2}$/.test(day || "")) return;
  var boxes = [], inMust = false;
  function add(sec, slot, label) {
    var d = document.createElement("div");
    d.style.cssText = "margin:10px 0 18px;padding:10px 12px;border:1px dashed #60a5fa;border-radius:10px";
    var l = document.createElement("div");
    l.textContent = "Your take: " + label + " (" + slot + ")";
    l.style.cssText = "font-size:13px;opacity:.8;margin:0 0 6px";
    var ta = document.createElement("textarea");
    ta.rows = 3; ta.setAttribute("data-slot", slot);
    ta.style.cssText = "width:100%;box-sizing:border-box;font:inherit;font-size:15px;padding:8px;border-radius:8px";
    d.appendChild(l); d.appendChild(ta); sec.appendChild(d); boxes.push(ta);
  }
  var secs = root.children;
  for (var i = 0; i < secs.length; i++) {
    var sec = secs[i];
    if (sec.tagName !== "SECTION") continue;
    var h = sec.querySelector("h2, h3");
    if (!h) { if (!boxes.length) add(sec, "0", "the day overall"); continue; }
    var txt = h.textContent.trim().toLowerCase();
    if (h.tagName === "H2") {
      inMust = txt.indexOf("must read") === 0;
      if (txt.indexOf("top of mind") === 0) add(sec, "T", "Top of mind");
      else if (txt.indexOf("worth knowing") === 0) add(sec, "W", "Worth knowing");
      continue;
    }
    var n = /^(\d{1,2})\./.exec(h.textContent.trim());
    if (inMust && n) add(sec, n[1], "story " + n[1]);
  }
  if (!boxes.length) return;
  var f = document.createElement("form");
  f.method = "POST"; f.action = url;
  f.style.cssText = "position:sticky;bottom:0;padding:12px;background:#0b1b2b;border-top:1px solid #23415d;z-index:9";
  function hidden(n, v) { var x = document.createElement("input"); x.type = "hidden"; x.name = n; x.value = v; f.appendChild(x); return x; }
  hidden("action", "takes"); hidden("t", m[1]); hidden("d", day);
  var payload = hidden("takes", "{}"), done = hidden("done", "");
  var cb = document.createElement("label");
  cb.style.cssText = "color:#e5f2ff;font-size:14px;margin-right:12px";
  var c = document.createElement("input"); c.type = "checkbox"; cb.appendChild(c);
  cb.appendChild(document.createTextNode(" Done: send the edition now"));
  var b = document.createElement("button"); b.type = "submit"; b.textContent = "Submit my takes";
  b.style.cssText = "padding:8px 16px;border-radius:999px;border:0;background:#2563eb;color:#fff;font-size:15px";
  f.appendChild(cb); f.appendChild(b);
  f.addEventListener("submit", function () {
    var o = {};
    boxes.forEach(function (ta) { var v = ta.value.trim(); if (v) o[ta.getAttribute("data-slot")] = v.slice(0, 1500); });
    payload.value = JSON.stringify(o); done.value = c.checked ? "1" : "";
  });
  var note = document.createElement("p");
  note.textContent = "Private: your takes for " + day + ". Type after any section, then Submit once. Only you see these boxes.";
  note.style.cssText = "padding:10px 12px;border-radius:10px;background:#1e3a5f;color:#e5f2ff;font-size:14px";
  root.insertBefore(note, root.firstChild);
  root.parentNode.insertBefore(f, root.nextSibling);
  started = true;
  }
  start();
  window.addEventListener("hashchange", start);   // an already-open page gets the boxes without a reload
})();
"""

SHARE_JS = """
(() => {
  document.querySelectorAll("[data-share]").forEach(b => b.addEventListener("click", async ev => {
    ev.preventDefault();
    const url = b.dataset.url || location.href, title = b.dataset.title || document.title;
    if (navigator.share) { try { await navigator.share({title, url}); return; } catch (e) { if (e.name === "AbortError") return; } }
    try { await navigator.clipboard.writeText(url); b.textContent = "Link copied"; } catch (e) { prompt("Copy this link:", url); }
  }));
  document.querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", async ev => {
    ev.preventDefault();
    const url = b.dataset.url || location.href;
    try { await navigator.clipboard.writeText(url); b.textContent = "Copied"; } catch (e) { prompt("Copy this link:", url); }
  }));
})();
"""


def _dd_head(md: str) -> str:
    """A deep dive's notes up to its source list (title, byline, summary, why today)."""
    return md.split("\n## Sources", 1)[0]


def _dd_sources(md: str) -> str:
    return ("## Sources" + md.split("\n## Sources", 1)[1]) if "\n## Sources" in md else ""


def _clip(t: str, n: int) -> str:
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _script_url(cfg: dict) -> str:
    u = ((cfg.get("email") or {}).get("script_url") or "")
    return u if u.startswith("https://script.google.com/") else ""


def _share_box(url: str, title: str, rel: str, cfg: dict, what: str = "this episode", subscribe: bool = True) -> str:
    """Share (phone share sheet, or copy), email it, and the way in: subscribe by email or add the podcast."""
    from urllib.parse import quote
    e = htmllib.escape
    mail = (f"mailto:?subject={quote(title)}&body="
            + quote(f"I thought you might like this: {title}\n{url or ''}\n\nThe AI Briefing: a daily read on AI, as a newsletter and a podcast."))
    sub = (f'<a class="button" href="{rel}index.html#email">✉ Subscribe by email</a>' if subscribe and _script_url(cfg) else "")
    return (f'<div class="sharebox"><span class="lbl">Share {e(what)}</span>'
            f'<a class="button primary" href="{e(url or "#")}" data-share data-url="{e(url)}" data-title="{e(title)}">Share</a>'
            f'<a class="button" href="{e(url or "#")}" data-copy data-url="{e(url)}">Copy link</a>'
            f'<a class="button" href="{e(mail)}">Email it</a>{sub}'
            f'<a class="button ghost" href="{rel}index.html#listen">🎧 Add the podcast</a></div>')


def _subscribe_form(cfg: dict) -> str:
    script = _script_url(cfg)
    if not script:
        return ""
    return (f'<form class="subform" method="post" action="{htmllib.escape(script)}">'
            '<input type="hidden" name="action" value="subscribe">'
            '<input type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" '
            'style="position:absolute;left:-9999px;width:1px;height:1px">'
            '<input type="email" name="email" required maxlength="200" placeholder="you@example.com" aria-label="Email address">'
            '<button type="submit" class="button primary">Subscribe</button></form>')


def _stars(cfg: dict, day: str) -> str:
    """Anonymous one-click stars for a day page (they open the script's confirm page)."""
    script = _script_url(cfg)
    if not script or not (cfg.get("email") or {}).get("ratings"):
        return ""
    links = "".join(f'<a href="{htmllib.escape(script)}?action=rate&amp;d={day}&amp;s={n}" title="{n} of 5" '
                    f'aria-label="{n} of 5 stars">★</a>' for n in range(1, 6))
    return (f'<h2 id="rate">Rate this briefing</h2><div class="stars">{links}<span class="small muted" style="margin-left:8px">'
            f'1 poor · 5 excellent</span></div>')


def _end_box(cfg: dict, day: str, url: str, title: str, rel: str, what: str = "this briefing") -> str:
    sub = _subscribe_form(cfg)
    return ('<div class="endbox">' + _stars(cfg, day)
            + (f'<h2 id="subscribe">Get it by email</h2><p class="small">One email each morning when the briefing is published. '
               f'Confirm once; unsubscribe with one click.</p>{sub}' if sub else "")
            + _share_box(url, title, rel, cfg, what, subscribe=not sub) + '</div>')


def _bar_actions(url: str, title: str, rel: str, cfg: dict) -> str:
    """Compact Share / Subscribe in the sticky bar: always in reach while reading."""
    e = htmllib.escape
    sub = (f'<a class="button" href="#subscribe">✉ Subscribe</a>' if _script_url(cfg) else "")
    return (f'<span class="baracts"><a class="button primary" href="{e(url or "#")}" data-share data-url="{e(url)}" '
            f'data-title="{e(title)}">Share</a>{sub}</span>')


def staging_site_url(cfg: dict) -> str:
    pc = cfg.get("publish") or {}
    return pc.get("staging_site_url") or "https://sgwoods.github.io/ai-briefing-staging/"


def staging_cfg(cfg: dict) -> dict:
    """The staging site: no subscribe forms (no email script), its own base URL."""
    return {**cfg, "email": {**(cfg.get("email") or {}), "script_url": ""}}


def _staging_banner(cfg: dict) -> str:
    from .version import full
    prod = ((cfg.get("publish") or {}).get("site_url") or "").rstrip("/") + "/"
    return (f'<div style="background:#7a4b00;color:#fff;padding:8px 16px;font:14px/1.4 system-ui,sans-serif;'
            f'text-align:center">Development preview · v{htmllib.escape(full())} · not the published edition · '
            f'<a style="color:#fff;text-decoration:underline" href="{htmllib.escape(prod)}">Go to the published site</a></div>')


def _page(title: str, body: str, rel: str = "", cfg: dict | None = None, bare: bool = False) -> str:
    from .env import staging
    if staging():
        body = _staging_banner(cfg or {}) + body
        title = f"[Preview] {title}"
    sc = site_cfg(cfg or {})
    head_link = (f'<header class="site"><a href="{rel}index.html">AI Briefing</a><a class="home" href="{htmllib.escape(sc["home_url"])}">'
                 f'{htmllib.escape(sc["home_label"])} ↗</a></header>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{htmllib.escape(title)}</title><link rel="stylesheet" href="{rel}style.css">'
            f'<meta name="description" content="{htmllib.escape(sc["tagline"])}">'
            f'<meta property="og:title" content="{htmllib.escape(title)}"><meta property="og:description" content="{htmllib.escape(sc["tagline"])}">'
            f'<meta property="og:image" content="{htmllib.escape(sc["photo"])}">'
            + ('<meta name="robots" content="noindex,nofollow">' if _is_staging() else '') +
            f'<link rel="alternate" type="application/rss+xml" title="AI Briefing" href="{rel}feed.xml"></head><body>'
            + (body if bare else f'{head_link}<main>{body}</main>') + f'<script src="{rel}share.js"></script>' +
            f'<footer>Daily AI briefing for early-stage investors, curated by {htmllib.escape(sc["name"])}. Analysis is machine-generated '
            f'from public sources (every claim links to its source); "Steven\'s take" is personal opinion. '
            + (f'<a href="{rel}index.html#email">Subscribe by email</a> · ' if _script_url(cfg or {}) else "")
            + f'<a href="{rel}index.html#listen">Add the podcast</a> · '
            f'<a href="{rel}feed.xml">RSS</a> · <a href="{rel}podcast.xml">Podcast feed</a> · '
            f'<a href="{rel}{DD_FEED}">Deep-dive feed</a>'
            + _version_links(rel, cfg or {}, sc) + '</footer></body></html>')


def _is_staging() -> bool:
    from .env import staging
    return staging()


def _version_links(rel: str, cfg: dict, sc: dict) -> str:
    """'· v0.1 beta (release notes) · Code · All projects' in every footer."""
    from .version import short
    code = cfg.get("code_repo") or ""
    return (f'<br><span class="small"><a href="{rel}releases/index.html">{htmllib.escape(short())}</a>'
            + f' · <a href="{rel}docs/index.html">Docs</a>'
            + (f' · <a href="https://github.com/{htmllib.escape(code)}">Code</a>' if code else "")
            + (f' · <a href="{htmllib.escape(sc["home_url"])}">{htmllib.escape(sc["home_label"] or "All projects")}</a>'
               if sc.get("home_url") else "") + "</span>")


def releases_page(cfg: dict) -> str:
    """<site>/releases/: the release notes, from CHANGELOG.md."""
    from .version import full, releases
    body = [f'<h1>Release notes</h1><p class="muted">Running <b>v{htmllib.escape(full())}</b>. Changes are built and '
            'tested on a development branch and reach production together as a release.</p>']
    for head, md in releases():
        body.append(f'<section class="panel"><h2>{htmllib.escape(head)}</h2>{_md_to_html(md)}</section>')
    return _page("AI Briefing · Release notes", "".join(body), "../", cfg)


def site_cfg(cfg: dict) -> dict:
    """Public-page text and links: neutral defaults, then the owner's bio (owner.yaml site:), then `site:` in config.yaml."""
    from .owner import get as owner
    return {
        "tagline": "Slowly, then fast. Every morning. A daily briefing on AI for early-stage investors: what happened, "
                   "what holds up, and what it means.",
        "name": "", "role": "", "photo": "", "bio": "", "why": "",
        "about": ("Every morning this briefing reads a hand-picked list of researchers, builders, sceptics and investors, "
                  "groups what they wrote into stories, and checks the big claims before they reach you. It is written by "
                  "AI models from public sources and every claim links to its source."),
        "home_url": "", "home_label": "",
        "apple_podcasts_url": "",          # the Apple Podcasts show page, once the feed is listed there
        "links": [],
        **(owner().get("site") or {}),
        **(cfg.get("site") or {}),
    }


def build(root: Path, cfg: dict, out: Path | None = None, base_url: str = "", audio_days: int = 30) -> dict:
    paths = cfg.get("paths", {})
    bdir = root / paths.get("briefings", "briefings")
    out = out or root / "site"
    if out.exists():
        shutil.rmtree(out)
    (out / "audio").mkdir(parents=True)
    (out / "style.css").write_text(CSS, "utf-8")
    (out / "listen.js").write_text(LISTEN_JS, "utf-8")
    if _is_staging():                                    # the development preview stays out of search engines
        (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", "utf-8")
    (out / "share.js").write_text(SHARE_JS, "utf-8")
    (out / "takes.js").write_text(TAKES_JS, "utf-8")
    from .mailer import PHOTO                    # the email masthead's photo, served from the site
    if (root / "assets" / PHOTO).exists():
        shutil.copy2(root / "assets" / PHOTO, out / PHOTO)
    (out / ".nojekyll").write_text("", "utf-8")
    from .episodes import audio_file, guid, hidden_days
    hidden = hidden_days(root)
    built_keys = []
    days = sorted((f.stem for f in bdir.glob("*.md") if DAY_RE.match(f.stem) and f.stem not in hidden), reverse=True)
    cutoff = (dt.date.today() - dt.timedelta(days=audio_days - 1)).isoformat()
    rows, feed, n_audio, episodes, latest = [], [], 0, [], None
    try:
        from .deepdive import episodes_for_feed
        dives = episodes_for_feed(root, days)
    except Exception:  # noqa: BLE001 - deep dives never break the site
        dives = []
    dive_by_day = {e["day"]: e for e in dives}
    for day in days:
        md = (bdir / f"{day}.md").read_text("utf-8")
        cpath = root / "data" / "commentary" / f"{day}.json"
        notes = json.loads(cpath.read_text("utf-8")).get("notes", {}) if cpath.exists() else {}
        title = md.splitlines()[0].lstrip("# ").strip() if md.startswith("# ") else f"AI Briefing {day}"
        mp3 = bdir / f"{day}.mp3"
        has_audio = mp3.is_file() and day >= cutoff
        afile = audio_file(root, day)
        play_file = afile                                # the day page plays the combined episode when there is one
        if has_audio:
            shutil.copy2(mp3, out / "audio" / afile)
            n_audio += 1
            built_keys.append(day)
            ep = {"day": day, "title": title, "md": md, "mp3": mp3, "file": afile, "guid": guid(root, day)}
            tvtt = root / "data" / "transcripts" / f"{day}.vtt"     # as-published transcript (pipeline/listen.py)
            if tvtt.exists():
                shutil.copy2(tvtt, out / "audio" / f"{day}.vtt")
                ep["vtt"] = f"{day}.vtt"
            full = bdir / f"{day}.podcast.mp3"          # briefing + hand-off + deep dive in one episode
            if full.is_file() and day in dive_by_day:
                ffile = afile.replace(".mp3", "-full.mp3")
                shutil.copy2(full, out / "audio" / ffile)
                dd_t = dive_by_day[day]["title"].removeprefix("Deep dive: ")
                ep.update(mp3=full, file=ffile, combined=True, title=f"{title} · with deep dive: {dd_t}")
                play_file = ffile
            episodes.append(ep)
        audio_tag = f'<audio id="mp3" controls preload="none" src="../audio/{play_file}" hidden></audio>' if has_audio else ""
        if has_audio and (out / "audio" / f"{day}.vtt").exists():
            audio_tag += f'<p class="small muted"><a href="../audio/{day}.vtt">Transcript of the episode as published</a></p>'
        bar = ('<div class="bar"><button id="read" class="on" type="button">Read</button>'
               '<button id="listen" type="button">Listen</button><span id="ctl" hidden>'
               '<button id="play" type="button">▶ Play</button> <button id="stop" type="button">■ Stop</button> '
               '<select id="rate"><option>0.9</option><option selected>1</option><option>1.15</option><option>1.3</option></select>'
               f'</span></div>{audio_tag}')
        body_html = _with_takes(_md_to_html(md), notes)
        try:                                     # a shipped edition that was corrected says so (pipeline/shipped.py)
            from .shipped import corrections
            fixes = corrections(root, day)
        except Exception:  # noqa: BLE001
            fixes = []
        if fixes:
            body_html = "".join(f'<p class="small muted"><b>Corrected {htmllib.escape(c["at"][:10])}:</b> '
                                f'{htmllib.escape(c["note"])}</p>' for c in fixes) + body_html
        day_url = f"{base_url.rstrip('/')}/{day}/" if base_url else ""
        what = "this episode" if has_audio else "this briefing"
        bar = bar.replace('</span></div>', '</span>' + _bar_actions(day_url, title, "../", cfg) + '</div>', 1)
        page = _page(title, f'{bar}<div id="brief">{body_html}</div>'
                     f'{_end_box(cfg, day, day_url, title, "../", what)}<script src="../listen.js"></script>'
                     + (f'<script src="../takes.js" data-takes data-script="{htmllib.escape(_script_url(cfg), quote=True)}" '
                        f'data-day="{day}"></script>' if _script_url(cfg) else ""), "../", cfg)
        (out / day).mkdir()
        (out / day / "index.html").write_text(page, "utf-8")
        brief = re.search(r"\*\*The day in brief\.\*\* (.+)", md)
        tom = re.findall(r"^- (.+)$", md.split("## Top of mind", 1)[1].split("\n## ", 1)[0], re.M) if "## Top of mind" in md else []
        preview = brief.group(1) if brief else (tom[0] if tom else "")
        preview = re.sub(r"\[(\d+)\]\(https?://[^)]+\)", "", preview).replace("**", "").strip()
        if latest is None:
            latest = {"day": day, "title": title, "brief": preview, "top": tom, "audio": has_audio, "file": play_file}
        dd = dive_by_day.get(day)
        dd_link = (f'<div class="small" style="margin-top:4px">🎧 <b>Deep dive:</b> <a href="{day}/deep-dive/index.html">'
                   f'{htmllib.escape(dd["title"].removeprefix("Deep dive: "))}</a></div>' if dd else "")
        rows.append(f'<div class="day"><a class="d" href="{day}/index.html">{htmllib.escape(title)}</a>'
                    f'{" 🔊" if has_audio else ""}<div class="small muted">{htmllib.escape(preview[:260])}</div>{dd_link}</div>')
        d = dt.datetime.fromisoformat(day + "T07:00:00").astimezone()
        link = f"{base_url.rstrip('/')}/{day}/" if base_url else f"{day}/index.html"
        enc = (f'<enclosure url="{base_url.rstrip("/")}/audio/{afile}" length="{mp3.stat().st_size}" type="audio/mpeg"/>'
               if has_audio and base_url else "")
        feed.append(f"<item><title>{htmllib.escape(title)}</title><link>{link}</link><guid>{link}</guid>"
                    f"<pubDate>{format_datetime(d)}</pubDate><description>{htmllib.escape(preview)}</description>{enc}</item>")
    try:                                   # topical deep dives: bonus episodes right after their day's briefing
        for e in dives:
            e["audio"] = e["day"] >= cutoff
            if e["audio"]:
                shutil.copy2(e["mp3"], out / "audio" / e["file"])
            (out / e["day"] / "deep-dive").mkdir(parents=True, exist_ok=True)
            player = (f'<audio controls preload="none" src="../../audio/{e["file"]}"></audio>' if e["audio"] else
                      '<p class="small muted">The audio for this deep dive has rolled out of the feed; the script is below.</p>')
            dd_url = f"{base_url.rstrip('/')}/{e['day']}/deep-dive/" if base_url else ""
            written = e.get("written") or ""
            nav = ('<div class="actions" style="margin:6px 0 14px"><a class="button primary" href="#read">Read it</a>'
                   + ('<a class="button" href="#listen">▶ Listen</a>' if e["audio"] else "") + '</div>') if written else ""
            head = _dd_head(e["md"])
            if written:                                  # the article has its own "Why today" section
                head = re.sub(r"(?m)^\*\*Why today\.\*\*.*\n?", "", head)
            try:                                         # corrections to a shipped day show on its deep dive too
                from .shipped import corrections
                fixes = corrections(root, e["day"])
            except Exception:  # noqa: BLE001
                fixes = []
            fix_html = "".join(f'<p class="small muted"><b>Corrected {htmllib.escape(c["at"][:10])}:</b> '
                               f'{htmllib.escape(c["note"])}</p>' for c in fixes)
            body = (fix_html + _md_to_html(head) + f'<div id="listen">{player}</div>{nav}'
                    + (f'<section id="read" class="ddread">{_md_to_html(written)}</section>' if written else "")
                    + _md_to_html(_dd_sources(e["md"]))
                    + _share_box(dd_url, e["title"], "../../", cfg, "this deep dive"))
            (out / e["day"] / "deep-dive" / "index.html").write_text(
                _page(e["title"], body +
                      f'<p><a href="../index.html">That day\'s briefing</a> · <a href="../../index.html#deep-dives">All deep dives</a>'
                      f' · <a href="../../{DD_FEED}">🎧 Subscribe to the deep dives</a></p>', "../../", cfg), "utf-8")
            day_page = out / e["day"] / "index.html"
            if day_page.exists():
                html = day_page.read_text("utf-8")
                link = (f'<p class="small"><b>Deep dive today:</b> <a href="deep-dive/index.html">'
                        f'{htmllib.escape(e["title"].removeprefix("Deep dive: "))}</a></p>')
                day_page.write_text(html.replace('<div id="brief">', link + '<div id="brief">', 1), "utf-8")
            e["link"] = f"{base_url.rstrip('/')}/{e['day']}/deep-dive/" if base_url else f"{e['day']}/deep-dive/index.html"
            e["notes_html"] = _md_to_html(e["md"])
            if e["audio"] and not any(x.get("combined") and x["day"] == e["day"] for x in episodes):
                episodes.append(e)                       # a separate bonus episode only when not in the day's episode
                n_audio += 1
    except Exception:  # noqa: BLE001 - deep dives never break the site
        pass
    podcast_url = ""
    if episodes:
        podcast_url = "" if _is_staging() else build_podcast(root, cfg, out, episodes, base_url)
    dd_eps = [{**x, "type": "full", "guid": x.get("guid", "").replace("ai-briefing-", "ai-briefing-dd-", 1)}
              for x in dives if x.get("audio")]
    if dd_eps and not _is_staging():                 # the deep dives as their own podcast (v0.2.17)
        build_podcast(root, cfg, out, dd_eps, base_url, feed=DD_FEED, title=DD_TITLE, desc=DD_DESC,
                      cover="deepdive-cover.png")
    (out / "index.html").write_text(_page(cfg.get("podcast", {}).get("title", "AI Briefing"),
                                          landing(cfg, latest, rows, podcast_url, bool(episodes), base_url, dives),
                                          cfg=cfg, bare=True), "utf-8")
    (out / "releases").mkdir(exist_ok=True)
    (out / "releases" / "index.html").write_text(releases_page(cfg), "utf-8")
    try:                                         # <site>/docs/: the public documentation (pipeline/docs.py)
        from . import docs
        docs.build(root, cfg, out, _page)
    except Exception as e:  # noqa: BLE001 - docs never block a publish
        print(f"docs skipped: {e}"[:200])
    (out / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>AI Briefing</title>'
        f'<link>{base_url or "./"}</link><description>Daily AI briefing for early-stage investors</description>'
        + "".join(feed[:60]) + "</channel></rss>", "utf-8")
    return {"days": len(days), "audio": n_audio, "out": str(out), "podcast": podcast_url,
            "episode_keys": built_keys + [e["key"] for e in episodes if e.get("key", "").startswith("deepdive:")]}


def landing(cfg: dict, latest, rows: list, podcast_url: str, has_podcast: bool, base_url: str = "",
            dives: list | None = None) -> str:
    """The public front page, styled like Steven's public pages. No config UI."""
    sc = site_cfg(cfg)
    e = htmllib.escape
    title = cfg.get("podcast", {}).get("title", "AI Briefing")
    feed = podcast_url or "podcast.xml"
    apple = sc.get("apple_podcasts_url") or ""          # only once the show is listed in Apple's directory
    apple_label = "Listen on Apple Podcasts"
    acts = []
    if latest:
        acts.append(f'<a class="button primary" href="{latest["day"]}/index.html">Read today\'s briefing</a>')
        if latest["audio"]:
            acts.append('<a class="button" href="#latest">▶ Play the latest episode</a>')
    if has_podcast and apple:
        acts.append(f'<a class="button" href="{e(apple)}">{apple_label}</a>')
    if has_podcast:
        acts.append('<a class="button ghost" href="#listen">Add the podcast to your app</a>')
    if _script_url(cfg):
        acts.append('<a class="button" href="#email">✉ Subscribe by email</a>')
    if dives:
        acts.append('<a class="button" href="#deep-dives">🎧 Deep dives</a>')
    home = (base_url.rstrip("/") + "/") if base_url else ""
    acts.append(f'<a class="button ghost" href="{e(home or "#")}" data-share data-url="{e(home)}" '
                f'data-title="{e(title)}">Share the podcast</a>')
    H = ['<div class="shell">',
         '<section class="hero"><div class="heroTop"><span class="eyebrow">Daily AI briefing · podcast</span>'
         f'<a class="heroHomeLink" href="{e(sc["home_url"])}">{e(sc["home_label"])} ↗</a></div>'
         f'<h1>{e(title)}</h1><p class="lead">{e(sc["tagline"])}</p>'
         f'<p class="small muted">Curated by {e(sc["name"])}</p><div class="actions">{"".join(acts)}</div></section>']
    if latest:
        clean = [re.sub(r"\s*\[\d+\]\(https?://[^)]+\)", "", t) for t in latest["top"][:4]]
        tops = "".join("<li>" + _md_to_html(t)[3:-4] + "</li>" for t in clean)
        H.append('<section class="panel latest" id="latest"><h2>Latest episode</h2>'
                 f'<h3><a href="{latest["day"]}/index.html">{e(latest["title"])}</a></h3>'
                 + (f'<audio controls preload="metadata" src="audio/{latest.get("file") or latest["day"] + ".mp3"}"></audio>' if latest["audio"] else "")
                 + (f'<p>{e(latest["brief"])}</p>' if latest["brief"] else "")
                 + (f'<div class="k" style="margin-top:14px">Top of mind</div><ul>{tops}</ul>' if tops else "")
                 + f'<p><a class="button primary" href="{latest["day"]}/index.html">Read the full briefing</a></p>'
                 + _share_box(f"{base_url.rstrip('/')}/{latest['day']}/" if base_url else "", latest["title"], "", cfg,
                              "this episode" if latest["audio"] else "this briefing") + '</section>')
    if dives:
        cards = []
        for d in dives[:12]:
            day_label = dt.date.fromisoformat(d["day"]).strftime("%a %b %-d")
            cards.append(f'<div class="card dive"><div class="k">{e(day_label)} · deep dive{" · 🔊" if d.get("audio") else ""}</div>'
                         f'<h3><a href="{d["day"]}/deep-dive/index.html">{e(d["title"].removeprefix("Deep dive: "))}</a></h3>'
                         f'<p class="small muted">{e(_clip(re.sub(r"[*_]", "", d.get("summary") or ""), 220))}</p>'
                         f'<div class="actions">'
                         + (f'<a class="button primary" href="{d["day"]}/deep-dive/index.html#read">Read</a>' if d.get("written") else "")
                         + (f'<a class="button{"" if d.get("written") else " primary"}" href="{d["day"]}/deep-dive/index.html#listen">▶ Listen</a>'
                            if d.get("audio") else "")
                         + f'<a class="button ghost" href="{d["day"]}/index.html">That day\'s briefing</a></div></div>')
        H.append('<section class="panel" id="deep-dives"><h2>Deep dives</h2>'
                 '<p class="lead" style="margin-top:0"><i>One story, slowly. Down to the details.</i></p>'
                 '<p>About ten minutes on the one thing worth understanding properly that day: a breakthrough, a '
                 'controversy, a shift in the trajectory. Each one follows that morning\'s briefing in the podcast feed, '
                 'and they also have a podcast of their own.</p>'
                 f'<div class="actions" style="margin:0 0 12px"><a class="button primary" href="{DD_FEED}">'
                 '🎧 Subscribe to the deep dives</a><a class="button" href="podcast.xml">The daily show (briefing + deep dive)</a></div>'
                 f'<div class="grid">{"".join(cards)}</div></section>')
    links = "".join(f'<a class="button" href="{e(u)}" rel="noopener">{e(t)}</a>' for t, u in sc["links"])
    H.append('<section class="grid" style="margin-top:22px">'
             '<div class="panel" style="margin-top:0"><h2>Who makes it</h2><div class="bio">'
             f'<img src="{e(sc["photo"])}" alt="{e(sc["name"])}" loading="lazy">'
             f'<div><h3>{e(sc["name"])}</h3><p class="role">{e(sc["role"])}</p><p>{e(sc["bio"])}</p>'
             f'<p class="muted"><i>{e(sc["why"])}</i></p></div></div><div class="pills">{links}</div></div>'
             '<div class="panel" style="margin-top:0"><h2>What you get</h2>'
             f'<p>{e(sc["about"])}</p><div class="grid4 how">'
             '<div class="card"><b>Top of mind</b><span>the few things worth carrying into the day</span></div>'
             '<div class="card"><b>Must read</b><span>stories merged across sources, each with a critical read</span></div>'
             '<div class="card"><b>Open questions</b><span>what isn\'t settled yet, and what would settle it</span></div>'
             '<div class="card"><b>Audio episode</b><span>the same briefing, read for the commute</span></div></div></div></section>')
    script = ((cfg.get("email") or {}).get("script_url") or "")
    if script.startswith("https://script.google.com/"):
        H.append('<section class="panel" id="email"><h2>Get it by email</h2>'
                 '<p>One email each morning when the briefing is published. Confirm once; unsubscribe with one click.</p>'
                 + _subscribe_form(cfg) +
                 '<p class="small muted">Your address is kept in the briefing\'s own Google account, used only for this briefing, '
                 'and never shared.</p></section>')
    if has_podcast:
        H.append('<section class="panel" id="listen"><h2>Listen &amp; subscribe</h2>'
                 '<p>Add the show to any podcast app by pasting this feed address:</p>'
                 f'<div class="feedrow"><code id="feed">{e(feed)}</code><button type="button" onclick="navigator.clipboard&amp;&amp;'
                 'navigator.clipboard.writeText(document.getElementById(\'feed\').innerText);this.innerText=\'Copied\'">Copy feed URL</button></div>'
                 '<div class="grid4 how" style="margin-top:14px">'
                 '<div class="card"><b>Apple Podcasts</b><span>Library → ··· (top right) → Follow a Show by URL → paste</span></div>'
                 '<div class="card"><b>Overcast</b><span>+ (top right) → Add URL → paste</span></div>'
                 '<div class="card"><b>Pocket Casts</b><span>Search → paste the feed URL</span></div>'
                 '<div class="card"><b>Other apps</b><span>look for “Add by URL” or “Add RSS feed”</span></div></div>'
                 '<div class="actions" style="margin-top:14px">'
                 + (f'<a class="button primary" href="{e(apple)}">{apple_label}</a>' if apple else "")
                 + f'<a class="button" href="{e(feed)}">Open the feed</a><a class="button ghost" href="feed.xml">Text-only RSS</a></div>'
                 '<p class="small muted">Episodes are written and read by AI from public sources; every claim links to its source in the written briefing.</p></section>')
    H.append('<section class="panel"><h2>Archive</h2>' + ("".join(rows) or '<p class="muted">No briefings yet.</p>') + '</section>')
    H.append("</div>")
    return "".join(H)


def _duration(mp3: Path) -> str:
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                           capture_output=True, text=True, timeout=20)
        s = int(float(r.stdout.strip()))
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    except Exception:  # noqa: BLE001
        return ""


def _show_notes(md: str) -> str:
    """Episode notes: day in brief, Top of mind and Must-read headlines, with source links."""
    keep = []
    for sec in re.split(r"(?m)^(?=## )", md):
        if sec.startswith("## Must read"):
            heads = re.findall(r"(?m)^### (.+)$\n\*\*(.+?)\*\*.*?\[source\]\((https?://[^)]+)\)", sec)
            keep.append("## Must read\n\n" + "\n".join(f"- [{h}]({u}) ({w})" for h, w, u in heads))
        elif sec.startswith("## Top of mind") or sec.startswith("# "):
            keep.append(sec.strip())
    return _md_to_html("\n\n".join(keep))


DD_FEED = "deepdive.xml"
DD_TITLE = "AI Briefing: Deep Dive"
DD_DESC = ("One story, slowly. Down to the details. The AI Briefing's deep dive on its own: about ten minutes on the one thing worth understanding properly "
           "that day (a breakthrough, a controversy, a shift in the trajectory), for early-stage investors. Written "
           "and read by AI from public sources, curated by Steven Woods; every claim links to its source.")


def build_podcast(root: Path, cfg: dict, out: Path, episodes: list, base_url: str, feed: str = "podcast.xml",
                  title: str = "", desc: str = "", cover: str = "podcast-cover.png") -> str:
    """An RSS feed podcast apps understand (iTunes tags, artwork, durations, show notes, as-published transcripts).
    podcast.xml is the daily show; deepdive.xml (v0.2.17) is the deep dives on their own."""
    pc = cfg.get("podcast", {})
    base = base_url.rstrip("/")
    cover_src = root / "assets" / cover
    if not cover_src.exists():
        cover, cover_src = "podcast-cover.png", root / "assets" / "podcast-cover.png"
    if cover_src.exists():
        shutil.copy2(cover_src, out / cover)
    title = title or pc.get("title", "AI Briefing")
    author = pc.get("author", "Steven")
    desc = desc or pc.get("description", "Slowly, then fast. Every morning. A daily AI briefing for early-stage investors: what happened, a critical read "
                                 "of the claims, and what it means for diligence. Written and read by AI from public "
                                 "sources, curated by Steven Woods; every claim links to its source in the written briefing.")
    ai_note = "This episode is AI-generated: written and voiced by AI from public sources."
    items = []
    for e in episodes:
        mp3 = e["mp3"]
        d = dt.datetime.fromisoformat(e["day"] + "T" + e.get("time", "06:45:00")).astimezone()
        brief = re.search(r"\*\*The day in brief\.\*\* (.+)", e["md"])
        summary = re.sub(r"\[(\d+)\]\(https?://[^)]+\)", "", e.get("summary") or (brief.group(1) if brief else e["title"])).replace("**", "")
        notes = (f"<p><i>{ai_note}</i></p>" + (e.get("notes_html") or _show_notes(e["md"]))
                 + (f'<p><a href="{base}/{e["day"]}/">Full briefing with every source</a></p>' if not e.get("notes_html") else "")
                 + (f'<p><b>Then the deep dive</b> (second part of this episode): '
                    f'<a href="{base}/{e["day"]}/deep-dive/">{htmllib.escape(e["title"].split("with deep dive: ", 1)[-1])}</a>'
                    f' · <a href="{base}/">All episodes and deep dives</a></p>' if e.get("combined") else "")
                 + f'<p><b>Share this episode:</b> <a href="{e.get("link") or base + "/" + e["day"] + "/"}">'
                   f'{e.get("link") or base + "/" + e["day"] + "/"}</a>'
                 + (f' · <a href="{base}/#email">Get the briefing by email</a>' if _script_url(cfg) else "")
                 + (f' · <a href="{base}/{e["day"]}/#rate">Rate it</a>' if (cfg.get("email") or {}).get("ratings") else "")
                 + "</p>")
        page_link = e.get("link") or f"{base}/{e['day']}/"
        dur = _duration(mp3)
        items.append(
            f"<item><title>{htmllib.escape(e['title'])}</title>"
            f"<guid isPermaLink=\"false\">{e.get('guid') or 'ai-briefing-' + e['day']}</guid><pubDate>{format_datetime(d)}</pubDate>"
            f"<link>{page_link}</link>"
            f"<description>{htmllib.escape(summary + ' ' + ai_note)}</description>"
            f"<content:encoded><![CDATA[{notes}]]></content:encoded>"
            f"<itunes:summary>{htmllib.escape(summary + ' ' + ai_note)}</itunes:summary>"
            f'<enclosure url="{base}/audio/{e.get("file") or e["day"] + ".mp3"}" length="{mp3.stat().st_size}" type="audio/mpeg"/>'
            + (f"<itunes:duration>{dur}</itunes:duration>" if dur else "")
            + (f'<podcast:transcript url="{base}/audio/{e["vtt"]}" type="text/vtt"/>' if e.get("vtt") else "")
            + f"<itunes:episodeType>{e.get('type', 'full')}</itunes:episodeType><itunes:explicit>false</itunes:explicit></item>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
           'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
           'xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel>'
           f"<title>{htmllib.escape(title)}</title><link>{base}/</link><language>en</language>"
           f"<description>{htmllib.escape(desc)}</description><itunes:summary>{htmllib.escape(desc)}</itunes:summary>"
           f"<itunes:author>{htmllib.escape(author)}</itunes:author>"
           f'<itunes:image href="{base}/{cover}"/><image><url>{base}/{cover}</url>'
           f"<title>{htmllib.escape(title)}</title><link>{base}/</link></image>"
           '<itunes:category text="Technology"/><itunes:category text="Business"><itunes:category text="Investing"/>'
           "</itunes:category><itunes:explicit>false</itunes:explicit><itunes:type>episodic</itunes:type>"
           + "".join(items) + "</channel></rss>")
    (out / feed).write_text(xml, "utf-8")
    return f"{base}/{feed}"
