# Topical deep dives

A separate episode of about ten minutes (`deepdive.minutes` 10, up to `max_minutes` 13 when an important story needs
the context), also published as a readable article on its own page (site: `<day>/deep-dive/`, and the front page's
Deep dives section), after the daily briefing, on the day's focal point: a
breakthrough and its controversy, a concept suddenly everywhere (the "third scaling law": scaling compute
at inference time), a change in the trajectory of the field, or a story that has matured over several days.

- **Who decides:** Claude picks the topic from today's briefing, the past week and recent deep dives, and may
  say there is none today. One a day (`deepdive.max_per_week` 7, since 2026-10-19), no repeat within 21 days unless something
  material is new. `./np deepdive --topic "..."` sets the topic yourself.
- **How it is written:** an explainer for the ear, in six parts: why today → the idea plainly → what is
  established vs claimed → how the AGI-forward / AI-realist / market / policy readings differ (only where the
  facts allow) → our read and one diligence question → what would settle it. Claude may search the web for
  the paper, the lab's post and the strongest critique.
- **Checks before it airs:** every source link is opened (dead ones dropped; fewer than 2 live → no episode);
  quotation marks survive only around words found in the archived or fetched text; sentences with a $ or %
  figure found in no source are cut; private names are removed; markup or banned words fail the episode.
  The summary and "Why today" lines are then checked against the finished body (`pipeline/consistency.py`, since
  v0.1.9): a sentence whose figure, company or "not disclosed" claim the body doesn't support is dropped. See
  docs/FACT-CHECKING.md.
- **No story twice (v0.2.5):** when the deep dive covers one of the day's Must reads, the briefing keeps that story
  to a sentence and a pointer to the deep dive, in the written edition, the email and the podcast.
- **In the podcast (2026-10-19):** the deep dive follows the briefing in the same episode. The briefing host
  ("I'm Michael" in the first line) closes by promoting today's deep dive and where to find it (the web page, with
  the written edition and every past episode), hands off to Bella, and the deep dive's sign-off closes the episode.
  The feed carries one file per day (`briefings/<day>.podcast.mp3`, "… · with deep dive: <title>"); the web page
  keeps separate players for the briefing and the deep dive. If the briefing audio was made without the hand-off
  (a deep dive made later by hand), the deep dive stays a separate bonus episode.
- **Where it goes:** briefings/deepdives/<day>.md (show notes + sources), .script.md, .mp3. The podcast feed
  lists it as a bonus episode "Deep dive: <title>" right after that day's briefing; the day's page links to it.
- **Its own podcast (v0.2.17):** the deep dives also have a feed of their own, `deepdive.xml` ("AI Briefing: Deep
  Dive", with its own cover). The daily show keeps the deep dive after the briefing, through the host's hand-off.
  The site's Deep dives section, each deep-dive page and the email link to the deep-dive feed.
- **When:** planned during the morning run before the briefing audio (so the briefing hands off to it), written and voiced right after, then published and mentioned in the email.
- **Picking from the evening note:** your private note (sent by the daily run after the subscriber email) gives every
  topic its own buttons: tomorrow's (Add your take, Move down, Dismiss), the rest of Up next (Make next, ↑, ↓, Add your
  take, Dismiss), each new suggestion (Make next, Add to Up next, Add your take, Dismiss), and "Suggest as a deep dive"
  on today's deep dive and each watchlist mention. Each button opens the private queue page with that one change ready
  to confirm (an email link never changes anything by itself); the page has the same buttons and a take box on every
  topic (signed owner links, 8-day expiry).
- **Your take on a deep dive (v0.2.11):** type it on the queue page or on the dashboard's Deep dives page, any time
  before the run that writes it. It is read verbatim as "Steven's take" at the end of the deep dive (its own section
  on the site and in the podcast), after the same privacy check as morning takes; a take that fails it is held back
  and stays private. Takes are opinion: never rewritten by a model, outside the fact check.
- **Queue:** dashboard /deep-dives: Claude adds up to 4 suggestions each morning; queue, reorder, dismiss or add your own. Up next goes first; otherwise the day's best (strength 4+). One a day; Up next is never left empty (the best suggestion is moved up if you queued nothing).
- **Voices:** briefing am_michael ("Michael", ~131 words a minute), deep dive af_bella ("Bella", ~157), changeable on
  the Tuning page. Script length is set from each voice's measured speed (`audio.voice_wpm`).
