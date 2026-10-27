"""Action-needed email to Steven when the daily edition can't go out (Steven, 2026-10-19: "if there is an error
causing things to not run daily notify me on email if I need to take action and outline what the issue and action
need to be").

One email per issue per day, to the owner address only (email.test_to); the callers also show a Mac notification. Each email
says what happened, what is affected, and the exact commands to run.

Release gate: an alert is the one email that does NOT wait for the gate, because the gate being blocked is the most
common reason for one. That is safe because it can only go to the owner (Code.gs also limits recipients), its text is
built here from fixed templates plus the pipeline's own error messages (defused, no fetched content), and it is
checked by the email privacy gate like any other message. docs/security/RELEASE.md records this exception.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

STATE = "data/state/alerts.json"
REPO = "~/Developer/news-pipeline"

KINDS = {
    "approval": ("Approval needed before the briefing can go out",
                 "Security-sensitive files changed since your last release approval, so the release gate is holding "
                 "back the site, the podcast and the emails.",
                 ['cd {repo}', './np release-check approve "reviewed: <what changed>"', '{then}']),
    "approval-evening": ("Approval needed before tomorrow's briefing",
                         "Security-sensitive files changed since your last release approval, so the release gate is "
                         "holding back the site, the podcast and the emails.",
                         ['cd {repo}', './np release-check approve "reviewed: <what changed>"', '{then}']),
    "gate": ("The release gate failed a check",
             "A release-gate check other than the approval failed (tests, secrets scan, invariants or the output "
             "privacy scan), so nothing is published or emailed.",
             ['cd {repo}', './np release-check', 'then tell Claude "ran ./np release-check" so it can fix the failure']),
    "run": ("This morning's run did not produce a briefing",
            "The daily run finished without a briefing.",
            ['cd {repo}', './np daily', 'if it fails again, tell Claude "ran ./np daily"']),
    "publish": ("The site and podcast were not published",
                "The briefing was built but the publish step failed.",
                ['cd {repo}', './np publish', 'if it fails again, tell Claude "ran ./np publish"']),
    "audio": ("Part of today's podcast is missing or garbled",
              "The as-published check transcribed today's episode from the public feed and compared it with its "
              "script: a section was not heard (details below).",
              ['Listen to the start of today\'s episode', 'tell Claude "the listen check failed" in the chat: it can '
               're-voice the day from the same script']),
    "email": ("The subscriber email did not go out",
              "The briefing was built but sending the email failed.",
              ['cd {repo}', './np email send', 'if it fails again, tell Claude "ran ./np email send"']),
}


def _load(root: Path) -> dict:
    try:
        return json.loads((root / STATE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def already(root: Path, day: str, kind: str) -> bool:
    return bool(((_load(root).get(day) or {}).get(kind) or {}).get("sent"))


def _mark(root: Path, day: str, kind: str, ok: bool) -> None:
    d = _load(root)
    d = {k: v for k, v in d.items() if k >= (dt.date.fromisoformat(day) - dt.timedelta(days=14)).isoformat()}
    d.setdefault(day, {})[kind] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "sent": ok}
    p = root / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1) + "\n", "utf-8")


def build(kind: str, day: str, detail: str = "", files=(), next_try: str = "", when: str = "morning") -> dict:
    title, what, steps = KINDS[kind]
    then = ("that's all: the approval sends what was held back (site, podcast, email, your note)" if when == "morning"
            else "nothing else: tomorrow's 05:00 run will go out as normal")
    steps = [s.format(repo=REPO, then=then) for s in steps]
    if when == "evening":
        what = what.replace("is holding back", "will hold back tomorrow morning's")
    lines = [f"{title} ({day})", "", "What happened", what]
    if detail:
        lines += ["", "Details", detail.strip()[:900]]
    if files:
        lines += ["", "Changed files to review", *[f"- {f}" for f in list(files)[:20]],
                  f"(diff: cd {REPO} && git diff <last approved commit> -- <file>)"]
    lines += ["", "What to do (in Terminal)", *[f"{i}. {s}" for i, s in enumerate(steps, 1)]]
    if next_try:
        lines += ["", f"An automatic retry runs at {next_try}; it sends as soon as the problem is fixed."]
    lines += ["", "Sent by the news pipeline on your Mac. One email per issue per day."]
    text = "\n".join(lines)
    import html as h
    body = "".join(f"<p style='margin:0 0 6px'>{h.escape(l)}</p>" if l else "<br>" for l in lines)
    # the mail script only sends subjects that start with "AI Briefing" (Code.gs send action)
    return {"subject": f"AI Briefing · Action needed: {title.lower()} ({day})", "text": text,
            "html": f"<div style='font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px'>{body}</div>"}


def send(root: Path, cfg: dict, kind: str, day: str = "", detail: str = "", files=(), next_try: str = "",
         when: str = "morning", log=None) -> bool:
    """Email Steven once per (day, kind). -> True if an email went out now. (The caller shows the Mac notification.)"""
    log = log or print
    day = day or dt.date.today().isoformat()
    from .env import staging
    if staging(root):                                    # a blocked outbound step is expected in staging
        log(f"staging: {kind} alert not sent ({detail[:120]})")
        return False
    if already(root, day, kind):
        return False
    from . import mailer
    msg = build(kind, day, detail, files, next_try, when)
    msg["text"], msg["html"] = mailer.defuse(msg["text"]), mailer.defuse(msg["html"])
    to = (mailer.ecfg(cfg).get("test_to") or "").strip()
    ok = False
    try:
        if not to:
            raise mailer.MailError("email.test_to is not set")
        bad = mailer.privacy_gate({**msg, "to": to}, cfg)
        if bad:
            raise mailer.MailError("privacy gate: " + "; ".join(bad)[:200])
        out = mailer.call(cfg, "send", subject=msg["subject"], html=msg["html"], text=msg["text"], to=to, _alert=True)
        ok = bool(out.get("ok"))
    except Exception as e:  # noqa: BLE001 - the Mac notification below still fires
        log(f"alert email not sent: {e}")
    if ok:                                       # a failed attempt is retried by the next scheduled run
        _mark(root, day, kind, ok)
    log(f"alert: {kind} ({'emailed' if ok else 'notification only'})")
    return ok
