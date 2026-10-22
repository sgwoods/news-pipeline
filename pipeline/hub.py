"""AI Briefing on Steven's public project hub (sgwoods.github.io/public): an exporting project.

Contract: sgwoods/public AI-BRIEFING-EXPORT.md, PUBLIC_STATUS_INTERFACE.md, PROJECT-STATUS-CONTRACT.md.
This project owns exactly two hub files and writes nothing else there:
  data/projects/ai-briefing.json   schema 1.0: the 15 base fields, then source_commit, source_commit_at,
                                   source_ref, source_dirty
  ai-briefing.html                 its page: hub stylesheet, shell/hero/panel, the freshness panel

The source identity is the RELEASED PUBLIC code: the version tag (VERSION -> v0.1.0-beta) in the public code repo
(config.yaml code_repo, local copy .public/). Export refuses, explicitly, when:
  - the tag is missing locally or on GitHub, or GitHub's tag points elsewhere;
  - the code running here differs from that tag (a change not yet released through ./np push-code).

    ./np hub status     # the two files it would write, and whether the source resolves (writes nothing)
    ./np hub push       # after a publish: write both files into .hub/ (a clone of sgwoods/public) and push
                        # only those two paths, commit message "Update public status manifest for ai-briefing"

The daily publish calls push(); a failure is reported and never blocks the briefing.
Public facts only: no subscriber counts, addresses, source lists, private names, settings or local URLs.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import subprocess
import tempfile
from pathlib import Path

PROJECT_ID = "ai-briefing"
HUB_REPO = "sgwoods/public"
HUB_DIR = ".hub"
ALLOW = (f"data/projects/{PROJECT_ID}.json", f"{PROJECT_ID}.html")
MESSAGE = f"Update public status manifest for {PROJECT_ID}"
BASE_KEYS = ("schema_version", "project_id", "active", "display_name", "description", "project_page_path", "repo_url",
             "dashboard_url", "experience_url", "repo_pushed_at", "status_generated_at", "status_label",
             "status_value", "focus_label", "focus_value")
SOURCE_KEYS = ("source_commit", "source_commit_at", "source_ref", "source_dirty")
KEYS = BASE_KEYS + SOURCE_KEYS
CODE_PATHS = ("pipeline", "dashboard", "scripts", "tests", "run.py", "np", "requirements.txt")   # what "running" means
DEFAULT_FOCUS = "Beta: dependable daily delivery, editorial accuracy, and acting on reader feedback."
DESCRIPTION = ("A daily AI briefing, newsletter and podcast for early-stage investors: what happened, what holds up, "
               "and what it means, with occasional deep dives.")


class HubExportError(RuntimeError):
    pass


def _utc(t: dt.datetime | None = None) -> str:
    t = t or dt.datetime.now(dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(cwd: Path, *a, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise HubExportError(f"git {' '.join(a[:3])} failed in {cwd.name}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def latest(root: Path) -> dict:
    days = sorted(p.stem for p in (root / "briefings").glob("????-??-??.md"))
    day = days[-1] if days else ""
    dives = sorted(p.stem for p in (root / "briefings" / "deepdives").glob("????-??-??.md"))
    return {"day": day, "editions": len(days), "deep_dive": day if day and day in dives else "",
            "deep_dives": len(dives)}


# ---------- the released public source ----------

def running_matches(root: Path, public: Path, ref: str) -> bool:
    """Is the code running here the code at REF in the public repo? A fresh export, compared file by file with
    REF's tree on the code paths only (docs and generated example files may move on without a release).
    Read-only: REF is read with git archive; nothing is written to either repository."""
    import io
    import tarfile
    from . import export
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "x"
        export.build(root, log=lambda *_: None, out=out)
        r = subprocess.run(["git", "archive", "--format=tar", ref, "--", *CODE_PATHS], cwd=public, capture_output=True)
        if r.returncode:
            raise HubExportError(f"cannot read {ref} in the public export: {r.stderr.decode()[:200]}")
        released = {m.name: tarfile.open(fileobj=io.BytesIO(r.stdout)).extractfile(m).read()
                    for m in tarfile.open(fileobj=io.BytesIO(r.stdout)).getmembers() if m.isfile()}
        running = {}
        for top in CODE_PATHS:
            p = out / top
            for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()) if p.exists() else []):
                if "__pycache__" not in f.parts:
                    running[str(f.relative_to(out))] = f.read_bytes()
        return running == released


def source(root: Path, cfg: dict, remote_check: bool = True) -> dict:
    """{source_commit, source_commit_at, source_ref, source_dirty} for the running release, or HubExportError."""
    from .version import tag
    ref = tag(root)
    public = root / ".public"
    repo = cfg.get("code_repo") or ""
    if not repo:
        raise HubExportError("code_repo is not set in config.yaml")
    if ref == "vdev":
        raise HubExportError("no VERSION file: nothing has been released")
    if not (public / ".git").exists():
        raise HubExportError("no public export yet (.public/): run ./np push-code approve first")
    r = _git(public, "rev-parse", "-q", "--verify", f"refs/tags/{ref}^{{commit}}", check=False)
    sha = r.stdout.strip()
    if r.returncode or len(sha) != 40:
        raise HubExportError(f"tag {ref} is not in the public export: release it with ./np push-code approve")
    if remote_check:
        ls = _git(public, "ls-remote", "--tags", f"https://github.com/{repo}.git", f"refs/tags/{ref}^{{}}",
                  f"refs/tags/{ref}", check=False)
        remote = {ln.split("\t")[1]: ln.split("\t")[0] for ln in ls.stdout.splitlines() if "\t" in ln}
        rsha = remote.get(f"refs/tags/{ref}^{{}}") or remote.get(f"refs/tags/{ref}")
        if ls.returncode or not rsha:
            raise HubExportError(f"tag {ref} is not on github.com/{repo}: push it (./np push-code approve)")
        if rsha != sha:
            raise HubExportError(f"tag {ref} on GitHub is {rsha[:12]}, the local export says {sha[:12]}")
    if not running_matches(root, public, ref):
        raise HubExportError(f"the code running here is not {ref}: release the change first (./np push-code approve), "
                             "so the hub never shows a release that isn't what runs")
    at = _git(public, "show", "-s", "--format=%cI", sha).stdout.strip()
    return {"source_commit": sha, "source_commit_at": _utc(dt.datetime.fromisoformat(at)), "source_ref": ref,
            "source_dirty": False}


# ---------- the two files ----------

def manifest(root: Path, cfg: dict, src: dict, now: dt.datetime | None = None) -> dict:
    pc, hc = cfg.get("publish") or {}, cfg.get("hub") or {}
    site = (pc.get("site_url") or "").rstrip("/") + "/" if pc.get("site_url") else None
    lt = latest(root)
    edition = (f" · edition {lt['day']}" + (" + deep dive" if lt["deep_dive"] else "")) if lt["day"] else ""
    m = {
        "schema_version": "1.0",
        "project_id": PROJECT_ID,
        "active": bool(hc.get("active", True)),
        "display_name": hc.get("display_name", "AI Briefing"),
        "description": hc.get("description", DESCRIPTION),
        "project_page_path": f"{PROJECT_ID}.html",
        "repo_url": f"https://github.com/{cfg['code_repo']}",
        "dashboard_url": None,                       # the operations dashboard is local-only and stays private
        "experience_url": site,
        "repo_pushed_at": src["source_commit_at"],   # = source_commit_at, by contract (not the publish time)
        "status_generated_at": _utc(now),
        "status_label": "Current release",
        "status_value": src["source_ref"] + edition,
        "focus_label": "Current focus",
        "focus_value": hc.get("focus", DEFAULT_FOCUS),
        **{k: src[k] for k in SOURCE_KEYS},
    }
    assert tuple(m) == KEYS
    return m


def dumps(m: dict) -> str:
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"


def page(m: dict, cfg: dict, root: Path) -> str:
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    site = m["experience_url"] or ""
    lt = latest(root)
    links = [("Read today's edition", f"{site}{lt['day']}/index.html" if site and lt["day"] else site),
             ("Podcast feed", site + "podcast.xml" if site else ""),
             ("Get it by email", site + "#email" if site else ""),
             ("Release notes", site + "releases/index.html" if site else ""),
             ("Public code", m["repo_url"])]
    btns = "\n".join(f'      <a class="button" href="{e(u)}">{e(t)}</a>' for t, u in links if u)
    dive = (f'\n      <li>Deep dive the same day: <a href="{e(site)}{e(lt["deep_dive"])}/deep-dive/index.html">read or '
            f'listen</a></li>' if lt["deep_dive"] and site else "")
    sha = m["source_commit"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(m['display_name'])} | Steven Woods Projects</title>
  <link rel="stylesheet" href="assets/public-site.css">
  <script src="assets/project-freshness.js" defer></script>
</head>
<body>
<main class="shell shell--narrow">
  <header class="hero">
    <div class="heroTop">
      <span class="eyebrow">Public project</span>
      <a class="heroHomeLink" href="index.html">Steven Woods</a>
    </div>
    <h1>{e(m['display_name'])}</h1>
    <p>{e(m['description'])}</p>
    <div class="links">
{btns}
    </div>
  </header>

  <section class="panel">
    <h2>{e(m['status_label'])}</h2>
    <ul>
      <li><b>{e(m['source_ref'])}</b>, public code commit <code>{e(sha[:12])}</code> ({e(m['source_commit_at'])})</li>
      <li>Latest edition: {e(lt['day'] or 'none yet')} · {lt['editions']} editions and {lt['deep_dives']} deep dives published</li>{dive}
      <li>Status exported {e(m['status_generated_at'])} by the project's own pipeline</li>
    </ul>
  </section>

  <section class="panel">
    <h2>How it is made</h2>
    <div class="grid">
      <div class="card"><h3>Curated sources</h3><p>Lab and company posts, trade press, researchers and newsletters, every feed verified live before it is used.</p></div>
      <div class="card"><h3>Evidence first</h3><p>Each story is weighed by what kind of source backs it; every Must read gets an evidence check, and figures that trace to no source are looked up or cut before anything is sent.</p></div>
      <div class="card"><h3>Local first</h3><p>Runs each morning with local models for most stages and Claude for the critical pass and editing; voiced locally.</p></div>
      <div class="card"><h3>Release gate</h3><p>Nothing goes out (site, podcast, email) unless tests, a secrets scan, privacy checks and a human approval of sensitive changes have passed. Changes reach production as releases.</p></div>
    </div>
  </section>

  <section class="panel">
    <h2>{e(m['focus_label'])}</h2>
    <p>{e(m['focus_value'])}</p>
  </section>

  <section class="panel" id="repository-freshness"
           data-project-freshness="{e(PROJECT_ID)}"
           data-source-commit="{e(sha)}"
           data-source-dirty="false" aria-live="polite">
    <h2>Repository freshness</h2>
    <p>See <a href="index.html#repository-activity">the latest hub observation</a>.
       A current repository comparison has not yet been loaded.</p>
  </section>
</main>
</body>
</html>
"""


