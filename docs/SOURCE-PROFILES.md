# Source profiles: weighing evidence, not headcount

`source_profiles.yaml` says what kind of evidence each source is. Claude drafted it; you correct it. Code
reads it and never rewrites it. `./np profiles` lists sites and sources seen recently that have no profile.

| kind | what it is | can it establish a fact? |
|---|---|---|
| primary | the company, lab, paper, filing, court or government itself | yes, but self-reported when it is about itself |
| reporting | a newsroom with editors and corrections | yes |
| analysis | an expert showing evidence (tests, data, documents) | it can test a claim |
| opinion | argument or advocacy | no |
| aggregator | newsletters and link sites summarising others | no |
| social | an individual's post | no (the article it links is judged on its own) |

Also per source: standards (cites-and-corrects, cites, mixed, none), stance (neutral, AGI-forward,
AI-realist, market, policy, safety) and interests (investor in, employer, sponsor).

What changes:
- Byline: "primary source + 1 report + 3 commentaries" instead of "5 sources". Copies of one report count once.
- Must read needs a primary source, a report or a hands-on test (a source that ran it first-hand: tests: true). A story carried only by commentary goes to Worth knowing.
  (Stories whose sources have no profile at all are not blocked; add profiles with ./np profiles.)
- Every analysis and critique prompt sees each item's evidence type; the critique holds AGI-forward and
  AI-realist claims to the same standard and says when a primary source is self-reported.
- The editorial prompt weighs by evidence: a lopsided story is called as such (no "both sides" for its own
  sake), other views appear only where the facts allow more than one reading, and an advocate's interest is
  named ("a16z, which invests in this market, argues…").
- The run report shows the balance of each edition: Must reads grounded, primary/report/commentary counts and
  the stance mix. The point is to spot an echo chamber, not to force a 50/50 split.
