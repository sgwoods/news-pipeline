# Changelog

Releases of the AI Briefing pipeline. Versions are `0.MINOR.PATCH` while in beta: a MINOR release adds features,
a PATCH release fixes problems. Changes are built and tested on a development branch and reach production
together as a release (docs/plans/release-process.md).

## Unreleased

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