def build(root: Path, cfg: dict, remote_check: bool = True) -> dict:
    src = source(root, cfg, remote_check=remote_check)
    m = manifest(root, cfg, src)
    files = {ALLOW[0]: dumps(m), ALLOW[1]: page(m, cfg, root)}
    from . import export
    from .owner import get as owner
    with tempfile.TemporaryDirectory() as tmp:          # the same privacy scan as the public code export
        for rel, txt in files.items():
            (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp) / rel).write_text(txt, "utf-8")
        hits = export.scan(Path(tmp), export.private_terms(root, owner(root)) + ["127.0.0.1", "localhost"])
    if hits:
        raise HubExportError("private terms in the hub files: " + "; ".join(hits[:5]))
    for rel, txt in files.items():                      # kept here too, as the record of what was exported
        p = root / "hub" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, "utf-8")
    return {"manifest": m, "files": files}


def _same(a: str, b: str) -> bool:
    """Equal apart from status_generated_at (and the page's export line): no commit for a no-op."""
    import re
    strip = lambda s: re.sub(r'("status_generated_at": ")[^"]*"|Status exported \S+', "", s)  # noqa: E731
    return strip(a) == strip(b)


def push(root: Path, cfg: dict, log=print, retries: int = 3) -> str:
    """Write the two files into the hub clone and push only them (no force; reconcile with main and retry)."""
    from .release import require
    require(root, cfg, "hub push")
    hub = root / HUB_DIR
    if not (hub / ".git").exists():
        raise HubExportError(f"no hub clone at {HUB_DIR}/: git clone --depth 1 --filter=blob:none --sparse "
                             f"https://github.com/{HUB_REPO}.git {HUB_DIR}")
    b = build(root, cfg)
    for attempt in range(retries):
        if _git(hub, "status", "--porcelain", "--untracked-files=no").stdout.strip():
            raise HubExportError(f"{HUB_DIR}/ has local changes: it must be a clean hub checkout")
        _git(hub, "fetch", "-q", "origin", "main")
        _git(hub, "checkout", "-q", "main")
        _git(hub, "reset", "-q", "--hard", "origin/main")   # our own clone: always start from current hub main
        changed = False
        for rel, txt in b["files"].items():
            p = hub / rel
            old = p.read_text("utf-8") if p.exists() else ""
            if not _same(old, txt):
                changed = True
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, "utf-8")
        if not changed:
            _git(hub, "checkout", "-q", "--", *[r for r in ALLOW if (hub / r).exists()], check=False)
            _git(hub, "reset", "-q", "--hard", "origin/main")
            return "hub: already current (nothing to push)"
        _git(hub, "add", "--", *ALLOW)
        staged = [s for s in _git(hub, "diff", "--cached", "--name-only").stdout.split("\n") if s]
        bad = [s for s in staged if s not in ALLOW]
        if bad:
            _git(hub, "reset", "-q", "--hard", "origin/main")
            raise HubExportError(f"refusing: staged paths outside the allowlist: {bad}")
        from .owner import get as owner
        o = owner(root)
        name, mail = o.get("public_git_name") or "AI Briefing", o.get("public_git_email") or "noreply@example.com"
        _git(hub, "-c", f"user.name={name}", "-c", f"user.email={mail}", "commit", "-q", "-m", MESSAGE)
        r = _git(hub, "push", "-q", "origin", "HEAD:main", check=False)
        if r.returncode == 0:
            sha = _git(hub, "rev-parse", "HEAD").stdout.strip()
            log(f"hub: pushed {sha[:12]} ({b['manifest']['status_value']}; source {b['manifest']['source_commit'][:12]})")
            return sha
        log(f"hub: push rejected (attempt {attempt + 1}), reconciling with hub main and retrying")
    raise HubExportError("hub push kept being rejected; nothing forced")
