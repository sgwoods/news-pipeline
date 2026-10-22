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

Approvals need a person at a terminal, so Claude, the scheduled tasks and the dashboard cannot approve.
Claude says when an approval is needed and what to look at.

Baseline: the first approval is Steven's, after reading `REVIEW-2026-10-15.md`. Until then every outbound
step is blocked (the morning briefing is still produced locally).
