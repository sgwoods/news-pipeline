# news-pipeline

The code behind **AI Briefing**: a daily AI briefing for early-stage investors and builders. Each morning it writes
an edition, records a ~10-minute podcast episode, sometimes adds a deep dive, publishes a static site and podcast
feed, and emails subscribers.

- Live site and podcast: https://sgwoods.github.io/ai-briefing/
- Project page: https://sgwoods.github.io/public/ai-briefing.html
- Status: **v0.1 beta**. A small number of outside readers; see `CHANGELOG.md` once releases begin.

This repository is the code only. The working instance's content, its sources, the people it follows, the editor's
perspective, subscribers and the archive live in a separate private repository. They are never published here
(see "What is not here").

## What it does
fetch → filter → summarize and rank → cluster into stories → critique → verify → editorial → write → fact check →
deep dive → audio → publish → email

- **Sources:** RSS and sitemaps, Bluesky lists, newsletters read from a Gmail label (read-only IMAP), Slack links,
  and a company watchlist with GDELT and Google News search.
- **Weighing evidence:** every source has a profile (primary, reporting, analysis, opinion, aggregator, social), so
  "five sources" becomes "1 primary + 1 report + 3 commentaries". A Must read needs primary or reporting evidence.
  See `docs/SOURCE-PROFILES.md`.
- **Fact checking:** figures are traced to their source, searched before they are cut, and flagged when they can't
  be confirmed. See `docs/FACT-CHECKING.md`.
- **Local first:** the default models run locally behind an OpenAI-compatible server (Ollama or LM Studio). Claude
  is optional per stage. Audio is Kokoro TTS.
- **Release gate:** every outbound step (site, email, podcast, backups) first passes tests, a secret scan,
  privacy invariants and a human approval of security-sensitive changes. See `docs/security/RELEASE.md`.

## Run it yourself
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp owner.example.yaml owner.yaml                    # who runs this instance (keep it private)
cp source_profiles.example.yaml source_profiles.yaml
./np tests                                           # unit tests
./np help                                            # every command
```
You also need a `config.yaml` (models, schedule, site), a `sources.yaml` and a `perspective.md` (your lens: the
people, topics and scepticism that steer the briefing). `.env.example` lists the secrets, which go in `.env` and
are never committed.

## What is not here
The instance's private files: `owner.yaml`, `config.yaml`, `perspective.md`, `author*.md`, the source and newsletter
lists, the watchlist and conflict lists, subscriber data, reader feedback, and the archive of fetched articles. The
public copy is built from the private repository by an allowlisted export that strips private blocks, replaces
personal details with placeholders, scans for anything private and runs the tests before anything is pushed.

## Licence
MIT. See `LICENSE`.
