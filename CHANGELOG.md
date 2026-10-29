# Changelog

Releases of the AI Briefing pipeline. Versions are `0.MINOR.PATCH` while in beta: a MINOR release adds features,
a PATCH release fixes problems. Changes are built and tested on a development branch and reach production
together as a release (docs/plans/release-process.md).


## Unreleased

## v0.2.31-beta · 2026-10-29
- **The advance deep dive** (Steven, 10-29): at 15:30 (schedule.advance) tomorrow's deep dive is written and
  checked and saved to Drive as "<day> · Deep dive · <title> (draft)", with a nudge and an email. The Doc ends with
  two sections: "Steven's take" (read verbatim after the episode) and "Notes for the editor" (what to change). The
  05:00 run reads them back: the take goes in; notes make the writer revise the draft, which is checked again;
  then it is voiced and shipped. Install the agent once with the `service-install` job (kind: advance).
  `./np advance` drafts now; run-queue job `advance`. The Schedule page has the row.

## v0.2.30-beta · 2026-10-29
- **Schedule page** (Steven, 10-29): the dashboard's new Schedule tab (and `./np schedule`) lists what is produced
  through the day, when, where it goes, and the window for feedback on each piece and how it is picked up.
- **The review page keeps your takes** (Steven, 10-29: a page of typed takes was lost by tapping a source link).
  Every link on the page opens in a new tab; each box is kept in the browser as you type and sent to the mail
  script a few seconds after you stop (a later save for the same box replaces the earlier one); leaving the page
  with unsent text asks first. Submit and Done work as before.
- **Pronunciations** (Steven, 10-29): the table gains outlets and acronyms said by name (NYT is "New York Times",
  WSJ, FT, GAAP as "gap", METR as "meter", S-1 as "S one", PBC and LTBT spelled out) and more people and
  companies (Qwen is now "Kwen", Nvidia, Pichai, Nadella, Dwarkesh, Azeem Azhar, Stratechery, Zhipu, Mistral).
  Uncertain ones carry a comment. `./np pronounce lint [DAYS]` lists what the voice may have garbled lately, for
  the next additions (docs/OPERATIONS.md).
- Fix: takes edited in the Drive Doc before the edition ships were not read, because the Doc is still the draft
  then ("held for your takes"); the draft is read when the published one isn't there yet.

## v0.2.29-beta · 2026-10-28
- **Readers suggest deep dives** (Steven, 10-28): a "Suggest a deep dive" link in the email's deep-dive section (with
  the reader's own token) and on every deep-dive page on the site. The page asks for a topic, why now, and an
  optional name. Suggestions land in the queue as "suggested by <name>" (else "a reader") and show that way in
  the evening note, on the queue page and in the dashboard; when one runs, the deep dive's notes say who suggested
  it. Addresses stay in the private queue file. Capped per reader and per day. Needs the mail-script deploy (the
  ship does it).

## v0.2.28-beta · 2026-10-28
- **The deep dive in the thread** (Steven, 10-28): right after the morning post, a reply in its thread with the deep
  dive: title, summary, Steven's take on it and the links, with its own card in the deep-dive cover's colours.
  `./np slack-post deepdive DAY`; run-queue job `slack-deepdive` (chat). Card text now ends at a full sentence or
  an ellipsis, never mid-sentence.

## v0.2.27-beta · 2026-10-28
- **The morning Slack post** (Steven, 10-28): when the email goes out, one post in cto-musings from the bot user
  "AI Briefing": the day's three leads, one of Steven's published takes (his words, the one with the most bite that
  fits), the deep dive and the links, with the day's card attached: a 1600×900 image in the newsletter's teal with
  the masthead, photo, leads, the take and the deep-dive band (`pipeline/card.py`, Pillow + Inter, new in
  requirements). Set up once with the `slack-setup` job (a Mac dialog takes the bot token; scopes chat:write,
  files:write, channels:read; invite the bot to the channel). `./np slack-post preview DAY` shows the text and
  renders the card; run-queue jobs `slack-card` (auto) and `slack-post` (chat). Security: a new outbound step,
  gated like the others; never in staging; bot posts are ignored by the Slack reader.
