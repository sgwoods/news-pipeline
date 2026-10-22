Run the critical pass ("nonsense radar") on this item, per the skepticism list and critical-pass tone in Steven's perspective file. Apply it equally to bulls and bears.

Judge the claims made by the SOURCE ITEM (its author or the organization it reports on). The first-pass summary is context only; if it states something the item does not support, mention that briefly in "overstated". Check any arithmetic yourself before you call a number wrong. "holds" is a fine verdict when the claim is modest and supported. Fill every field for every verdict; for "holds", say why the claim holds.

Weigh the source by its evidence type (the "evidence type" line), not by its confidence:
- Only "primary" (the company, lab, paper, filing or court itself) and "reporting" (a newsroom with editors) can establish that something happened. A primary source about itself is self-reported: say so.
- "analysis" can test a claim with evidence it shows. A first-hand test (the author ran the model, tool or benchmark and shows the result) is evidence of how a product behaves, as good as a report is for what happened; say what was tested and how. "opinion", "aggregator" and "social" never establish a fact on their own; for them, judge whether the facts they rely on come from a named primary source or report.
- Note a stated interest (an investor, employer or sponsor) when it bears on the claim. Hold every stance to the same standard: an AGI-forward and an AI-realist claim need the same evidence.

Pick the verdict with these definitions:
- "holds": the central claim is supported by what the item shows; any problems are minor.
- "overstated": the central claim goes clearly beyond the evidence in the item (bigger, more certain, or more general than shown).
- "unsupported": the central claim has no real evidence in the item at all.
- "mixed": ONLY when the item makes two or more central claims and they get different verdicts. Do not use "mixed" just because some details are missing; every item misses some details.

HARD LIMITS: "overstated" at most 35 words, "missing_evidence" at most 25 words, "would_change_view" at most 20 words. Short sentences. Name the one or two most important problems, not every problem.

Return JSON with exactly these keys:
{
  "verdict": "holds" | "overstated" | "unsupported" | "mixed",
  "overstated": "For holds: why it holds. Otherwise: what is overstated or rests only on the source's own numbers.",
  "missing_evidence": "The most important outside evidence that is absent.",
  "would_change_view": "The evidence that would change the verdict.",
  "one_line": "The verdict's reason in at most 20 words, for the printed briefing.",
  "corrected_claim": "If the first-pass claim misstates the item, the claim restated correctly in at most 45 words; otherwise an empty string."
}

<first_pass>
{{summary}}
</first_pass>

{{item}}
