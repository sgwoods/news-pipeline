# Release process: nothing outbound without the gate

"Outbound" = the public site and podcast feed, the subscriber email, Steven's private note, Gmail label
writes, the private backup push. Each of these calls `release.require()` first; it refuses unless
`./np release-check` passed for the exact code that is running (a fingerprint of every code file, prompt,
template and the Apps Script). If the code changed since the last pass, the gate re-runs automatically; if it
fails, the outbound step is skipped, the briefing still exists locally, and a macOS notification says why.

## What the gate checks
1. **Tests**: the whole suite (security tests included: mailbox guard, model isolation, SSRF guard, forward
   privacy, personal links, release gate).
2. **Secrets**: every tracked file, against token patterns and the real secret values (Keychain / .env);
   `.env` untracked and mode 600; `.gitignore` lists `.env` and `data/inbox/`.
3. **Invariants**, as code: mailbox only through the guard; `claude -p` with no tools (web stages: search and
   fetch only), no MCP servers, no secrets in its environment; web stages never receive mailbox text; the
   briefing's output gates (verified quotes, private names, personal links); site scan before publish; backup
   only to a private repo; dashboard localhost-only; Apps Script recipient limit; the private people list read
   in one place only.
4. **Outputs**: privacy scan of the last three editions (written, spoken, deep dives).
5. **Approval**: if a security-sensitive file changed (since 2026-10-18 H4: every code file, prompt, template, the Apps
   Script, every test, `.gitignore`, `config.yaml`, `author*.md`, `newsletters.yaml`, `conflicts.yaml`,
   `source_profiles.yaml`, `pronunciations.yaml`), a human records that they reviewed it:
   `./np release-check approve "reviewed: <what changed and why it is safe>"` (stored in
   `docs/security/approvals.json`, committed).
6. `live` (on the Mac): the installed Claude CLI supports the isolation flags.

## Workflow for any change
1. Change code (Claude or Steven) → commit (the pre-commit hook scans the staged files for secrets).
2. `./np release-check` → fix anything failing.
3. If it asks for approval: read the diff of the sensitive files (`git diff <last approved commit> -- <files>`),
   then approve with a note.
4. Push (the pre-push hook runs the full gate).

Evening check: the preflight service runs `./np preflight` at 20:30 and notifies if an approval is pending, so the
morning run isn't held. If a morning's outbound steps were held anyway, the run after the next approval sends them
(`_retry_outbound`).

**Action-needed emails (2026-10-19):** when the gate blocks the morning (or the evening check sees a pending
approval), a run produces no briefing, or the publish or email step fails, `pipeline/alerts.py` emails Steven once per
issue per day with what happened and the exact commands to run. This is the one email that does not wait for the gate
(the gate being blocked is its main reason to exist). It can only go to the owner address (`mailer.call(_alert=True)`
refuses any other recipient or action; Code.gs limits recipients too), and its text comes from fixed templates plus
the pipeline's own error messages, defused and privacy-checked.

Approvals need Steven, never Claude, a scheduled task or the dashboard. Claude says when an approval is needed and
what to look at, then queues a mac-tier job. Steven answers it one of three ways, each tied to that job and that day
by a key only the Mac's Keychain holds (pipeline/runner.py):
- **a tap on the phone** (ntfy, v0.2.24, the usual way): Approve or Reject on the notification sends a one-time
  token over a private topic; the runner checks it on its next tick;
- **the Mac dialog** (shown for 90 seconds when phone approvals are on);
- **the approval page with a passphrase** (v0.2.22, fallback): the page sends a proof made on the phone from the
  passphrase, checked against the Keychain.
None of the email, the mail script's records or the job files can stand in for these, so Claude, which can read all
of them, cannot approve.

**Approval up front in chat (Steven, 2026-10-31; v0.2.37).** Taps that arrived 10–20 minutes after a task started,
when Steven was away from the Mac, were the interruption. For `ship` and `release` only, Steven's yes in chat (asked
by Claude when the task starts; answerable in the Claude iOS app) is the approval: Claude quotes it in the job's
`chat_approval`, and the runner releases on its own once tests and the soak on today's edition pass, then notifies
him. The trade-off, accepted by Steven: this rests on Claude quoting him faithfully, like the chat tier always has,
not on a key only the Mac holds. Failed tests, a soak that needs review, the 08:30–20:00 window and the slot rules
still stop it. `rollback`, `push-code`, `approve` and every secrets setup keep the tap.

**No-ask jobs (same day):** re-recording after an agreed correction (`remaster`) and rebuilding a broken deep dive
on its topic (`deepdive-rebuild`) are auto tier; checks, previews, probes and the daily X-list refresh already were.
Each is logged and notified. Releases run 08:30–20:00, or earlier once the morning edition is out.

## Release rules for day-to-day stability (2026-10-30)
The newsletter matters more than the next feature. From v0.2.33:
- **One slot a day.** Feature work batches into one `ship` per weekday, from 13:00 (`release.slot`): after the
  edition and the takes, before the 15:30 advance draft. A second slot ship the same day, or a slot ship at a
  weekend, is refused with the reason ("expired"), not held.
- **The fix lane.** `ship` with `lane: fix` is for something that is broken (a failed run, a wrong page, a lost
  input). It goes any time in the release window and doesn't use the slot. Claude says in chat why it is a fix.
- **The soak.** Every ship rebuilds today's edition in dev with the new code (`./np staging run`, outbound off) and
  compares it with what went out (`./np staging compare`: sections, counts, length, links, audio, privacy). A compare
  that needs review stops the ship before Steven is asked; it goes only with `accept: "accepted: <Steven's words>"`.
  The Approve shows the lane and the soak verdict.
- `release` (no tests, no soak) is only for finishing a ship whose release step failed.

Baseline: the first approval is Steven's, after reading `REVIEW-2026-10-15.md`. Until then every outbound
step is blocked (the morning briefing is still produced locally).


## Rules for tests (2026-10-23)
- Tests describe the code, never the machine: no reading of real processes, the clock (pass `now`), the network,
  or files outside a temp folder. Test runs set `NP_ENV=production` and `NP_TESTING=1`.
- The full gate runs at release time and in the evening preflight. Mornings only confirm that the running code
  is code that already passed and is approved (`release-passed.jsonl`), so a test can never block a send.