- Fix: the Drive check re-queued a takes-sync every 20 minutes after a plain re-publish (the Docs weren't rewritten,
  so nothing recorded our own last write). A take the commentary already has is never an edit, and takes-sync now
  rewrites the Docs.
- **Podcast artwork refresh**: podcast apps cache artwork by URL and never refetch it (Apple still showed the old
  cover a day after the new one went up), so the feeds now name a copy whose filename carries the image's hash.
  Apple Podcasts picks up the new covers at its next feed check.

## v0.2.26-beta · 2026-10-28
- Fix: the runner's minute tick exited before the Drive check when the queue was empty, so edited takes were never
  noticed on their own. It now runs the check every 20 minutes regardless.

## v0.2.25-beta · 2026-10-28
- **Takes edited in the Docs count** (Steven, 10-28: a take written in the morning boxes, then augmented in the car
  with Claude editing the shared Doc). The pipeline reads the published edition's "Steven's takes" and the deep
  dive's "Steven's take" back from Drive; lines that changed after its own last write are new takes, checked like
  any other. The runner looks every 20 minutes once the edition is out and queues a `takes-sync` job (auto tier)
  that applies them and re-publishes the site and email boxes; an edited deep-dive take re-records the deep dive
  and re-publishes its episode. No email is re-sent. `./np takes apply DAY` does the same by hand.

## v0.2.24-beta · 2026-10-28
- **Phone notifications and one-tap approvals** (Steven, 10-28: "more control from my iPhone"): through the free,
  open-source ntfy app. Approvals arrive as a notification with Approve and Reject buttons; one tap, no passphrase,
  no browser. The tap sends a one-time token the Mac checks, over private topics only the Mac's Keychain and the
  phone know. Nudges: the takes page is ready (tap opens it), the evening deep-dive note is out (tap opens the
  queue page), a run needs attention, a run-queue job finished. Turn on with the `ntfy-setup` job (a Mac Approve;
  the topic lands on the clipboard for the phone), then "ntfy test". The passphrase path stays as a fallback.
  Security-sensitive: a third approval path.

## v0.2.23-beta · 2026-10-28
- Phone approvals: the job file now says why a phone answer wasn't accepted (no answer yet, the check failed, or the
  passphrase didn't match), and a passphrase that doesn't match gets one Mac notification, as promised.

## v0.2.22-beta · 2026-10-28
- **Calls we made** (site page): every house-view call with what would change our mind and its check date. On
  Sundays the run scores the calls that are due against what we've reported since (right, wrong, mixed; too early
  gets 90 more days). `./np positions [list|score]`; run-queue job `positions-score`.
