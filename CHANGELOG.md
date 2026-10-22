# Changelog

Releases of the AI Briefing pipeline. Versions are `0.MINOR.PATCH` while in beta: a MINOR release adds features,
a PATCH release fixes problems. Changes are built and tested on a development branch and reach production
together as a release (docs/plans/release-process.md).

## Unreleased

## v0.1.7-beta · 2026-10-22
Shipped editions don't break. Once a day's email has gone out, that day is shipped (`pipeline/shipped.py`), and:
- **Publish guard:** before every production publish, the new site is checked against what readers already have.
  It refuses (the live site is untouched and the owner is emailed) if any of these hold:
  - a shipped day page or deep dive is missing;
  - a shipped edition's text changed without a correction;
  - a shipped MP3 inside the retention window is missing;
  - the home page or a feed is missing, or the podcast feed would shrink.
- **Corrections are explicit:** rebuilding a shipped day (`rebrief`, `reprocess`, `remaster`) needs
  `--correct "what changed"`, and the page shows "Corrected <date>: …".
- **Remasters keep the old audio:** the earlier MP3 is carried over from the live site, so no audio URL breaks.
- **After-publish check:** once the site is live, the newest shipped pages, both feeds and the latest MP3 must
  answer. If not, the previous site is put back automatically, the email is held, and the owner is emailed.
  `./np publish restore` does the same by hand.
- **The email waits for a good publish:** if the publish fails or the after-publish check fails, no subscriber
  email goes out. Before, it went anyway.
- **Audio retention:** 30 days on the site and in the podcast feed, up from 14. 60 days would be about 1 GB, the
  GitHub Pages limit.
- **Slack:** links any member posts in the team channel now count, links only. Who posted is never stored, and
  their text is never used.
- **Staging preview:** carries only the newest day's audio. The first full preview push timed out.
- **Site pushes are sturdier:** a push that stalls (under 1 KB/s for 60 s) fails and is retried once over
  HTTP/1.1, instead of hanging the morning run. Pushes no longer use one huge buffered upload, which is what
  GitHub was timing out with HTTP 408.

## v0.1.6-beta · 2026-10-22
- Development preview: `./np staging publish [setup]` publishes the dev checkout's site to its own Pages repo
  (sgwoods/ai-briefing-staging). The preview has a banner on every page linking back to the published site, is
  kept out of search engines (noindex, robots.txt), and has no subscribe form and no podcast feed. Staging can
  publish only there, and production never publishes there.
- `./np staging compare [DAY]`: staging against production for the same day: sections, counts, words, source
  links, the evidence mix, fact-check counts and audio length, plus the privacy scan of the preview and a diff of
  the edition. Writes `logs/compare-DAY.md` and flags what needs review.
- Fix: a staging run no longer copies its MP3 into the owner's iCloud folder. The first staging run had
  overwritten that day's copy. It no longer deletes iCloud files either.
- Tests always run as production (`NP_ENV=production`), in either checkout.

## v0.1.5-beta · 2026-10-22
- Fix: the scheduled jobs had been firing exactly one hour early every day (the 05:00 run started at 04:00, the
  20:30 preflight at 19:30). launchd now only ticks every half hour, and the Mac's own local clock decides when a
  scheduled time has come (`pipeline/schedule.py`, `./np scheduled`). Times must be on :00 or :30.
- Releases refuse checkout-local files (`.venv`, `.env`, `.staging`) committed on dev; `.venv` is ignored as a
  link too.
- Fix: rebuilding an edition (`./np rebrief`, `./np staging run`) failed with KeyError 'critique', because the
  evidence check on Must reads needs the critique model, and a rebuild had stopped loading it. Found by the
  first staging run.
- Git safety: every git call in the export, hub, dev and release code ignores GIT_DIR / GIT_WORK_TREE from the
  environment, and the tests that build throwaway repositories clear them. A leaked GIT_DIR once pointed a test's
  `git init` at the production repository and wrote a wrong `core.worktree` into its config. Caught and fixed
  before any run used it.
- The first release built on dev and promoted with `./np release`.

## v0.1.4-beta · 2026-10-22
- Development checkout: `./np dev setup` creates a second working copy of the repository on branch `dev`, in
  staging mode. Inside it:
  - `./np staging sync` brings in production's latest data and fixes;
  - `./np staging run [DAY]` rebuilds an edition with the development code while outbound stays off, and
    `--email` sends the review copy to the owner only;
  - `./np staging reset` throws away what staging wrote.
- Staging outputs can't be committed: the pre-commit hook refuses data paths in a staging checkout, archive
  commits are skipped there, alerts aren't sent, and services can't be installed. Staging runs keep out of the
  03:30–08:30 production window.
- Releases and rollback:
  - `./np release VERSION "reviewed: ..."` merges dev into production between 08:30 and 20:00, needs one
    approval, then tags the release and pushes the public code, the backup and the hub status. It refuses if
    production has stray code changes, a run is in progress, dev's version or changelog don't match, or the
    staging marker was committed.
  - `./np rollback "reviewed: ..."` returns the code to the previous release.

## v0.1.3-beta · 2026-10-22
- Documentation on the site at `/docs/`, rebuilt at every publish from the same markdown as the public code, with
  the diagrams embedded. Each page shows the running version and when it last changed. Linked from the footer and
  the hub page.
- Generated sections in the architecture document: current facts and a component table built from each module's
  own description. Drift tests fail a release if the document names a module that no longer exists, or doesn't
  name the current version.
- Release check: the tests line shows unittest's own summary.

## v0.1.2-beta · 2026-10-22
- Staging mode: a development checkout (marked by an untracked `.staging` file) can build everything but can't
  reach readers. The release gate refuses every outbound action there. The mailer allows only reads and review
  copies to the owner, marked [STAGING]. A new release-gate invariant keeps every outbound function behind the gate.
- The hub project page shows the latest release notes and links to the architecture document.
- Architecture document with four diagrams: system overview, the daily run, repositories and privacy boundaries,
  and the release flow (`docs/ARCHITECTURE.md`).

## v0.1.1-beta · 2026-10-22
- AI Briefing on the public project hub (sgwoods.github.io/public) as an exporting project: after each publish,
  `./np hub push` writes its status (19 fields, naming this released public commit) and its project page with the
  hub's freshness panel, and pushes only those two files. It refuses when the running code isn't the release.
- The site's old `/hub/` copy of the status files is retired.
- `./np log <command>` saves any command's output under `logs/`.

## v0.1.0-beta · 2026-10-22
The system as it runs today, labelled the first beta: a small number of outside readers.

- Daily edition: fetch from feeds, sitemaps, Bluesky lists, newsletters and Slack links; filter, summarize, rank,
  cluster into stories, critique, verify and fact-check; Top of mind, Must read, Worth knowing, Open questions.
- Evidence-weighted sources: every source has a profile, and a Must read needs primary or reporting evidence.
- Podcast: a ~10-minute episode read by the host, followed in the same episode by the day's deep dive.
- Public site, podcast feed and RSS on GitHub Pages; a subscriber email sent after the site is live.
- Release gate on every outbound step: tests, secret scan, privacy invariants and Steven's approval of
  security-sensitive changes; owner alerts when action is needed; a cloud watchdog for missing editions.
- Reader feedback collected from email replies and triaged daily.
- Public code repository: an allowlisted, scrubbed export (`./np push-code`), MIT licence.
