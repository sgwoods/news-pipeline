# The critic: how the briefing is rated, every week

Every Saturday morning the briefing is scored against the latest episode or issue of ten of the most popular tech
and AI shows, with one fixed rubric. The aim is practical: find the few changes that would most improve the
briefing for its readers and listeners, decide each week which to make, and see whether they worked.

## The rubric
Ten characteristics, each scored 1-10 (1-3 poor, 4-6 adequate, 7-8 strong, 9-10 best in class). The overall score
is the weighted sum divided by 10, out of 100. The weights are for a **daily AI briefing for investors**, set from
what audiences consistently praise and criticise in reviews, rankings and press coverage of these shows:
signal-to-noise first, then accuracy and depth; brevity and a fixed structure for a daily; conviction that is fair
to the other side; voice as the moat; polish counts but comes second.

| Characteristic | Weight | What is measured |
|---|---|---|
| Content selection | 18 | Signal-to-noise: the right stories, no filler |
| Accuracy & sourcing | 15 | Traceable claims, links to primary sources, no contradictions within an edition |
| Depth & insight | 14 | The "so what" for capital and markets |
| Timeliness & cadence | 10 | Fresh and dependable enough to become a habit |
| Structure & pacing | 10 | A predictable order, and a length that fits the format |
| Opinion / point of view | 9 | Conviction that is fair to the other side |
| Distinctiveness & fit | 7 | Hard to get elsewhere; built for this audience |
| Writing / script | 6 | Clarity; written for the ear in the podcast |
| Tone & voice | 5 | Personality, chemistry, register |
| Production | 6 | Audio fidelity, music, cold open, interludes, transitions, editing; design for a newsletter |

Production problems a listener notices cap the score, whatever the other characteristics.

## The benchmark shows
Chosen in October 2026 for popularity (chart positions, subscriber and audience figures, rankings) and for
relevance to a daily AI briefing for investors: Dwarkesh Podcast, Stratechery, The AI Daily Brief, Machine Gods
(NPR), Latent Space, The Neuron, Acquired, All-In, TLDR AI and the Lex Fridman Podcast. Two changes from the first
list: Machine Gods replaced Hard Fork when its hosts moved there, and TLDR AI (about 1.15M subscribers) replaced
The Batch, which publishes no audience figures; The Batch was kept as a bonus benchmark in the first run.

Long interview and history shows (Acquired, Lex Fridman, All-In) score low on fit and length for an investor
daily. That reflects the use case, not their quality.

## How a weekly run works
1. **The ten shows.** Each show's latest episode or issue is scored. Nobody listens to the audio: scores come from
   transcripts, show notes, chapter lists, reviews, press coverage and production credits, and each score carries
   a confidence note. Newsletters are scored on the issue itself.
2. **The briefing.** An independent critic reviews the past seven editions: the written edition, the podcast
   script, the deep dive, the run statistics, takes and corrections. The written edition and the podcast are
   scored separately where they differ (structure, writing, tone, production), then combined. Measurements are
   included: word counts, durations, sections and their order, how often a story repeats across days.
3. **The feedback.** Five strengths to keep, and ten suggestions ranked by expected effect on the score. Each
   suggestion carries evidence (a quote or a measurement) and two to five concrete options, with one recommended,
   plus a first batch with the most impact for the effort. Free, local fixes come first.
4. **The decision.** The owner receives a private email (below) and chooses what to build that week. Changes go
   through the normal release process, and the next week's run checks whether they moved the scores.

## Outputs
- **The weekly email** (owner only, `pipeline/critic.py`): our score and rank; the top five suggestions with the
  recommended option; a bar chart of our score against the field average and the best show for each
  characteristic, marking where we are below the field; the overall ranking; our trend week by week; what shipped
  that week; strengths to keep. The charts are plain HTML, so they render in any mail client.
- **The record:** `data/critic/<date>.json` (scores, suggestions, options) and `data/critic/<date>.md` (the full
  narrative report), kept in the private archive. The trend is read from these files.
- **Commands:** `./np critic preview | email | list`, and the run-queue job `critic-email`.

## Limits
- Scores are informed judgements by a model, not measurements. Different reviewers score different shows, so
  differences of about 3 points are noise; the trend over several weeks matters more than one week.
- Audio can't be heard, so production scores rest on documented evidence and carry lower confidence.
- Only the latest episode or issue of each show is scored, so an unusual week moves its score.
- The rubric is weighted for this briefing's use. It is not a general ranking of the shows.

## Latest results
_Generated at build time from the critic run of 2026-11-07._

| Rank | Show | Score | Rated |
|---|---|---|---|
| 1 | Stratechery | 85.2 | AI on the Ballot (2026-11-04) |
| 2 | The AI Daily Brief (newsletter) | 77.9 | Companies Are Spending 5x More on AI Now (2026-11-06) |
| 3 | The AI Daily Brief (podcast) | 74.2 | Companies Are Spending 5x More on AI Now (2026-11-06) |
| 4 | Machine Gods (NPR) | 73.7 | The Purple Tsunami Against Data Centers (2026-11-06) |
| 5 | Acquired | 72.5 | Seinfeld (2026-10-18) |
| 6 | Latent Space | 72.2 | Deep Dive: Anthropic S-1 Myths and Mythos (Jamin Ball, Altim (2026-11-07) |
| 7 | **AI Briefing (us)** | **70.8** | the week's editions (2026-11-07) |
| 8 | All-In | 68.6 | Anthropic S-1 Shocker, Greatest Business Ever? Google's $500 (2026-10-30) |
| 9 | The Neuron | 63.5 | OpenAI released GPT-6 Cyber, a hacking AI (2026-11-06) |
| 10 | Dwarkesh Podcast | 61.6 | What Robert Caro learned about power after studying it for 5 (2026-10-30) |
| 11 | TLDR AI | 59.8 | TLDR AI 2026-11-06 (GPT-6 Cyber, Inkling 2 Small, Gemini Omn (2026-11-06) |
| 12 | Lex Fridman Podcast | 57.8 | #503 - AI Crisis in Math: Navier-Stokes, Riemann Hypothesis  (2026-10-26) |

| Characteristic (weight) | Us | Field average | Best |
|---|---|---|---|
| Content selection (18) | 7 | 7.5 | 9 (Stratechery) |
| Accuracy & sourcing (15) | 6 | 7.3 | 9 (Acquired) |
| Depth & insight (14) | 8 | 6.4 | 9 (Stratechery) |
| Timeliness & cadence (10) | 8 | 7.4 | 10 (TLDR AI) |
| Structure & pacing (10) | 6.5 | 7.1 | 8 (The AI Daily Brief (newsletter)) |
| Opinion / point of view (9) | 8 | 6.4 | 9 (Stratechery) |
| Distinctiveness & fit (7) | 8 | 6.3 | 9 (Stratechery) |
| Writing / script (6) | 6.5 | 6.8 | 8 (Stratechery) |
| Tone & voice (5) | 7 | 7.4 | 8 (The AI Daily Brief (newsletter)) |
| Production (6) | 5.5 | 6.9 | 9 (Machine Gods (NPR)) |

Our overall score by week: 2026-10-24 62.2 · 2026-10-31 69.6 · 2026-11-07 70.8
