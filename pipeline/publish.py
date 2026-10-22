"""Push the static site (site/) to a separate public GitHub repo served by GitHub Pages.

Keeps the public repo to a single commit (force-push), so old MP3s don't accumulate there.
The full history stays in this private working repo.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _run(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def setup(root: Path, repo: str) -> str:
    if not shutil.which("gh"):
        raise RuntimeError("GitHub CLI not found. Install it: brew install gh, then run: gh auth login")
    if _run(["gh", "auth", "status"], check=False).returncode != 0:
        raise RuntimeError("Not logged in to GitHub. Run: gh auth login")
    _run(["gh", "auth", "setup-git"], check=False)
    if _run(["gh", "repo", "view", repo], check=False).returncode != 0:
        _run(["gh", "repo", "create", repo, "--public", "--description",
              "Daily AI briefing for early-stage investors (machine analysis + Steven's take)"])
        msg = f"created public repo {repo}"
    else:
        msg = f"repo {repo} already exists"
    return msg


def scan_site(root: Path, site: Path) -> list:
    """Everything about to go public, checked: private names, Steven's addresses, tracker/account links,
    and files that must never be published. -> problems (empty = clean)."""
    import re as _re
    from . import stages
    from .links import _MDLINK, personal, personal_addresses
    names = stages.private_names()
    problems = []
    href = _re.compile(r'(?:href|src)="(https?://[^"]+)"')
    for p in site.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(site))
        if p.suffix.lower() in (".env", ".pem", ".key") or p.name in ("author-private.md", "feedback.json", "watchlist.yaml"):
            problems.append(f"{rel}: file must never be published")
            continue
        if p.suffix.lower() not in (".html", ".xml", ".txt", ".md", ".json", ".js", ".css"):
            continue
        t = p.read_text("utf-8", errors="replace")
        low = t.lower()
        for n in names:
            if _re.search(r"\b" + _re.escape(n) + r"\b", t):
                problems.append(f"{rel}: private name")
                break
        from .links import DISCLOSURE_FLAG
        if p.suffix.lower() in (".html", ".xml", ".txt", ".md") and DISCLOSURE_FLAG.search(t):
            problems.append(f"{rel}: board-seat / conflict disclosure (never public)")
        for a in personal_addresses({}):
            if "@" in a and a in low:
                problems.append(f"{rel}: Steven's address")
                break
        for u in href.findall(t) + [u for _, u in _MDLINK.findall(t)]:
            if personal(u.replace("&amp;", "&"), {}):
                problems.append(f"{rel}: personal/tracker link {u[:60]}")
                break
    return problems


def push(root: Path, site: Path, repo: str, message: str, cfg: dict | None = None) -> str:
    from .release import require
    require(root, cfg or {}, "site publish")
    bad = scan_site(root, site)
    if bad:
        raise RuntimeError("privacy scan of the site failed, nothing published: " + "; ".join(bad[:8]))
    pub = root / ".publish"
    if not (pub / ".git").exists():
        pub.mkdir(exist_ok=True)
        _run(["git", "init", "-q", "-b", "main"], cwd=pub)
        _run(["git", "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=pub)
    for p in pub.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for p in site.iterdir():
        dest = pub / p.name
        shutil.copytree(p, dest) if p.is_dir() else shutil.copy2(p, dest)
    _run(["git", "checkout", "-q", "--orphan", "publish-tmp"], cwd=pub)
    _run(["git", "add", "-A"], cwd=pub)
    from .owner import get as owner
    o = owner()
    _run(["git", "-c", f"user.name={o['name']}", "-c", f"user.email={o['account'] or 'briefing@localhost'}",
          "commit", "-q", "-m", message], cwd=pub)
    _run(["git", "branch", "-D", "main"], cwd=pub, check=False)
    _run(["git", "branch", "-m", "main"], cwd=pub)
    _run(["git", "config", "http.postBuffer", "524288000"], cwd=pub, check=False)   # MP3s: big pushes
    try:
        _run(["git", "push", "-q", "-f", "origin", "main"], cwd=pub)
    except Exception:  # noqa: BLE001 - GitHub sometimes times out a large push (HTTP 408): one retry
        import time
        time.sleep(30)
        _run(["git", "push", "-q", "-f", "origin", "main"], cwd=pub)
    # Enable Pages once (ignored if already on).
    if shutil.which("gh"):
        _run(["gh", "api", "-X", "POST", f"repos/{repo}/pages", "-f", "source[branch]=main", "-f", "source[path]=/"],
             check=False)
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


# ---------- private backup of this working repo ----------

def backup_setup(root: Path, repo: str) -> str:
    """Create a PRIVATE GitHub repo for this checkout (code + archive) and push to it."""
    if not shutil.which("gh"):
        raise RuntimeError("GitHub CLI not found. Install it: brew install gh, then run: gh auth login")
    if _run(["gh", "auth", "status"], check=False).returncode != 0:
        raise RuntimeError("Not logged in to GitHub. Run: gh auth login")
    _run(["gh", "auth", "setup-git"], check=False)
    view = _run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"], check=False)
    if view.returncode == 0 and view.stdout.strip().upper() != "PRIVATE":
        raise RuntimeError(f"{repo} exists and is {view.stdout.strip()}: refusing to push the archive (full article text) to it")
    if view.returncode != 0:
        _run(["gh", "repo", "create", repo, "--private", "--description", "news-pipeline working repo (private)"])
    remotes = _run(["git", "remote"], cwd=root).stdout.split()
    url = f"https://github.com/{repo}.git"
    _run(["git", "remote", "set-url" if "origin" in remotes else "add", "origin", url], cwd=root)
    _run(["git", "push", "-q", "-u", "origin", "main"], cwd=root)
    return f"private backup ready: {repo} (pushed main)"


def backup_push(root: Path, cfg: dict | None = None) -> str:
    from .release import require
    require(root, cfg or {}, "backup push")
    if "origin" not in _run(["git", "remote"], cwd=root).stdout.split():
        raise RuntimeError("no 'origin' remote yet: run ./np backup setup")
    url = _run(["git", "remote", "get-url", "origin"], cwd=root).stdout.strip()
    repo = url.removeprefix("https://github.com/").removesuffix(".git")
    view = _run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"], check=False) \
        if shutil.which("gh") else None
    if not view or view.returncode != 0 or view.stdout.strip().upper() != "PRIVATE":
        raise RuntimeError(f"refusing to push: could not confirm {repo} is PRIVATE (the archive, reader replies and the "
                           "private people list are in this repo)")
    _run(["git", "push", "-q", "origin", "main"], cwd=root)
    return "pushed to origin"


# ---------- wait for GitHub Pages before emailing ----------

def wait_live(cfg: dict, day: str, timeout: int = 300, every: int = 10, log=print, client=None, sleep=None) -> bool:
    """After a push, GitHub Pages takes a few seconds to minutes to serve the new pages. Poll today's page (and its
    deep dive, if there is one) until both answer with today's content, so the email's links work when it lands
    (Steven, 2026-10-19). -> True when live; False after `timeout` seconds (the email then goes anyway)."""
    import time
    site = ((cfg.get("publish") or {}).get("site_url") or "").rstrip("/")
    if not site or not day:
        return True
    sleep = sleep or time.sleep
    urls = [f"{site}/{day}/index.html"]
    from pathlib import Path as _P
    if (_P(__file__).resolve().parent.parent / "briefings" / "deepdives" / f"{day}.md").exists():
        urls.append(f"{site}/{day}/deep-dive/index.html")
    if client is None:
        from .netguard import client as guarded
        client = guarded(follow_redirects=True, timeout=15, headers={"Cache-Control": "no-cache"})
    waited, pending = 0, list(urls)
    while True:
        still = []
        for u in pending:
            try:
                r = client.get(f"{u}?v={int(time.time())}")
                if not (r.status_code == 200 and day in r.text):
                    still.append(u)
            except Exception:  # noqa: BLE001
                still.append(u)
        pending = still
        if not pending:
            log(f"Site live after {waited}s: {', '.join(urls)}")
            return True
        if waited >= timeout:
            log(f"Site not live after {waited}s ({', '.join(pending)}); sending anyway")
            return False
        sleep(every)
        waited += every
