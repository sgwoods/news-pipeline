# news-pipeline

Steven's daily AI news briefing: a written edition, a ~10-minute podcast episode, occasional deep dives, a public
site (https://sgwoods.github.io/ai-briefing/) and a subscriber email. Spec and decisions: `PLAN.md`. Lens: `perspective.md`.
Rules for Claude: `CLAUDE.md`.

## Setup (once, in Terminal on the Mac)
```
cd ~/Developer/news-pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
LLM backend defaults to a local model behind an OpenAI-compatible server (Ollama or LM Studio); set `llm.local.model` in `config.yaml`.
Claude is optional per stage: `claude_code` uses `claude -p` on your subscription (keep `ANTHROPIC_API_KEY` unset); `claude_api` uses a key in `.env`.

## Shortcuts (use these)
`./np help` lists them. Each one saves full output to `logs/cmd-<name>-<time>.txt` and ends with a short
report saved to `logs/last-report.md`, which Claude reads straight from this folder. If Claude can't
reach the Mac, paste the block between `===== REPORT =====` and `===== END REPORT =====`.

| | |
|---|---|
| `./np setup` | create/refresh the venv and install requirements |
| `./np doctor` | check Python, packages, Ollama + model, sources, git |
| `./np run` | full daily run |
| `./np test [N]` | analyze N pending items (default 10) |
| `./np analyze` | analyze all pending items |
| `./np reprocess DAY` | re-analyze a day (adds new versions) |
| `./np fetch` / `./np verify` | fetch only / re-verify sources |
| `./np daily` | once-a-day run + Mac notification (what the schedule calls) |
| `./np schedule install` | schedule `./np daily` at 06:30 with a 07:30 retry; also `status`, `test`, `remove` |
| `./np site` / `./np publish setup` / `./np publish` | build the public site locally / create the public GitHub repo (once) / build + push to GitHub Pages |
| `./np tests` / `./np report` / `./np dash` | unit tests / reprint last report / dashboard |
| `./np quality [DAY]` / `./np review weekly` | scorecard / weekly quality review |
| `./np factcheck [DAY]` | fact-check dry run: figures traced, searched before cutting (docs/FACT-CHECKING.md) |
| `./np email …` / `./np note …` | subscribers, sends, catch-up / your private evening note (docs/EMAIL-SETUP.md) |
| `./np deepdive [DAY]` | topical deep dive episode (docs/DEEP-DIVES.md) |
| `./np watchlist …` | companies you track (private) |
| `./np release-check [approve "…"]` | the release gate; approvals are Steven's only (docs/security/RELEASE.md) |

`./np help` has the full list.

## The daily run (05:00, retries 06:30 and 07:30)
fetch (feeds, sitemaps, Bluesky, newsletters, Slack, watchlist) → filter → summarize/rank → cluster → critique →
**verify** (every Must read gets an evidence check; thin items have their article read) → editorial → write →
**fact check** (figures traced, searched, cut or flagged) → number check → deep dive (if planned) → audio →
publish (site, podcast, hub status) → email → archive commit and private backup push. Every outbound step
passes the release gate first; anything held back is retried once the gate passes.

## Docs
- `docs/OPERATIONS.md` services, schedule, backup, moving to the iMac
- `docs/FACT-CHECKING.md` what is checked before anything goes out
- `docs/SOURCE-PROFILES.md` weighing evidence by kind of source
- `docs/DEEP-DIVES.md` the second episode
- `docs/EMAIL-SETUP.md`, `docs/FEEDBACK.md`, `docs/NEWSLETTERS.md`, `docs/SLACK.md`, `docs/LINKEDIN.md`
- `docs/HUB.md` status for the public project hub (sgwoods.github.io/public)
- `docs/security/` release gate, Gmail isolation, account migration, security reviews
- `docs/reviews/` editorial, quality, format, architecture and source-gap reviews

## Commands (what the shortcuts call)
- `python run.py --verify-sources`: check every feed and write `sources.yaml` + `logs/source-verification-<date>.md`
- `python -m unittest discover -s tests`: run tests
- `python run.py`: daily run: fetch → filter → rank/tag → critical pass → write `briefings/<day>.md`. Commits the archive.
- `python run.py --stages-only [--limit 10]`: analyze pending items without fetching (good for trying a model)
- `python run.py --reprocess 2026-10-05`: re-analyze a day's items (adds new versions; nothing overwritten)
- `python run.py --no-llm`: fetch + archive only
- `python run.py --lookback-hours 168`: back-fill the last week (first run)
- `python run.py --no-commit`: run without committing

## Archive (append-only, committed)
- `data/raw/YYYY-MM-DD/items.jsonl`: every new item: id, url, person, source, published, full text
- `data/index.jsonl`: one line per item ever seen
- `data/runs.jsonl`: one line per run, per-stage status and per-source results
- `data/state/`: page-source baselines (URLs already seen)
- `data/summaries/<day>.jsonl`: per-item analysis (filter decision, claim / so-what / agenda, tag, importance,
  critical pass) with source URL, model and prompt version; re-runs append new versions
- `data/briefings.jsonl` + `briefings/versions/`: every briefing ever written and which items it used

## Local model (Ollama)
```
ollama pull qwen3:30b      # ~19 GB; or qwen3:14b (~9 GB) if memory is tight
```
Set `llm.local.model` in `config.yaml`. To send one stage to Claude instead, e.g. the critical pass:
`llm.stages: {critique: claude_code}`. Prompts live in `pipeline/prompts/*.md`; editing one changes its
version hash, so old and new analyses stay distinguishable.

## Running it as a service
See `docs/OPERATIONS.md`: `./np service install` (daily run + always-on dashboard), Control page at http://127.0.0.1:8765/control, `./np backup setup` for the private GitHub backup, and how to move to the iMac.

## Where to read the briefing
- Dashboard: `./np dash`, then http://127.0.0.1:8765/briefings: every day with its Top of mind, item count, audio player (once Phase 2 lands) and all versions; http://127.0.0.1:8765/briefings/latest jumps to the newest
- Terminal: `./np read [DAY]` (default latest), `./np listen [DAY]` for the MP3, `./np open` opens the latest in the browser
- File: `briefings/YYYY-MM-DD.md` (any Markdown viewer; earlier versions in `briefings/versions/`)

## Audio (Phase 2)
One-time: `brew install python@3.12 ffmpeg espeak-ng`, then `./np setup --rebuild` (Kokoro needs Python 3.10+).
`./np voices` makes a sample per candidate voice (listen at http://127.0.0.1:8765/voices); set `audio.voice` in
`config.yaml`. Every run then writes `briefings/<day>.script.md` + `briefings/<day>.mp3` and copies the MP3 to the
iCloud Drive folder "News Briefings". `./np audio [DAY]` rebuilds one day's audio.

## Commentary and publishing
- Write your take under any section of a briefing in the dashboard; it autosaves to `data/commentary/<day>.json` (every save also logged).
- Mail-out draft: `/briefings/<day>/mailout` (Top of mind + the stories you commented on).
- Public site: `./np publish` builds `site/` (briefings + your notes + last 14 days of MP3s + RSS) and force-pushes it to the
  separate public repo in `config.yaml` (`publish.repo`). This repo is never published: `data/` holds full article text.

## Where to edit
- `perspective.md`: who and what you care about
- `source_hints.yaml`: extra feed URLs / Bluesky handles per person
- `sources_managed.yaml`: sources added outside perspective.md (Sources page, `./np sources`, or by hand), verified by `./np verify`
- `source_profiles.yaml`: what kind of evidence each source is
- `watchlist.yaml`, `conflicts.yaml`: tracked companies and private conflict context (never public)
- `config.yaml`: backend, model, lookback window, briefing size
- `pipeline/prompts/*.md`: the instructions each LLM stage gets (your lens itself stays in `perspective.md`)