- **Accuracy audit**: after the email, about five of the day's claims are re-checked against their own sources
  (supported, partly, not found, contradicted), and the consistency flags are counted. Partly right or contradicted
  claims send one alert email; the site's Accuracy page shows the daily counts and every correction. `./np audit
  [DAY]`; run-queue job `audit`. Dashboard switch: Briefing structure → "Accuracy audit after the email" (on).
- **Phone approvals** (Steven, 10-27): mac-tier jobs (ship, release, approve...) can be approved from the phone.
  The runner emails a one-time link; on the page you type your approval passphrase and tap Approve or Reject. The
  passphrase never leaves the phone (the page sends a proof the Mac checks against its Keychain), so a link or a
  record alone can't approve. Turn it on once with the `phone-setup` job (a Mac dialog asks for the passphrase).
  Security-sensitive: a second approval path. Needs the mail-script deploy (the ship does it).
- **Merged top, on** (Steven, 10-27): Briefing structure → "Top of the edition" = merged gives one 5-bullet "Today in 30
  seconds" with the diligence question under it, instead of the day in brief plus Top of mind (critic #7A). Audio,
  email, takes, Drive and the checks read both shapes.

## v0.2.21-beta · 2026-10-27
- **House views.** Our read takes a position under one of the views in `house_views.md` (1–10 plus Steven's
  theses 11–17) and names it ("House view: …"). The lead story adds the case for, the case against, the deciding
  question and our lean, in place of its other view. Each position is logged in `data/positions/ledger.jsonl` with
  what would change our mind and a check date (a thesis's own, else 90 days). Dashboard switch: Editorial lens →
  "Take positions under the house views". Security: `house_views.md` steers the models, so it joins the files
  whose changes need release approval.

## v0.2.20-beta · 2026-10-27
- **Pending sign-ups** (Steven, 10-27): one reminder email to people who signed up but never confirmed ("One click to
  start receiving it"), at most once a week each; 14 days after the reminder a still-pending sign-up is marked
  expired by the morning run (they can sign up again, and an old confirm link still works). Run-queue jobs
  `email-remind` and `email-remove` (chat tier). `./np email list` counts readers without the owner's test copy.
  Needs a mail-script deploy (the ship does it).

## v0.2.19-beta · 2026-10-27
- **New taglines** (Steven, 10-27): the AI Briefing is "Slowly, then fast. Every morning." and the deep dive is
  "One story, slowly. Down to the details." On the email masthead and deep-dive section, both podcast covers, both
  feed descriptions and the site.
- Speech: a name glued to its version number is split before the pronunciation table ("Qwen3.8" was heard as
  "QN3, 8"; now "Chwen three point eight").

## v0.2.18-beta · 2026-10-27
- **The weekly flagship deep dive** (Steven, 10-27: "lets do this as outlined"): on Saturdays the deep dive is a
  two-voice episode of about 22 minutes on the week's topic, with Bella as host and Michael as the sceptic who
  pushes back on the evidence. Same checks as the daily deep dive. Shown as "Weekly deep dive" in the feeds and
  "This week's deep dive · two voices" in the email; Friday's evening note says so.
- Fix: the new audio check is `./np audio-check` (and run-queue `audio-check`); `./np listen` already played the
  day's MP3 on the Mac.

## v0.2.17-beta · 2026-10-27
- **Hear what was published** (Steven, 10-27): after the email, the day's episode is downloaded from the public feed,
  transcribed locally (Whisper, free) and compared with its script. A missing or garbled section (like 10-27's
  intro) sends one action-needed email. The as-published transcript is published with the next publish (WebVTT,
  `podcast:transcript` in the feed, a link on the day's page). `./np audio-check [DAY]`; run queue `audio-check`; `setup`
  (chat tier) installs the new requirement (mlx-whisper, Apple silicon).
- **The deep dives as their own podcast:** `deepdive.xml`, "AI Briefing: Deep Dive", with its own cover. The daily
  show still flows from the briefing into the deep dive. The deep-dive feed is promoted on the site (Deep dives
  section, each deep-dive page, the footer) and in the email ("▶ Listen to the deep dive", "subscribe to the deep
  dives").

## v0.2.16-beta · 2026-10-27
- **Podcast brand matches the newsletter** (Steven, 10-27): new 3000×3000 cover in the teal of his photo, with his
  photo, "AI Briefing", the tagline and "Curated by Steven Woods". Podcast apps pick up new artwork on their own
  schedule (Apple can take a few days).
- **The show is named in the first seconds** (Steven, 10-27: "the audio today has no introduction"): the cold open
  now starts "On today's AI Briefing." Each recording also gets a `.sections.json` with every section's length, so
  a section that comes out silent or clipped is visible.

## v0.2.15-beta · 2026-10-27
- Fix (mail script): rewriting a Drive doc that ends with a list (Steven's takes) failed in clear(); an empty
  paragraph is added first (10-27). Needs a mail-script deploy (the next ship does it).

## v0.2.14-beta · 2026-10-27
- Fix: the public export's tests failed because the photo isn't exported (the public code push stopped).
- Fix: `./np release … --force` never reached the release (the command line took `--force` for another command).
- Fix: the release itself still waited for 08:30 when the run queue let it go early; it now follows the same rule
  (once today's edition is out).
- Shares: a link shared in Slack is labelled "Shared internally today" (it said "Shared in Steven's team channel");
  Steven's own Bluesky posts say "Posted by Steven on Bluesky" (Steven, 10-27).

## v0.2.13-beta · 2026-10-27
- Fix (mail script): rewriting an existing Drive doc (the draft becoming the published edition) failed with "Can't
  remove the last paragraph in a document section" (10-27). The tidy-up step is now optional. Needs a mail-script deploy.
- Voice: `scripts/voice/transcribe.py` transcribes Steven's recorded talks locally (Whisper), from the public record manifest.
- **Approvals keep moving in the morning** (Steven, 10-27: "get everything moving as soon as I am done"):
  - Approve early: a release queued before the morning is done asks right away, and runs as soon as the edition
    is out. The click is kept as a signature made with a key in the Mac's Keychain, which a file alone can't fake;
    it's used once and only that day.
  - The morning window ends when today's edition has gone out and no run is busy, not at a fixed 08:30.
  - One Approve covers the release's follow-through: the public code export, and a mail-script deploy when the
    live script differs from the release.
  - The approval dialog stays up 19 minutes and comes back right away, with a sound, until it's answered.

## v0.2.12-beta · 2026-10-26
- **Email masthead** (Steven, 10-26): his photo and colour (the teal of the photo), "AI Briefing", the tagline
  "What happened, what holds up, what it means." (`email.tagline` overrides) and "Curated by Steven Woods · for
  early-stage investors". The photo is served from the site (`assets/steven-woods.jpg`). Visual only.
- Drive docs: the deep dive no longer repeats "Why today", and flag emoji (garbled in Docs) are left out.
- Fix: the run queue's `approve` job stopped at its own gate check when only the approval was missing (10-26).

## v0.2.11-beta · 2026-10-26
- **Your take on a deep dive** (Steven, 10-26): a box on every topic on the queue page (from the evening email) and on
  the dashboard's Deep dives page. The take is read verbatim as "Steven's take" at the end of that deep dive, on the
  site and in the podcast, after the same privacy check as morning takes.
- **Every topic in the evening email has its own buttons:** Make next, ↑ / ↓, Add to Up next, Add your take, Dismiss,
  and "Suggest as a deep dive" on today's deep dive and watchlist mentions. Each opens the queue page with that change
  ready to confirm. The queue page can now also add a suggestion to the end of Up next. Needs a mail-script deploy.
- **The edition and deep dive in Drive** (Steven, 10-26): Google Docs in the shared `Briefings` folder, named by date.
  With the pre-release takes email: "<day> · AI Briefing (draft, held for your takes) · <lead>" and "<day> · Deep
  dive · <title>" (the takes email links to the draft). Once published, the draft becomes "<day> · AI Briefing ·
  <lead>" with Steven's takes, and the deep dive doc is rewritten. `./np drive save [DAY]` / run-queue `drive-save`.
  After the mail-script deploy, run `authorizeDrive` once in the Apps Script editor to grant Drive and Docs access.

## v0.2.10-beta · 2026-10-26
- **Fix: the takes email linked to a page that doesn't exist yet** (Steven, 10-26). The day's site page is only
  published after the cutoff, so the link now opens a private review page served by the mail script: the held
  edition with a box after each section and one Submit ("Done: send the edition now" ticks it out early). The
  pipeline uploads the page just before the takes email (`setreview`, key only); the script shows it only with
  Steven's signed takes token. If the upload fails, the email goes without the link (the reply buttons still work).
- The text version of the takes email numbers each story by its headline again.
- Email takes: a section name as a header ("Worth knowing:", "Top of mind:", "Must read 2:") now counts like
  "W:", and a signature (a bare link or "-- " line) ends a take (10-26: a Worth-knowing take was missed).
- Includes the v0.2.9 mail-script fix below (that release was not shipped on its own). Needs a mail-script deploy:
  `deploy-mailer`, Approve on the Mac.

## v0.2.9-beta · 2026-10-25 (folded into v0.2.10)
- Fix (mail script): site takes were saved, but Sheets turned the day ("2026-10-25") into a date cell and the
  pipeline's read-back compared it as text, so it found none. Takes are now written as text, and the read-back
  compares raw cells, so the 10-25 test takes are found too. Needs a mail-script deploy (the first via clasp).

## v0.2.8-beta · 2026-10-25
- **Takes on the site, fixed for an open page:** the takes email's site link adds `?v=<day>` so the browser loads
  the page fresh, and the boxes also appear when only the `#takes=` part changes (on 10-25 a cached page showed none).
