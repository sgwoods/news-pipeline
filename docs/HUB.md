# Public project hub (sgwoods.github.io/public)

Steven's hub lists his projects from per-project status manifests (hub repo `sgwoods/public`, rules in its
`PUBLIC_STATUS_INTERFACE.md`, `PUBLIC-OPERATING-MODEL.md`, `PROJECT-STATUS-CONTRACT.md`). This project is a
**standalone project** there, id `ai-briefing`.

## What this project owns in the hub (and nothing else)
- `data/projects/ai-briefing.json`: status manifest, schema 1.0, exactly these keys in this order:
  `schema_version, project_id, active, display_name, description, project_page_path, repo_url, dashboard_url,
  experience_url, repo_pushed_at, status_generated_at, status_label, status_value, focus_label, focus_value`
  (two-space indent, UTF-8, trailing newline, ISO 8601 UTC times, `null` for missing URLs).
- `ai-briefing.html`: the top-level project page (hub style: `assets/public-site.css`, `shell shell--narrow`,
  `hero`/`heroTop`/`eyebrow`/`heroHomeLink` → the hub index, `panel` sections).

Never edit the hub's `index.html`, other projects' files, card order, homepage wording or the shared
"Repository work last updated" line. Portfolio judgment (priority, energy/value/horizon, next step, drift)
lives in the hub's `PROJECT-SUITE-OVERVIEW.md` and is the hub session's to write.

## How the files are produced and handed over
`pipeline/hub.py` writes both on every publish (`./np publish` and the daily run):
- `hub/data/projects/ai-briefing.json` and `hub/ai-briefing.html` in this repo (committed with the archive), and
- the same two files on the public site: https://sgwoods.github.io/ai-briefing/hub/data/projects/ai-briefing.json
  and https://sgwoods.github.io/ai-briefing/hub/ai-briefing.html

This repo is private and lives on the MacBook; the hub clone is not on this machine. So the hub session (or
its refresh tool) copies the two published files into `data/projects/` and the hub root, then runs
`python3 tools/refresh_public_coordination.py`. Commit message there: "Update public status manifest for ai-briefing".

Status values: `status_label` "Latest edition", `status_value` "Edition YYYY-MM-DD (+ deep dive)",
`repo_pushed_at` = the publish time, `focus_value` from `hub.focus` in config.yaml (Steven edits it).
Overrides: `hub.display_name`, `hub.description`, `hub.active`.

Public facts only: no subscriber counts, addresses, source lists, private names, board seats or settings.
The site privacy scan (`publish.scan_site`) checks these files like every other published page.
