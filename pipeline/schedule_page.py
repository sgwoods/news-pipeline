"""The day's schedule as a table (Steven, 2026-10-29): what is produced, when, where it goes, and the window for
his feedback on each piece and how it is picked up. Built from config so it stays true when times change.
Shown on the dashboard (/schedule) and printed by ./np schedule."""
from __future__ import annotations


def rows(cfg: dict) -> list:
    sched = cfg.get("schedule") or {}
    times = sched.get("times") or ["05:00", "06:30", "07:30"]
    first, retries = times[0], ", ".join(times[1:])
    cutoff = str((cfg.get("takes") or {}).get("cutoff") or "09:15")
    pre = str(sched.get("preflight") or "20:30")
    slack = (cfg.get("slack") or {}).get("post") or {}
    ch = slack.get("channel") or (cfg.get("slack") or {}).get("channel") or "the team channel"
    sync = 20
    fl = (cfg.get("deepdive") or {}).get("flagship") or {}
    wd = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    flag_day = wd[int(fl.get("weekday", 5))] if fl.get("enabled", True) else ""
    R = []

    def add(when, what, where, window, how, kind="daily"):
        R.append({"when": when, "what": what, "where": where, "window": window, "how": how, "kind": kind})

    add(first, "The morning run starts: fetch, filter, rank, evidence checks, editorial, the written edition, "
        f"the deep dive, audio. About 30 minutes; a slow morning runs to 45. Retries at {retries} if it hasn't produced.",
        "Mac only, until it is checked.", "None yet.", "")
    add(f"~{first[:2]}:35", "Takes email and phone nudge: the held edition with a box per section, plus the deep dive.",
        "Your inbox; the review page (tap the nudge); Drive: '<day> · AI Briefing (draft, held for your takes)' and '<day> · Deep dive'.",
        f"Until {cutoff}, or until you say done.",
        "Type in the review page or reply to the email; or edit the Drive Docs (alone, or by talking to Claude in the car). "
        "All three are read at the cutoff or at done. Nothing goes out before.")
    add(f"{cutoff} / done", "The edition ships: site published, podcast feeds updated, subscriber email sent, Drive Docs rewritten "
        "as '<day> · AI Briefing · <lead>' with your takes; the as-published transcript check; the accuracy audit; "
        "the editor's note for tomorrow's deep dive.",
        "sgwoods.github.io/ai-briefing, podcast.xml and deepdive.xml, subscribers' inboxes, Drive, your phone (nudge).",
        f"Open all day: Doc edits are read every {sync} minutes.",
        f"Edit the published Docs (or have Claude edit them). Every {sync} min the Mac re-reads them; a changed take re-publishes "
        "the site and the email boxes, and a changed deep-dive take re-records the deep dive. No email is re-sent.")
    add("right after", f"The morning Slack post in #{ch.lstrip('#')}: the day's leads, one of your takes, the deep dive, the card; "
        "the deep dive follows as a reply in its thread.", f"#{ch.lstrip('#')}, posted by the AI Briefing bot.",
        "Before: via your takes (the post quotes the published ones). After: none; it is not re-posted.",
        "Your takes are what it quotes, so the review window above is the window.")
    add("right after", "The editor's note: tomorrow's deep dive, the queue, new suggestions (readers' ideas say who suggested them), "
        "the watchlist.", "Your inbox; the queue page (tap the nudge).", "Until tomorrow's run starts.",
        "Tap Make next, reorder, dismiss, add a topic, or write your take on tomorrow's topic: read verbatim after the deep dive.")
    adv = str(sched.get("advance") or "15:30")
    add(adv, "Tomorrow's deep dive, drafted: written and checked, not yet voiced.",
        "Drive: '<tomorrow> · Deep dive · <title> (draft)'; a nudge and an email with the link.",
        "Until tomorrow's run starts (05:00).",
        "Read it on the way home. At the end of the Doc: 'Steven's take' (your words, read after the episode) and "
        "'Notes for the editor' (what to change: the morning run revises the draft from them, checks it again, and "
        "records it with your take). Type or talk to Claude; write 'done' or just stop.")
    add("~every 20 min", "The run queue: jobs Claude queues; approvals arrive on your phone with Approve and Reject.",
        "Your phone (ntfy); the Mac dialog as a backup.", "Until 20:00 for releases; one tap.", "Tap Approve. A tap after 20:00 waits for tomorrow.")
    slot = str((cfg.get("release") or {}).get("slot") or "13:00")
    if slot.lower() != "off":
        add(f"{slot} weekdays", "The release slot: at most one batched code release a day. It first rebuilds today's "
            "edition with the new code and compares it with what went out; a big difference stops it before you're asked. "
            "Fixes for broken things can go any time (the fix lane); no feature releases at weekends.",
            "Your phone (ntfy): one Approve with the soak result.", "Until 20:00.", "Tap Approve, or Reject to hold it.")
    add(pre, "Evening preflight: would tomorrow's run be allowed to publish and email? One alert if an approval is pending.",
        "Your phone and inbox, only if something is wrong.", "Until 20:00 the same evening for releases.", "Approve on the phone.")
    if flag_day:
        add(f"{flag_day}s", f"The weekly flagship: the deep dive as a two-voice episode (~{fl.get('minutes', 22)} min).",
            "The same places as the daily deep dive.", "Same as any deep dive.", "Same as any deep dive; the Friday note flags it.", "weekly")
    add("Sundays", "Calls we made: the positions whose check date has come are scored against what we have reported since.",
        "The site's Calls we made page.", "None; it reads our own later coverage.", "Comment in the chat if a verdict looks wrong.", "weekly")
    add("Nov 10", "First expiries of pending sign-ups (14 days after the reminder).", "The subscriber Sheet.", "None.", "", "once")
    return R


def text(cfg: dict) -> str:
    out = []
    for r in rows(cfg):
        out.append(f"{r['when']:>14}  {r['what']}\n{'':16}-> {r['where']}\n{'':16}feedback: {r['window']}"
                   + (f" {r['how']}" if r["how"] else ""))
    return "\n".join(out)
