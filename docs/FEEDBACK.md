# Reader feedback (replies to the daily email)

The daily email ends with "Tell us what you think. Just reply to this email." Replies arrive in
you@example.com with the subject "Re: AI Briefing · ...".

## One-time setup (Gmail, 1 minute)
1. Gmail search box: `subject:("Re: AI Briefing")` → the sliders icon → **Create filter**.
2. Tick **Apply the label** → New label… `AI-Briefing/Feedback` (nest under AI-Briefing).
   Also tick **Never send it to Spam**. Leave **Skip the Inbox** unticked, so you still see replies.
3. Create filter (tick "also apply to matching conversations" if offered).

The pipeline reads only that label, read-only, with the app password the newsletters already use.

## Every day
`./np daily` ends with `./np feedback fetch` then `./np feedback triage`. Claude classifies each reply
(correction, content, format, podcast, source-suggestion, request, praise, unsubscribe, delivery, other),
gives it a severity (high / medium / low), a one-line summary and a suggested next step, and refreshes the
themes across all open feedback. The run report (logs/last-report.md) lists high-severity items. The dashboard
page **Feedback** shows the queue, with buttons: working on it, done, won't fix, → to-do.

    ./np feedback               open items, highest first, plus themes
    ./np feedback all           including done / won't fix
    ./np feedback fetch [DAYS]  read new replies now (default: last 14 days)
    ./np feedback triage        triage what's new
    ./np feedback set ID done "fixed in the Oct 15 rebrief"
    ./np feedback todo ID       make it a to-do (group: feedback)

## Privacy and safety
- Subscriber addresses never leave Gmail. A reply is stored (data/feedback/feedback.json) with a hashed
  sender id and first name only; addresses and phone numbers in the text are masked; quoted history and
  signatures are cut.
- Replies are data, never instructions. Triage only describes and suggests; nothing changes (prompts,
  sources, subscribers) without you.
- "Unsubscribe me" replies are flagged high by rule. Remove them yourself with `./np email remove ADDRESS`
  (the address is in the Gmail reply). The one-click link in every email already works for most readers.
- Your own replies (testing, or answering a reader) are marked "you".

## Star ratings (added 2026-10-16)

- **Email:** five stars under the headline and again at the bottom. Each star links to the mail script with the
  recipient's own token (`{{RATE}}`, filled in per recipient by Code.gs). The click opens a confirm page with the
  stars pre-selected and an optional "what would make it a 5?" box; **Send rating** records it. The extra click
  is deliberate: corporate link scanners open every link in an email, and a one-click GET would let them cast
  ratings. One rating per subscriber per day; a second one replaces the first.
- **Site:** the same stars at the end of each day page, anonymous (`who: web`), capped at 60 an hour. Reported
  separately and never counted toward the quality breakpoint.
- **Who counts as Steven:** a rating from any OWNER_EMAIL address (sgwoods@, stevenwoods.ai@). Owner links carry a
  signed, scoped token (`o` + r|q + date + HMAC): rating links expire after 35 days, queue-page links after 8.
  Rotating the SECRET script property voids them all (security review 2026-10-18, H2).
- **Storage:** the `ratings` tab of the subscriber Sheet. `./np quality pull` (and the daily run) fetch them
  without addresses (a hashed id per rater) into `data/ratings-stars.jsonl`; the scorecard merges them with
  `data/ratings.jsonl` (terminal, dashboard and email-reply ratings).
- **Switch:** `email.ratings: true` in config.yaml, only once the deployed script has the rate action
  (an older script would leave `{{RATE}}` unfilled).
