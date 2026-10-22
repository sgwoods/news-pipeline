# Operations: services, restarts, backup, moving to the iMac

## What runs where
| Piece | How it runs | Managed by |
|---|---|---|
| Daily run (fetch → briefing → fact check → deep dive → audio → publish → email) | launchd agent `com.sgwoods.news-pipeline`, at `schedule.times` (05:00, retries 06:30, 07:30) | `./np service … daily` |
| Evening preflight (is the release approval current? notifies if not) | launchd agent `com.sgwoods.news-pipeline.preflight`, at `schedule.preflight` (20:30) | `./np service … preflight` |
| Dashboard (http://127.0.0.1:8765) | launchd agent `com.sgwoods.news-pipeline.dashboard`, always on, restarts on crash | `./np service … dashboard` |
| Local model | Ollama, `brew services start ollama` | `./np service restart ollama` |
| Critical pass, clustering, editorial | Claude Code (`claude -p`) on your subscription | — |
| Public site + podcast feed (+ hub status files under /hub/, docs/HUB.md) | GitHub Pages, repo `publish.repo` (public, single commit) | `./np publish` |
| Subscriber email + your evening note | Apps Script "AI Briefing mailer" in briefing@example.com (docs/security/MIGRATION-stevenwoods-ai.md) | `./np email …`, `./np note …` |
| Private backup of this repo (code + full archive) | GitHub, repo `archive.remote_repo` (private) | `./np backup` |

Everything is also on the dashboard's **Control** page (http://127.0.0.1:8765/control).

## Commands
```
./np service install            # write + load both launchd agents for THIS checkout
./np service status             # services, Ollama, Claude Code
./np service restart dashboard  # after code changes to the dashboard
./np service run daily          # run the scheduled job now, same environment as 06:30
./np service pause daily        # stop the schedule (keeps the plist); resume daily to restart
./np service restart ollama
./np service remove             # unload + delete both agents
```
Tuning and exploring (same as the dashboard Tuning / Threads / Questions pages):
```
./np preview 2026-10-07 calm-10min   # rebuild that day with a profile into briefings/experiments/ (~3-6 min)
./np dive 2026-10-07 2               # deep dive on story 2 of that briefing -> briefings/dives/
```
Profiles are `profiles/<name>.yaml`; the daily run uses `tuning.profile` in config.yaml ("Make it the daily profile" on the Tuning page).

Sources (same as the dashboard Sources page):
```
./np suggest [N]                  # refresh the queue with N new suggestions (default 10, ~2-6 min, Claude + web search)
./np sources                      # list pending / accepted / watch / denied
./np sources find "Name" [note]   # search one person's feeds and queue the result
./np sources accept ID | deny ID [why] | reconsider ID | recheck ID
./np sources remove URL [why] | restore URL
```
Quality and checks:
```
./np quality [DAY|all]            scorecard (targets, ratings); ./np quality pull fetches star ratings
./np review weekly                weekly review against the house rules and benchmarks (The AI Daily Brief, The Batch)
./np factcheck [DAY]              fact-check dry run (docs/FACT-CHECKING.md)
./np verify                       re-verify every source; failures are listed, never silently dropped
```
Email timing: after publishing, the run waits until GitHub Pages serves today's page (and deep dive) before emailing,
checking every 10 seconds for up to `publish.wait_live_seconds` (300); after that the email goes anyway.

When something needs you: an "Action needed: AI Briefing …" email (to email.test_to) says what happened and which
commands to run: a pending approval (evening check or morning), a failed release-gate check, a run with no briefing,
a failed publish or email. One email per issue per day; the Mac notification still shows too. The Mac being off or asleep all
morning is caught from outside: the "AI Briefing watchdog" (a Claude scheduled task in the cloud, daily 08:24
Toronto) checks the public site for today's edition (hub/data/projects/ai-briefing.json and today's page) and, if it
is missing, emails you@example.com with what to do. It only reads the public site; it changes nothing.

Logs: `logs/launchd.*.log` (daily), `logs/dashboard.*.log`, `logs/run-*.log`, `logs/last-report.md`.

## One-time setup on a Mac
```
brew install python@3.12 ffmpeg espeak-ng ollama gh
brew services start ollama && ollama pull qwen3:30b
git clone https://github.com/sgwoods/news-pipeline.git ~/Developer/news-pipeline   # NOT under ~/Documents (see below)
cd ~/Developer/news-pipeline && ./np setup --rebuild && ./np doctor
claude --version                 # Claude Code installed + logged in; ANTHROPIC_API_KEY unset
gh auth login
./np service install
```
**Keep the project outside ~/Documents, ~/Desktop, ~/Downloads and iCloud Drive.** macOS privacy protection (TCC)
blocks launchd background jobs from those folders ("Operation not permitted", exit 126) unless you give /bin/bash
Full Disk Access, which would apply to every bash script. Use `~/Developer/news-pipeline` (~/Developer is the standard macOS home for projects; Finder gives it its own icon). The iCloud copy of the MP3
is optional for the same reason; the podcast feed doesn't need it.

## Moving from the MacBook to the iMac (planned once the pipeline is stable)
1. MacBook: `./np backup` (push everything), then `./np service remove`.
2. iMac: the one-time setup above (clone from the private backup repo).
3. iMac: secrets are in the MacBook's Keychain, not in git: `./np secrets set NAME` for each one `./np secrets status`
   lists (Gmail app password for stevenwoods.ai, EMAIL_SCRIPT_KEY, Slack token). Good moment to rotate the email key:
   `./np email key new`, then paste it as the SECRET script property.
4. iMac: `./np release-check` then approve, `./np service install`, then `./np service run daily` to test.
Only one machine should have the services installed, or both will publish and email.
