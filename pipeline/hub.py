"""Status for Steven's public project hub (sgwoods.github.io/public), per its PUBLIC_STATUS_INTERFACE (schema 1.0).

This project is a standalone project in the hub's terms: it owns exactly two files there,
`data/projects/ai-briefing.json` (the canonical status manifest) and `ai-briefing.html` (its top-level page).
It never edits the hub's index.html, other projects' files, ordering or wording.

The pipeline's own repo is private, so the hub cannot read it. Both files are therefore:
  - written to hub/ in this repo (committed, the source of truth), and
  - published with the site at <site_url>/hub/, where the hub session or its refresh tool picks them up.
Public facts only: no subscriber counts, addresses, sources lists, private names or settings.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path

PROJECT_ID = "ai-briefing"
KEYS = ("schema_version", "project_id", "active", "display_name", "description", "project_page_path", "repo_url",
        "dashboard_url", "experience_url", "repo_pushed_at", "status_generated_at", "status_label", "status_value",
        "focus_label", "focus_value")
DEFAULT_FOCUS = "Beta: aggressive fact checking before email and audio, wider source coverage; podcast listing after four green weeks."
DESCRIPTION = ("A daily AI briefing for investors and builders, written and voiced each morning with a "
               "skeptical, evidence-weighted read, plus occasional deep dives.")


def _utc(t: dt.datetime | None = None) -> str:
    t = t or dt.datetime.now(dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def latest(root: Path) -> dict:
    days = sorted(p.stem for p in (root / "briefings").glob("????-??-??.md"))
    day = days[-1] if days else ""
    dives = sorted(p.stem for p in (root / "briefings" / "deepdives").glob("????-??-??.md"))
    return {"day": day, "editions": len(days), "deep_dive": day if day and day in dives else "",
            "deep_dives": len(dives)}


def manifest(root: Path, cfg: dict, now: dt.datetime | None = None, pushed_at: str = "") -> dict:
    pc, hc = cfg.get("publish") or {}, cfg.get("hub") or {}
    site = (pc.get("site_url") or "").rstrip("/") + "/"
    repo = pc.get("repo") or ""
    lt = latest(root)
    value = f"Edition {lt['day']}" + (" + deep dive" if lt["deep_dive"] else "") if lt["day"] else "Not yet published"
    stamp = _utc(now)
    m = {
        "schema_version": "1.0",
        "project_id": PROJECT_ID,
        "active": bool(hc.get("active", True)),
        "display_name": hc.get("display_name", "AI Briefing"),
        "description": hc.get("description", DESCRIPTION),
        "project_page_path": f"{PROJECT_ID}.html",
        "repo_url": f"https://github.com/{repo}" if repo else None,
        "dashboard_url": None,                       # the builder dashboard is local-only (127.0.0.1)
        "experience_url": site if pc.get("site_url") else None,
        "repo_pushed_at": pushed_at or stamp,
        "status_generated_at": stamp,
        "status_label": "Latest edition",
        "status_value": value,
        "focus_label": "Current focus",
        "focus_value": hc.get("focus", DEFAULT_FOCUS),
    }
    assert tuple(m) == KEYS
    return m


def dumps(m: dict) -> str:
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"


def page(m: dict, cfg: dict, root: Path) -> str:
    site = m["experience_url"] or ""
    lt = latest(root)
    e = html.escape
    links = [("Read today's edition", site), ("Podcast feed", site + "podcast.xml" if site else ""),
             ("Get it by email", site + "#subscribe" if site else ""), ("Published site repository", m["repo_url"] or "")]
    btns = "\n".join(f'      <a class="button" href="{e(u)}">{e(t)}</a>' for t, u in links if u)
    day_link = f'{site}{lt["day"]}/index.html' if site and lt["day"] else site
    dive = (f'<li>Deep dive the same day: <a href="{e(site)}{e(lt["deep_dive"])}/deep-dive/index.html">read or listen</a></li>'
            if lt["deep_dive"] and site else "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(m['display_name'])} | Steven Woods Projects</title>
  <link rel="stylesheet" href="assets/public-site.css">
</head>
<body>
<main class="shell shell--narrow">
  <header class="hero">
    <div class="heroTop">
      <span class="eyebrow">Public project</span>
      <a class="heroHomeLink" href="https://sgwoods.github.io/public/index.html">Steven Woods</a>
    </div>
    <h1>{e(m['display_name'])}</h1>
    <p>{e(m['description'])}</p>
    <div class="buttonRow">
{btns}
    </div>
  </header>

  <section class="panel">
    <h2>{e(m['status_label'])}</h2>
    <ul>
      <li><a href="{e(day_link)}">{e(m['status_value'])}</a> · {lt['editions']} editions and {lt['deep_dives']} deep dives published</li>
      {dive}
      <li>Status generated {e(m['status_generated_at'])} by the project's own pipeline; site last published {e(m['repo_pushed_at'])}</li>
    </ul>
  </section>

  <section class="panel">
    <h2>How it is made</h2>
    <div class="grid">
      <div class="card"><h3>Curated sources</h3><p>Lab and company posts, trade press, researchers and newsletters, every feed verified live before it is used.</p></div>
      <div class="card"><h3>Evidence first</h3><p>Each story is weighed by what kind of source backs it; every Must read gets an evidence check, and figures that trace to no source are looked up or cut before anything is sent.</p></div>
      <div class="card"><h3>Local first</h3><p>Runs each morning on a Mac with local models for most stages and Claude for the critical pass and editing; voiced locally.</p></div>
      <div class="card"><h3>Release gate</h3><p>Nothing goes out (site, podcast, email) unless tests, a secrets scan, privacy checks and a human approval of sensitive changes have passed.</p></div>
    </div>
  </section>

  <section class="panel">
    <h2>{e(m['focus_label'])}</h2>
    <p>{e(m['focus_value'])}</p>
    <p>This page and <code>data/projects/{PROJECT_ID}.json</code> are written by the project (hub status interface, schema 1.0); the source repository is private.</p>
  </section>
</main>
</body>
</html>
"""


def write(root: Path, cfg: dict, site_dir: Path | None = None, pushed_at: str = "") -> dict:
    """Write hub/data/projects/ai-briefing.json + hub/ai-briefing.html (and copies under site_dir/hub/)."""
    m = manifest(root, cfg, pushed_at=pushed_at)
    out = {"manifest": dumps(m), "page": page(m, cfg, root)}
    targets = [root / "hub"] + ([site_dir / "hub"] if site_dir else [])
    for base in targets:
        (base / "data" / "projects").mkdir(parents=True, exist_ok=True)
        (base / "data" / "projects" / f"{PROJECT_ID}.json").write_text(out["manifest"], "utf-8")
        (base / f"{PROJECT_ID}.html").write_text(out["page"], "utf-8")
    return m
