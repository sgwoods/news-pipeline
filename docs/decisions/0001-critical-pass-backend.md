# DECISION RECORD 0001: CRITICAL PASS BACKEND

Status: CLOSED 2026-10-06. Option B approved by Steven and confirmed by comparison (section 7).

## 1. Subject

The critical pass is stage 4 of the pipeline.
It examines the claims in an item and gives a verdict.
The verdict is "holds", "mixed", "overstated" or "unsupported".
At this time, the local model (qwen3:30b) does this stage.
You must decide which model does this stage in the daily run.

## 2. Data from the test

Test: run 20261006T113152, 73 items from 2026-10-05.

- The local model examined 32 items in 143 seconds.
- 17 of the 32 results have a verdict but no reason.
- 15 of the 32 results have the verdict "overstated".
- Some "overstated" results are not correct.
  - Example 1: The model said that $252B plus $161.2B is not $413.2B.
  - Example 2: The model said that the 0.3% robot figure is overstated. The item gives the same figure.
- Some results examine the first-pass summary, not the source item.
- Some results are correct and useful. Example: the Florida injunction item (Gary Marcus).

Conclusion: The local critical pass is not reliable at this time.

## 3. Options

### Option A: Keep the local model

- Cost: 0. All data stays on the Mac.
- Risk: Incorrect verdicts go into the briefing.
- Risk: You must examine each verdict before you use it.

### Option B: Use Claude Code (`claude -p`) for the critical pass only

- The local model continues to do the filter, rank and write stages.
- Cost: No API cost. The calls use your Claude subscription limits.
- Volume: Approximately 30 items each day.
- Time: Not known. The first run will measure it.
- Data: The item text goes to Anthropic. All items are public web content.
- Safety: The pipeline gives no tools to Claude Code. Fetched text cannot cause actions on your Mac.
- Requirement: Claude Code must be installed and logged in on the Mac.
- Requirement: ANTHROPIC_API_KEY must not be set.

### Option C: Use the Claude API

- Cost: You pay for each call.
- This option uses the same type of model as Option B.
- Thus, Option C gives no advantage at this time. Do not use it.

### Option D: Use a larger local model

- Cost: 0. All data stays on the Mac.
- The Mac has 32 GB of memory. This limits the model size.
- A larger model is slower. The improvement is not known.
- You can test this option later.

## 4. Recommendation

Use Option B.
First, do a comparison on the same day of data.
The archive keeps the local verdicts and the Claude verdicts.
Make the change permanent only if the Claude verdicts are better.

## 5. Procedure for Option B

1. Open Terminal on the Mac.
2. Type `claude --version`.
3. Make sure that a version number shows.
4. If the command is not found, install Claude Code. Then log in with your Claude account.
5. Type `echo $ANTHROPIC_API_KEY`.
6. Make sure that the result is empty.
7. Tell Claude: "approve option B".
8. Claude sets `llm.stages: {critique: claude_code}` in `config.yaml`.
9. Type `./np reprocess 2026-10-05`.
10. Tell Claude: "done".
11. Claude compares the local verdicts and the Claude verdicts. Claude gives you the result.

## 6. Procedure to go back to the local model

1. Open `config.yaml`.
2. Remove `critique: claude_code` from `llm.stages`.
3. Save the file.

NOTE: No other change is necessary. The archive keeps all old results.

## 7. Result of the comparison (2026-10-06)

Local run: 20261006T113152. Claude Code run: 20261006T114536. Same 73 items. 28 items had a critique in both runs.

- Claude Code examined 34 items in 314 seconds (approximately 9 seconds for each item).
- 0 of the 34 Claude results have no reason. The local model had 17 of 32 with no reason.
- Claude did the arithmetic correctly. Example: "$252B + $161.2B ≈ $413B". The local model said this sum was wrong.
- Claude found errors in the first-pass summary. Examples: "Dead Money" (wrong research firm), "What do you want from AI?".
- Claude gave new analysis. Example: Barclays, 1M searches for 16,000 users is approximately 62 searches each.
- Problem 1: Claude uses the verdict "mixed" too often (25 of 34).
- Problem 2: The Claude results are longer than the word limits (approximately 80 words).
- NOTE: Claude is an Anthropic model. Anthropic items get a critique from an Anthropic model. In this test, these critiques were strict (Barclays, robots, "What do you want from AI?"). Continue to monitor this.

Decision: Keep Option B. Status: CLOSED.
