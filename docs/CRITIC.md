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
_Generated at build time from the critic run of 2026-11-14._

| Rank | Show | Score | Rated |
|---|---|---|---|
| 1 | Stratechery | 83.3 | AI on the Ballot (2026-11-04) |
| 2 | The AI Daily Brief (podcast) | 75.5 | Washington Is Taking Control of AI (2026-11-13) |
| 3 | The AI Daily Brief (newsletter) | 75.1 | Washington Is Taking Control of AI (2026-11-13) |
| 4 | Dwarkesh Podcast | 73.2 | The avalanche that hit math is coming for AI development (na (2026-11-13) |
| 5 | The Neuron | 69.8 | Jensen Huang resigned as Nvidia CEO (2026-11-13) |
| 6 | Machine Gods (NPR) | 69.6 | The 10 Biggest Losers from Jensen Huang's Fall + The METR Re (2026-11-13) |
| 7 | All-In | 69.2 | Jensen OUT as Nvidia CEO: Spy Scandal, Export Restrictions,  (2026-11-14) |
| 8 | Acquired | 65.3 | Seinfeld (2026-10-18) |
| 9 | **AI Briefing (us)** | **63.8** | the week's editions (2026-11-14) |
| 10 | Latent Space | 62.1 | Designing for Agents - Zeno Rocha, Resend (2026-11-10) |
| 11 | TLDR AI | 59.1 | TLDR AI 2026-11-13 (Gemini 4 Hydrogen / Claude Managed Agent (2026-11-13) |
| 12 | Lex Fridman Podcast | 55.4 | #504 - Russia-Ukraine War: Putin, Zelenskyy, Drones and the  (2026-11-10) |

| Characteristic (weight) | Us | Field average | Best |
|---|---|---|---|
| Content selection (18) | 5.75 | 7.1 | 9 (Stratechery) |
| Accuracy & sourcing (15) | 5.5 | 6.8 | 8 (The AI Daily Brief (newsletter)) |
| Depth & insight (14) | 7.5 | 6.5 | 9 (Stratechery) |
| Timeliness & cadence (10) | 6.75 | 7.4 | 9 (The Neuron) |
| Structure & pacing (10) | 5.5 | 6.9 | 9 (Stratechery) |
| Opinion / point of view (9) | 7.5 | 6.7 | 9 (Dwarkesh Podcast) |
| Distinctiveness & fit (7) | 7.75 | 7.0 | 9 (Stratechery) |
| Writing / script (6) | 6.25 | 6.9 | 8 (The Neuron) |
| Tone & voice (5) | 7 | 7.1 | 8 (Stratechery) |
| Production (6) | 5 | 6.5 | 9 (Acquired) |

Our overall score by week: 2026-10-24 62.2 · 2026-10-31 69.6 · 2026-11-07 70.8 · 2026-11-14 63.8
