# Newsletters from Gmail as a source (one-time setup, ~10 minutes)

The pipeline reads one Gmail label over IMAP, read-only, and archives each newsletter issue like any
other item. Which newsletters, their tier and the bias note the analysis is told about live in
`newsletters.yaml` (hand-edited).

## 1. Subscribe
Use **you+briefing@example.com** on each newsletter's sign-up page (Gmail delivers it to your normal
inbox; the `+briefing` part is what the filter matches). A few sites reject `+` addresses: use the plain
address there, and the filter below also matches the senders listed in `newsletters.yaml`.

Starter list (all free): The Rundown AI (therundown.ai), TLDR AI (tldr.tech/ai), Superhuman AI
(superhuman.ai), The Batch (deeplearning.ai/the-batch), Import AI (importai.substack.com),
One Useful Thing (oneusefulthing.org), Last Week in AI (lastweekin.ai).

## 2. Label + filter (Gmail on the web)
1. Settings (gear) → See all settings → **Labels** → Create new label: `AI-Briefing`, then another
   `Sources` nested under it (the full name is `AI-Briefing/Sources`).
2. **Filters and Blocked Addresses** → Create a new filter → in **To** put
   `you+briefing@example.com` → Create filter → tick **Skip the Inbox**, **Apply the label:
   AI-Briefing/Sources**, **Never send it to Spam** → Create filter.
3. (Optional) a second filter with **From** = `therundown.ai OR tldr.tech OR superhuman.ai OR deeplearning.ai
   OR importai.substack.com OR oneusefulthing@substack.com OR lastweekin.ai` with the same actions, for
   sites that would not take the `+` address.

## 3. App password (needs 2-Step Verification on the Google account)
1. https://myaccount.google.com/apppasswords → App name `news-pipeline` → Create.
2. Copy the 16-character password into `.env` as `GMAIL_APP_PASSWORD=...` (spaces are fine; the pipeline strips them).
   `.env` is never committed. The password only allows IMAP/SMTP for this account; revoke it on the same
   page if the Mac is ever lost.

## 4. Check, then switch on
```
./np newsletters test      # IMAP login + the label exists
./np newsletters fetch 7   # read the last 7 days now (then ./np analyze to analyze them)
./np newsletters           # per-newsletter counts; senders under the label that are not in newsletters.yaml
```
Then set `email_sources.enabled: true` in `config.yaml`: every run reads the label after the web sources.

## How the tiers work
- `follow closely` / `follow`: like any tracked person.
- `wire`: aggregator; items can appear in Worth knowing or In brief, never lead a story.
- `coverage-check`: same, plus every claim goes through the critical pass (scrutiny). The bias note is
  passed to the model with each item ("about this source (Steven's note)").

## Forwarding something yourself (updated 2026-10-19)
Forward to `you+briefing@example.com` (or `stevenwoods.ai+sources@`) from any of your addresses. What happens:
- **A listed newsletter:** read in full, as usual.
- **Outside material** (a bank's market update, a report, an announcement from a company's own list): the body is
  kept and used as a source, credited to the original sender's organisation ("CIBC Capital Markets (forwarded)");
  your own note above the forward, signatures and legal footers are cut. It's treated like any source: its claims
  are checked, and it's never presented as fact on its say-so.
- **Shareable route:** anything you send from your own addresses to `briefing+briefing@example.com` (owner.yaml
  share_addresses) is cleared for public use and kept with its body, internal forwards included: credited to the firm
  ("your firm (shared)"), never to the colleague; your own notes as "Shared by the editor". Explicit not-for-distribution
  markers still keep it links-only. Gmail (stevenwoods.ai): filter `to:(briefing+briefing@example.com)` → label
  AI-Briefing/Sources, skip the inbox.
- **Internal or restricted mail** (from an @example-firm.com / @example-firm.com sender, or marked not for
  redistribution / internal use only / do not forward): only its public links are kept.
