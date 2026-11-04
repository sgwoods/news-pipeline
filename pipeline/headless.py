"""A local headless browser as the last try for a page the plain fetch couldn't read (Steven, 2026-11-04).

The 11-04 trial (scripts/headless_trial.py) over 24 links the deep dives had dropped as dead: 10 were fine on a
plain retry, 5 more opened in headless Chrome (bot checks, pages that need JavaScript), 9 stayed blocked (paywalls,
Cloudflare walls), which we leave alone.

Rules: only when the site's robots.txt allows our user agent; only public hosts (pipeline/netguard.py); the system
Chrome (or Chromium, Edge, Brave) in headless mode with a throwaway profile, so none of Steven's sign-ins or cookies;
its own user agent, nothing disguised; a capped number of pages per run. A page that comes back as a "verify you are
human" screen counts as a failure. Off with fetch.headless: false.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
BLOCK_PAGE = re.compile(r"just a moment|verify you are human|access denied|enable javascript and cookies|"
                        r"are you a robot|captcha|request blocked|attention required", re.I)
GOOD = 1500
_used = [0]
_robots: dict = {}


def hcfg(cfg: dict) -> dict:
    f = (cfg.get("fetch") or {})
    return {"enabled": f.get("headless", True), "max_pages": int(f.get("headless_max_pages", 12)),
            "user_agent": f.get("user_agent", "news-pipeline/0.1")}


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    return shutil.which("chromium") or shutil.which("google-chrome") or ""


def robots_ok(url: str, ua: str, get=None) -> bool:
    p = urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            if get is None:
                from .netguard import client
                with client(timeout=10, follow_redirects=True, headers={"User-Agent": ua}) as c:
                    r = c.get(base + "/robots.txt")
                    status, text = r.status_code, r.text
            else:
                status, text = get(base + "/robots.txt")
            rp.parse(text.splitlines() if status == 200 else [])
        except Exception:  # noqa: BLE001 - unreachable robots.txt: no rules
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(ua, url) and _robots[base].can_fetch("*", url)


def usable(html: str) -> bool:
    from .textutil import html_to_text
    text = html_to_text(html or "")
    if BLOCK_PAGE.search(text[:3000]) and len(text) < 4000:
        return False
    return len(text) >= GOOD


def fetch(url: str, cfg: dict, run=subprocess.run, get=None) -> str:
    """The rendered page's HTML, or '' (off, no browser, cap reached, robots.txt says no, non-public, a wall)."""
    import os
    from .netguard import _host_ok
    c = hcfg(cfg)
    if os.environ.get("NP_TESTING") and run is subprocess.run:     # tests never start a real browser
        return ""
    if not c["enabled"] or _used[0] >= c["max_pages"] or not url.startswith(("https://", "http://")):
        return ""
    exe = browser() if run is subprocess.run else "chrome"
    if not exe or not _host_ok(urlsplit(url).hostname or "") or not robots_ok(url, c["user_agent"], get):
        return ""
    _used[0] += 1
    with tempfile.TemporaryDirectory() as prof:
        try:
            out = run([exe, "--headless=new", "--disable-gpu", "--no-first-run", "--mute-audio",
                       f"--user-data-dir={prof}", "--virtual-time-budget=10000", "--timeout=25000",
                       "--dump-dom", url], capture_output=True, text=True, timeout=45)
            html = out.stdout or ""
        except (subprocess.TimeoutExpired, OSError):
            return ""
    return html if usable(html) else ""


def reset() -> None:
    _used[0] = 0
    _robots.clear()
