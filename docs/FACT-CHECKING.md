# Fact checking before anything goes out

Steven's rule (2026-10-18): **cut unverifiable sentences and send; block only on privacy or a contradicted Must read.**
Every step below runs in the morning run before the email and the audio. None of them calls a model with
fetched text as instructions; fetched pages are data.

| Step | Where | What it does |
|---|---|---|
| 1. Reader | `pipeline/reader.py`, stage `verify` | An item under 600 characters (headline, teaser, social post with a link) gets its linked article fetched through the network guard. Unreadable → the verdict is "Unverified". A post with no link is judged as a post. |
| 2. Evidence check | `run.py` stage `verify` | Every Must read without a critique verdict gets one (holds / mixed / overstated / unsupported), with the article text from step 1. |
| 3. Source weighting | `source_profiles.yaml`, docs/SOURCE-PROFILES.md | A Must read needs a primary source, a report or a first-hand test; company posts are self-reported. |
| 4. Figure trace | `pipeline/factcheck.py`, write stage | Every figure in the edition is looked up in the text of its sources (raw items + articles the reader read). Dates, years, chapter numbers are ignored; differences and ratios of source figures count as traced. |
| 5. Search before cut | `pipeline/factsearch.py` | An untraced figure is looked for in the story's own linked articles, then on the web (Bing's public RSS search, free, no account; top 3 results). A page counts only if the figure sits within ~600 characters of the name nearest to it in the sentence. Found on the web → the sentence stays with a link to the outlet. At most 8 figures per edition. Requests logged to `logs/news-search.jsonl`. Switch: `factcheck.search: false` in config.yaml. |
| 6. Cut or flag | `factcheck.check` | Still untraced: in factual sections (day in brief, Top of mind, What happened, Worth knowing, In brief, Recommended reading) the sentence is cut; in headlines and analysis (Evidence check, Our read, views, Open questions) it is flagged in the run log only. |
| 7. Number check | `pipeline/numbers.py` | A stated difference that doesn't add up is corrected; changes and near-twin figures are flagged. |
| 8. Speech | `pipeline/speech.py` | Prices, rates, ranges and model sizes are spoken correctly ("two dollars for input and ten for output"). |
| 9. Privacy gates | `links.py`, `mailer.privacy_gate`, `publish.scan_site` | Private names, Steven's addresses, board-seat disclosures and tracker links never leave; these do block. |

The scorecard (`./np quality`) reports "Figures in no source" (target 0) from the write stage's report in the run log.

## Commands
```
./np factcheck              dry run on the latest edition: FOUND / CUT / FLAG, nothing edited
./np factcheck 2026-10-13   same for a day
./np factcheck probe "Harvey raised $300M at a $5B valuation." '$5B'    one live search
```
Deep dives have their own checks (docs/DEEP-DIVES.md): links opened, quotes verified, unsourced $/% sentences cut.


## The lines readers see first (v0.1.9, 2026-10-23)
Summaries and "Why today" lines appear in the email, on the site and in the podcast notes before anyone reads
the body, so they get their own check (`pipeline/consistency.py`), run against the already-checked body.
A sentence is dropped if:
- a figure in it isn't in the body;
- it names none of the companies or people the body ties that figure to;
- it says something was "not disclosed" when the body or a source gives it.

The "Why today" line is written from the checked body, never copied from the previous day's topic suggestion.
Agenda lines can claim a role ("founder", "CEO", "investor in") only when the item's own source says so.
Otherwise they read: "The author's role and any stake aren't stated in the source."

Corrections to shipped editions: `./np correct DAY "what changed"` after a hand edit. The note shows on the day
page and the deep-dive page.