- **Run-queue jobs for takes:** `takes-test DAY` (the takes email marked [TEST], to the owner), `takes-check DAY`
  (what would publish now: email, site, Slack, with the privacy check; saves nothing), `takes-apply DAY` (chat
  tier: save the day's takes and publish; for a shipped day only the written takes change).
- **The mail script via clasp** (`pipeline/clasp.py`, `./np mailer status | setup | deploy`): `mailer-status`
  checks the live script against the repo, `deploy-mailer` (Approve on the Mac) pushes Code.gs and updates the same
  deployment, so mail-script changes stop needing copy and paste. One-time setup by Steven: docs/EMAIL-SETUP.md.
- The site script is a raw string (Python's escape warning is gone).

## v0.2.7-beta · 2026-10-25
- **Takes on the website:** the private takes email has a "Read and comment on the site" link to the day's page.
  With Steven's signed token (after the `#`, valid two days) the page shows a box after the day in brief, Top of
  mind, each Must-read story and Worth knowing, and one Submit (with "Done: send the edition now"). Visitors without
  the token see nothing different. The mail script checks the token and stores the takes; the pipeline reads them
  during the hold together with email replies and Slack, and the same privacy hold applies.
- **Needs a redeploy of the mail script** (`scripts/apps-script/Code.gs`: new `takes` / `takes_pull` actions, owner
  token scope `t`, a `{{OWNERT}}` placeholder for owner sends). Until then the site link shows no boxes and
  everything else works as before.

## v0.2.6-beta · 2026-10-25
- Takes email: bold lead phrases were pale blue on white (the subscriber email's dark-mode colour) and now read
  dark; links are blue. A "W" slot covers Worth knowing (button in the takes email, a take box under Worth knowing
  in the subscriber email and on the site, and read after the quick hits in the podcast).

## v0.2.5-beta · 2026-10-25
The critic's first batch (review of 2026-10-24), plus an easier way to add takes.
- **No story twice:** after the deep dive is written, a Must read it covers shrinks to one sentence and a pointer,
  in the written edition, the email and the podcast. On 10-24 this would have cut the PHP story that took about 11
  of 19 minutes.
- **The briefing agrees with its deep dive:** "not disclosed" lines the deep dive answers are dropped from the day
  in brief and Top of mind; "unverified" lines about the deep dive's story are flagged for review.
- **Verdict labels match their evidence:** "Holds" is no longer used on an evidence check that says the claim is
  self-reported or unverified; it reads "Unverified".
- **Source gate:** a homepage link, or a sponsored or webinar page, can't be a Must read.
- **"For early-stage":** a new line on each Must read on what the story means at seed and Series A (written
  edition, email, podcast).
- **Audio:** a cold open with the lead story's sharpest line; loudness normalised to −16 LUFS at 96 kbps; "K3.1"
  is said "K three point one", not "Kthree"; a lint logs words the voice may garble; developing stories get a
  short "what's new" segment.
- **Takes email:** it now carries the whole edition, with an "Add your take" button after each section that opens
  a reply with the section's number filled in, and a link to the page on the site.
- Not in this batch: merging the day in brief and Top of mind (critic item 7), which changes the email, site,
  takes slots and audio together; it needs a preview first.

## v0.2.4-beta · 2026-10-25
- Fix: v0.2.3's public code push was refused because the new critic page (docs/CRITIC.md) wasn't in the public
  export, so the exported tests couldn't find it. It's added, and a test now checks that every page on the site's
  docs is in the export.
- `./np sources add` says "already a source" (and closes the queue entry) when the feed is already wired in,
  instead of "no feed answered".

## v0.2.3-beta · 2026-10-25
- Fix: on Sun 10-25 the Mac went offline during the takes hold, so the publish at the 09:15 cutoff failed and the
  email was held. The only retries were at 06:30 and 07:30, before the cutoff, so nothing sent it later. With takes
  on, the schedule now also retries at 09:30, 10:30 and 12:00 (`schedule.after_takes`).
- Fix: v0.2.2's release was approved at 20:02, after the release window, and failed. The run queue no longer shows
  a release dialog that would be answered after 20:00, and an approval that lands outside the window now expires
  cleanly instead of failing.
- The run-queue job `send-held` (chat tier) runs `./np daily` to publish and email a held edition.
- Includes v0.2.2 (the weekly critic email, `./np sources add`), which wasn't released on 10-24.
- **Docs:** a new page, "The critic" (`docs/CRITIC.md`, also on the site): the rubric and its weights, the benchmark
  shows and why they were chosen, how a weekly run works, the email and the record, the limits, and the latest
  results (generated from `data/critic/` at every publish: ranking, us against the field by characteristic, our
  trend). The architecture page gains a section on the weekly critic.

## v0.2.2-beta · 2026-10-24
- **The weekly critic:** every Saturday the briefing is scored against the latest episode or issue of ten benchmark
  shows, with a 10-part rubric weighted for an investor daily. A private email to the owner gives our score and
  rank, bar charts by characteristic against the field, our trend week by week, what shipped, and the top
  suggestions with recommended options (`pipeline/critic.py`, `./np critic preview | email | list`, the run-queue
  job `critic-email`). Results are kept in `data/critic/<date>.json`; the first is 2026-10-24.
- `./np sources add "Name" URL [URL] [note]` and the run-queue job `source-add`: verify a feed live on the Mac,
  then wire it in. Used to add the ten benchmark shows as sources.

## v0.2.1-beta · 2026-10-24
- Fix: the first takes morning (10-24) never sent the takes email. The takes step called the mailer with
  positional arguments it doesn't take, so it failed straight away and the edition shipped on time without takes,
  as designed. Fixed, with a test that checks each call against the mailer's real signature.

## v0.2.0-beta · 2026-10-23
- **Steven's takes (My takes, phase 1):** the owner's own view in the edition, verbatim, labelled "Steven's take".
  - Once the edition is written, a private "AI Briefing · Your takes" email lists slots: 0 (the day), T (Top of
    mind), and 1 to N (each Must-read story). Reply "1: ..." from a phone; "done" sends early, "skip" means none.
  - Your own words on a link you post in the team Slack channel count as your take on that story.
  - The edition waits until **09:15** or "done" (`./np takes done`, or `takes-done` in the run queue).
  - Each take is checked for private names, owner addresses, personal links, disclosure phrases and the
    confidential marker. One that fails is held back and listed to you, never published.
  - Takes appear on the site and in the email, and the host reads each one after its story in the podcast. Only
    the briefing audio is re-rendered.
  - Retries leave a waiting run alone; a failure ships the edition without takes.
- `./np takes status | email | preview | done`.
- Fix: the Slack reader closed or leaked its HTTP client when it found your own LinkedIn posts.

## v0.1.14-beta · 2026-10-23
- **First-lines check for the daily briefing:** the day in brief and Top of mind are now checked against the
  edition's own body, as deep-dive summaries have been since v0.1.9 (`consistency.check_briefing`). A figure
  belongs to its whole story, so a line can name the company in its lead. A sentence that ties a figure to the
  wrong company, or says something wasn't disclosed when the body gives it, is dropped.
- **Across days (flag):** a "not disclosed" claim is compared with the previous 14 editions and flagged for review
  if an earlier day gave the figure for the same company.
- The "not disclosed" test is stricter everywhere: a question asking for a figure, or a sentence saying it's
  lacking, no longer counts as giving it, and it must be about the same company.
- `./np consistency [DAY|all]` (also a run-queue recipe) runs the checks over published editions as a dry run.
  Over all 18 editions and 8 deep dives it found one misattributed figure (10-22's day in brief) and two
  cross-day flags (10-23).

## v0.1.13-beta · 2026-10-23
- Fix: the run queue's launchd tick never started a job. Its quick idle check listed both queue folders with `ls`,
  which fails whenever one of them is empty. It now checks each file, and a test runs the real `./np runner tick`.

## v0.1.12-beta · 2026-10-23
- **Run queue:** releases, corrections and checks can be started from the Claude chat instead of pasted into a
  shell (`pipeline/runner.py`, `./np runner`, docs/plans/run-queue.md). Claude queues a named recipe and the Mac
  runs it. There are three tiers: tests, staging and verify run at once; corrections and publish need Steven's
  yes in the chat; releases, rollbacks, approvals and the public code push need Approve in a dialog on the Mac.
  The click grants presence for that job only (`pipeline/presence.py`), and no file can stand in for it. Release
  invariant 10 guards the runner. One-time setup: `./np runner install`.
- **Docs stay current:** release-gate tests now require every public module to be described in a hand-written doc
  and every diagram to be used. Each release lists the modules that changed while their docs didn't ("docs to
  review"), in the approval dialog and in `data/state/docs-impact.json`, for a weekly docs refresh.
- **Docs:** Fact checking is rewritten as "Grounding and fact checking": six layers, a new diagram, why the
  first-lines check exists, corrections and known gaps. Architecture gains sections on grounding, the run queue
  (with a diagram) and keeping docs current, plus every smaller module.

## v0.1.11-beta · 2026-10-23
- Fix: v0.1.10's public code push was refused again, correctly: a code comment and the changelog named a
  portfolio company. Both are reworded, and the dev test now builds the whole public export and fails on any
  private term, not only in test files.

## v0.1.10-beta · 2026-10-23
- Fix: v0.1.9's public code push was refused, correctly, because a new test used real portfolio names. The test
  now uses made-up names, and a test fails in dev whenever any test file names a private term, so the release
  can't be the first place it's caught.

## v0.1.9-beta · 2026-10-23
Fix: on 2026-10-23 the deep dive's body was correct, but its summary and "Why today" lines, which readers see first
in the email, on the site and in the podcast notes, said a legal-AI company disclosed no ARR and that "a vendor"
claimed a $21M saving. In fact the company disclosed ARR, and the $21M was an investor's post about a different
company. The day before, an unsourced Agenda line had called that investor the other company's "founder".
- **The why-today line comes from the checked body:** it's written from the deep dive's checked "why today"
  section, no longer copied from the previous day's topic suggestion.
- **A header check (`pipeline/consistency.py`) for the summary and why-today lines:** a sentence is dropped if a
  figure isn't in the checked body, if it names none of the companies or people the body ties that figure to, or if
  it says something wasn't disclosed when the body or a source gives it. Spelled-out figures in scripts count. If
  nothing in the summary survives, the checked opening is used.
- **Agenda lines can't assert unsourced roles:** "founder", "CEO", "investor in" and similar must appear in the
  item's own source text; otherwise the line becomes neutral.
- **Deep-dive text is guarded like the briefing:** a shipped deep dive changes only through a correction, and its
  page shows the correction note.
- **`./np correct DAY "what changed"`:** records a hand edit to a shipped edition as a correction, shown on the day
  page and the deep-dive page.

## v0.1.8-beta · 2026-10-23
Fix: the 2026-10-23 edition was held at 05:26 and again at 06:30. The release gate re-ran the whole test suite
during the morning run, and one release test that checks for a running daily run saw the real one and failed.
The same check blocked the backup's git push.
- **Released code isn't re-tested in the morning:** once a code and settings fingerprint has passed the full gate
  (tests included) and is approved, later checks accept it without re-running the tests
  (`data/state/release-passed.jsonl`). Changed code is still fully checked.
- **Tests never read the live machine:** test runs set `NP_TESTING=1`, `run_in_progress` doesn't look at real
  processes under it, and the release tests mock it too.
- **The evening preflight tests tonight what runs tomorrow:** if the code hasn't passed the full gate yet, the
  preflight runs it at 20:30 and emails the owner if it fails, instead of finding out at 05:00.
- **The pre-push hook uses the same fast check** (`--release-check require`), and `./np release` reinstalls the
  hooks.

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
