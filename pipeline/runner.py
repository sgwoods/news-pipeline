"""Run queue: Claude queues a named recipe, this Mac runs it, Steven decides (docs/plans/run-queue.md).

    data/queue/pending/<id>.json   a job: {"id", "recipe", "args": {...}, "chat_approval": "...", "queued_by"}
    data/queue/waiting/<id>.json   a job waiting for Approve in the dialog on this Mac
    data/queue/done/<id>.json      the job and its result: status, each step's exit code, log file and last lines

A launchd agent (`./np runner install`) ticks every minute and when a job file appears. Jobs are data: the runner
runs only the recipes below, with validated arguments, as argument lists (never a shell). Three tiers:

- auto: tests, staging sync / preview / compare, doctor, the gate's status, verify, consistency, critic-email
        (the weekly critic, to the owner only). Run as soon as queued.
- chat: corrections, publish, restore, takes-done (release a held edition now), source-add (verify a feed, wire it in), send-held (./np daily: publish and email a held edition). Need `chat_approval`: Steven's yes in the Claude chat, quoted.
- mac:  ship, release, rollback, release-check approve, public code push, git hooks, deploy-mailer (the mail script). Run only after Steven clicks
        Approve in a dialog on this Mac (or `./np runner approve ID` in Terminal). The click grants presence in
        memory for that job's approved steps only (pipeline/presence.py); nothing in a file can.

One job at a time. Jobs that change production wait out the morning run (03:30-08:30) and any run in progress.
The runner itself runs only in production, and only on released code (no code changes outside a release).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import io
import json
import os
import re
import subprocess
from pathlib import Path

QUEUE = "data/queue"
APPROVE = ("approve", [])                                  # the step at which a mac-tier job asks Steven
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}(?:-(?:beta|rc\d{0,2}))?$")
JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MORNING = (dt.time(3, 30), dt.time(8, 30))
RELEASE_WINDOW = (dt.time(8, 30), dt.time(20, 0))
REPROMPT = dt.timedelta(minutes=20)
DIALOG_SECONDS = 600                  # for the end-of-window check (no dialog if an answer would land after 20:00)
DIALOG_SHOWN = 1140                   # the dialog stays up 19 min; REPROMPT (20 min) asks again right after
PHONE_DIALOG = 90                     # with phone approvals on, the Mac dialog is short: the runner keeps ticking
PHONE_ITERATIONS = 300_000            # PBKDF2 rounds on the phone page (pipeline/runner.py phone_proof)
EARLIEST = dt.time(5, 0)              # once the morning edition is out, production jobs needn't wait for 08:30
APPROVED = "data/queue/approved"      # early approvals, signed with a key in this Mac's Keychain (see below)
STEP_TIMEOUT = 3600
MAX_JOB_BYTES = 8192

# step: (where, argv) where "dev" / "prod" run ./np in that checkout and "local" calls a function run.py provides.
# "{day}", "{note}", "{version}" are replaced by the job's validated arguments; an empty optional one is dropped.
RECIPES = {
    "tests":   {"tier": "auto", "args": {}, "steps": [("dev", ["tests"])]},
    "sync":    {"tier": "auto", "args": {}, "steps": [("dev", ["staging", "sync"])]},
    "preview": {"tier": "auto", "args": {"day": "day?"},
                "steps": [("dev", ["staging", "run", "{day}"]), ("dev", ["staging", "publish"])]},
    "compare": {"tier": "auto", "args": {"day": "day?"}, "steps": [("dev", ["staging", "compare", "{day}"])]},
    "doctor":  {"tier": "auto", "args": {}, "steps": [("prod", ["doctor"])]},
    "gate":    {"tier": "auto", "args": {}, "steps": [("prod", ["release-check"])]},
    "consistency": {"tier": "auto", "args": {"day": "day?"}, "steps": [("prod", ["consistency", "{day}"])]},
    "verify":  {"tier": "auto", "args": {}, "steps": [("local", ["verify"])]},
    "correct": {"tier": "chat", "args": {"day": "day", "note": "text"},
                "steps": [("prod", ["correct", "{day}", "{note}"]), ("prod", ["publish"]), ("local", ["verify"])]},
    "publish": {"tier": "chat", "args": {}, "steps": [("prod", ["publish"]), ("local", ["verify"])]},
    "remaster": {"tier": "auto", "args": {"day": "day", "note": "text"},   # re-record DAY's podcast from its corrected
                 "steps": [("prod", ["remaster", "{day}", "--correct", "{note}"]), ("local", ["verify"])]},  # text
    "restore": {"tier": "chat", "args": {}, "steps": [("prod", ["publish", "restore"]), ("local", ["verify"])]},
    "takes-done": {"tier": "chat", "args": {}, "steps": [("prod", ["takes", "done"])]},
    "takes-test": {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["takes", "test", "{day}"])]},
    "takes-check": {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["takes", "check", "{day}"])]},
    "drive-save": {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["drive", "save", "{day}"])]},
    "audio-check": {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["audio-check", "{day}"])]},
    "audit":   {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["audit", "{day}"])]},
    "audit-deepdive": {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["audit", "deepdive", "{day}"])]},
    "positions-score": {"tier": "auto", "args": {"day": "day?"}, "steps": [("prod", ["positions", "score", "{day}"])]},
    "setup": {"tier": "chat", "args": {}, "steps": [("prod", ["setup"])]},     # install requirements.txt
    "email-remind": {"tier": "chat", "args": {"emails": "emails?"}, "steps": [("prod", ["email", "remind", "{emails}"])]},
    "email-remove": {"tier": "chat", "args": {"email": "email"}, "steps": [("prod", ["email", "remove", "{email}"])]},
    "takes-sync": {"tier": "auto", "args": {"day": "day"},    # Steven edited today's Doc(s): apply, re-publish, rewrite the Docs
                   "steps": [("prod", ["takes", "apply", "{day}"]), ("prod", ["publish"]), ("prod", ["drive", "save", "{day}"]),
                             ("local", ["verify"])]},
    "takes-apply": {"tier": "chat", "args": {"day": "day"},
                    "steps": [("prod", ["takes", "apply", "{day}"]), ("prod", ["publish"]), ("local", ["verify"])]},
    "send-held": {"tier": "chat", "args": {}, "steps": [("prod", ["daily"]), ("local", ["verify"])]},
    "critic-email": {"tier": "auto", "args": {"date": "day?"}, "steps": [("prod", ["critic", "email", "{date}"])]},
    "source-add": {"tier": "chat", "args": {"name": "text", "url": "url", "url2": "url?", "note": "text?"},
                   "steps": [("prod", ["sources", "add", "{name}", "{url}", "{url2}", "{note}"])]},
    # ship (v0.2.33): lane "" / "slot" = the weekday 13:00 slot, once a day; lane "fix" = something is broken, any
    # time in the release window. Before Approve, a soak: today's edition rebuilt with the dev code and compared with
    # production; a compare that needs review (exit 3) stops the ship unless "accept" quotes Steven's OK. The soak passes
    # --force: a ship only runs once the morning edition is out and no run is busy (10-31: it refused before 08:30).
    "ship":    {"tier": "mac", "args": {"version": "version", "note": "reviewed", "lane": "lane?", "accept": "accepted?"},
                "steps": [("dev", ["staging", "sync"]), ("dev", ["tests"]), ("dev", ["staging", "run", "--force"]),
                          ("dev", ["staging", "compare"]), APPROVE,
                          ("local", ["release", "{version}", "{note}"]), ("local", ["verify"]),
                          ("local?", ["follow-through", "{note}"])]},   # public export + mail script, same Approve
    "release": {"tier": "mac", "args": {"version": "version", "note": "reviewed"},
                "steps": [APPROVE, ("local", ["release", "{version}", "{note}"]), ("local", ["verify"])]},
    "rollback": {"tier": "mac", "args": {"note": "reviewed"},
                 "steps": [APPROVE, ("local", ["rollback", "{note}"]), ("local", ["verify"])]},
    "approve": {"tier": "mac", "args": {"note": "reviewed"},
                "steps": [APPROVE, ("local", ["approve", "{note}"])]},   # approve re-runs the gate and refuses
                                                                  # if any check but the approval fails (10-26)
    "install-hooks": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["install-hooks"])]},
    "phone-setup": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["phone-setup"])]},   # the passphrase
    "ntfy-setup": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["ntfy-setup"])]},     # phone notifications
    "ntfy-test": {"tier": "auto", "args": {}, "steps": [("prod", ["ntfy", "test"])]},
    "advance": {"tier": "auto", "args": {}, "steps": [("prod", ["advance"])]},   # draft tomorrow's deep dive now
    "service-install": {"tier": "chat", "args": {"kind": "text"}, "steps": [("prod", ["service", "install", "{kind}"])]},
    "slack-setup": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["slack-setup"])]},   # the bot token
    "jev-setup": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["jev-setup"])]},       # the TypeSafe key
    "jev-report": {"tier": "auto", "args": {}, "steps": [("prod", ["jev", "report"])]},
    "deepdive-rebuild": {"tier": "auto", "args": {"day": "day", "topic": "text", "note": "text"},   # rewrite a shipped dive
                         "steps": [("prod", ["deepdive", "{day}", "--topic", "{topic}", "--force"]),
                                   ("prod", ["correct", "{day}", "{note}"]), ("prod", ["publish"]), ("local", ["verify"])]},
    "x-probe": {"tier": "auto", "args": {}, "steps": [("prod", ["x", "probe", "3"])]},
    "slack-card": {"tier": "auto", "args": {"day": "day"}, "steps": [("prod", ["slack-post", "preview", "{day}"])]},
    "slack-post": {"tier": "chat", "args": {"day": "day"}, "steps": [("prod", ["slack-post", "send", "{day}"])]},
    "slack-archive": {"tier": "chat", "args": {"from": "day", "to": "day"},
                      "steps": [("prod", ["slack-post", "archive", "{from}", "{to}"])]},
    "slack-deepdive": {"tier": "chat", "args": {"day": "day"}, "steps": [("prod", ["slack-post", "deepdive", "{day}"])]},
    "deploy-mailer": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["deploy-mailer"]),
                                                         ("prod", ["mailer", "status"])]},
    "mailer-status": {"tier": "auto", "args": {}, "steps": [("prod", ["mailer", "status"])]},
    "mailer-setup": {"tier": "chat", "args": {"script": "text"}, "steps": [("prod", ["mailer", "setup", "{script}"])]},
}
CHANGES_PRODUCTION = {"setup", "correct", "publish", "remaster", "deepdive-rebuild", "restore", "ship", "release", "rollback", "approve", "install-hooks",
                      "push-code", "source-add", "send-held", "takes-apply", "takes-sync", "deploy-mailer", "slack-post", "slack-deepdive", "slack-archive", "service-install"}
IN_RELEASE_WINDOW = {"ship", "release"}
# Steven, 2026-10-31: "pull approvals forward to the beginning of a task". A ship or release carrying his yes from
# chat (asked when the task starts, answerable in the Claude iOS app) needs no tap: it runs on its own once tests and
# the soak pass, and he gets a notification after. Rollback, the public code push and secrets keep the tap.
CHAT_APPROVES = {"ship", "release"}
NEEDS_APPROVAL = {"release", "rollback", "approve", "install-hooks", "push-code", "deploy-mailer", "phone-setup", "ntfy-setup",
                  "slack-setup", "jev-setup"}   # local steps behind the click


class JobError(ValueError):
    pass


def recipe_problems(recipes: dict = RECIPES) -> list:
    """Release invariant 10: every step that needs a person is in a mac-tier recipe, after its Approve step."""
    bad = []
    for name, r in recipes.items():
        seen_approve = False
        for step in r["steps"]:
            if step == APPROVE:
                seen_approve = True
                if r["tier"] != "mac":
                    bad.append(f"{name}: an Approve step outside the mac tier")
                continue
            where, argv = step
            if where not in ("dev", "prod", "local", "local?"):
                bad.append(f"{name}: unknown place {where}")
            if where in ("local", "local?") and (argv[0] in NEEDS_APPROVAL or argv[0] == "follow-through") \
                    and not (r["tier"] == "mac" and seen_approve):
                bad.append(f"{name}: {argv[0]} runs without Steven's Approve")
            if where in ("dev", "prod") and argv[0] in ("release", "rollback", "push-code", "release-check") \
                    and len(argv) > 1:
                bad.append(f"{name}: {argv[0]} with arguments must be a local step after Approve")
        if r["tier"] == "mac" and not seen_approve:
            bad.append(f"{name}: mac tier without an Approve step")
    return bad


def _text(v, cap: int) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > cap:
        raise JobError(f"text must be 1-{cap} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in v):
        raise JobError("text may not contain line breaks or control characters")
    return v.strip()


def validate(job: dict, name: str = "") -> dict:
    """The job, checked: known recipe, exactly its arguments, each in its shape. Raises JobError."""
    if not isinstance(job, dict):
        raise JobError("a job is a JSON object")
    jid = str(job.get("id", ""))
    if not JOB_ID.match(jid):
        raise JobError("id: letters, digits, . _ - (up to 64)")
    if name and name != f"{jid}.json":
        raise JobError(f"file name {name} doesn't match id {jid}")
    recipe = job.get("recipe")
    if recipe not in RECIPES:
        raise JobError(f"unknown recipe {recipe!r}: one of {', '.join(RECIPES)}")
    spec = RECIPES[recipe]["args"]
    args = job.get("args") or {}
    if not isinstance(args, dict) or set(args) - set(spec):
        raise JobError(f"{recipe} takes {', '.join(spec) or 'no arguments'}")
    clean = {}
    for k, kind in spec.items():
        v = args.get(k, "")
        if kind.endswith("?") and v in ("", None):
            clean[k] = ""
            continue
        kind = kind.rstrip("?")
        if kind == "day":
            if not isinstance(v, str) or not DAY.match(v):
                raise JobError(f"{k}: YYYY-MM-DD")
            try:
                dt.date.fromisoformat(v)
            except ValueError as e:
                raise JobError(f"{k}: {e}") from e
        elif kind == "version":
            if not isinstance(v, str) or not VERSION.match(v.lstrip("v")):
                raise JobError(f"{k}: like 0.1.12-beta")
            v = v.lstrip("v")
        elif kind == "url":
            if not isinstance(v, str) or not re.fullmatch(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:[/?#][^\s<>\"']*)?", v) \
                    or len(v) > 300:
                raise JobError(f"{k}: an https:// URL")
        elif kind in ("email", "emails"):            # one address, or a comma-separated list of them
            parts = [x.strip().lower() for x in str(v).split(",") if x.strip()] if isinstance(v, str) else []
            if not parts or (kind == "email" and len(parts) != 1) or len(parts) > 50 or \
                    not all(re.fullmatch(r"[^\s@<>\"',]+@[^\s@<>\"',]+\.[A-Za-z]{2,}", x) for x in parts):
                raise JobError(f"{k}: an email address" + ("" if kind == "email" else " or a comma-separated list"))
            v = ",".join(parts)
        elif kind == "lane":
            if v not in ("slot", "fix"):
                raise JobError(f'{k}: "slot" (the daily 13:00 release) or "fix" (something is broken)')
        elif kind == "accepted":
            v = _text(v, 300)
            if not v.lower().startswith("accepted"):
                raise JobError(f'{k} must start with "accepted:" and quote Steven\'s OK in chat')
        elif kind == "reviewed":
            v = _text(v, 300)
            if not v.lower().startswith("reviewed"):
                raise JobError(f'{k} must start with "reviewed:"')
        else:
            v = _text(v, 300)
        clean[k] = v
    out = {"id": jid, "recipe": recipe, "args": clean, "queued_by": str(job.get("queued_by", ""))[:40],
           "queued_at": str(job.get("queued_at", ""))[:40]}
    if RECIPES[recipe]["tier"] == "chat":
        out["chat_approval"] = _text(job.get("chat_approval", ""), 500)
    elif job.get("chat_approval"):
        out["chat_approval"] = str(job["chat_approval"])[:500]
    return out


def argv_for(step_argv: list, args: dict) -> list:
    out = []
    for a in step_argv:
        m = re.fullmatch(r"\{(\w+)\}", a)
        if m:
            v = args.get(m.group(1), "")
            if v:
                out.append(v)
        else:
            out.append(a)
    return out


# ---------------------------------------------------------------- the queue on disk
def qdir(root: Path, name: str) -> Path:
    d = root / QUEUE / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(p: Path) -> dict:
    if p.stat().st_size > MAX_JOB_BYTES:
        raise JobError("job file too large")
    try:
        return json.loads(p.read_text("utf-8"))
    except ValueError as e:
        raise JobError(f"not JSON: {e}") from e


def _write(p: Path, data: dict):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", "utf-8")
    tmp.replace(p)


def _finish(root: Path, src: Path, job: dict, status: str, detail: str = "", notify=None):
    job.update({"status": status, "detail": detail[:500], "ended": dt.datetime.now().isoformat(timespec="seconds")})
    _write(qdir(root, "done") / f"{job['id']}.json", job)
    if src.exists() and src.parent.name != "done":
        src.rename(qdir(root, "done") / f"{job['id']}.queued.json")
    if notify:
        notify(f"{job['recipe']} {status}", detail or job["id"])
    _status(root)


def _status(root: Path):
    done = sorted(qdir(root, "done").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    last = []
    for p in done:
        if p.name.endswith(".queued.json"):
            continue
        try:
            j = json.loads(p.read_text("utf-8"))
            last.append({k: j.get(k) for k in ("id", "recipe", "status", "detail", "ended")})
        except ValueError:
            pass
        if len(last) >= 10:
            break
    _write(root / QUEUE / "status.json", {
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "pending": sorted(p.stem for p in qdir(root, "pending").glob("*.json")),
        "waiting": sorted(p.stem for p in qdir(root, "waiting").glob("*.json")),
        "last": last})


# ---------------------------------------------------------------- running steps
def clean_env() -> dict:
    drop = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "NP_ENV", "NP_TESTING")
    return {k: v for k, v in os.environ.items() if k not in drop}


def run_np(root: Path, argv: list, log: Path, timeout: int = STEP_TIMEOUT) -> int:
    """./np ARGV in that checkout, as an argument list (never a shell)."""
    with log.open("a", encoding="utf-8") as f:
        f.write(f"$ ./np {' '.join(argv)}  (in {root.name})\n")
        f.flush()
        try:
            r = subprocess.run(["/bin/bash", str(root / "np"), *argv], cwd=root, env=clean_env(), stdout=f,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout)
            return r.returncode
        except subprocess.TimeoutExpired:
            f.write(f"\n(timed out after {timeout}s)\n")
            return 124


def run_local(fn, name: str, argv: list, log: Path) -> int:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = fn(argv)
    except Exception as e:  # noqa: BLE001
        buf.write(f"\nerror: {type(e).__name__}: {e}\n")
        code = 1
    with log.open("a", encoding="utf-8") as f:
        f.write(f"$ {name} {' '.join(argv)}  (in-process)\n{buf.getvalue()}\n")
    return int(code or 0)


def _tail(log: Path, n: int = 25) -> list:
    try:
        return log.read_text("utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def ask_mac(job: dict, summary: str, seconds: int = DIALOG_SHOWN) -> str:
    """The approval dialog on this Mac: 'approve', 'reject' or 'timeout'. The text goes in as an argument."""
    msg = (("Approve now? It runs as soon as the morning edition is out.\n\n" if job.get("early") else "") +
           f"Approve this run-queue job?\n\n{job['recipe']} {' '.join(v for v in job['args'].values() if v)}\n\n"
           f"{summary}\n\nQueued by {job.get('queued_by') or '?'} · {job['id']}")[:1800]
    script = ['on run argv', 'display dialog (item 1 of argv) with title "AI Briefing · approval" '
              'buttons {"Reject", "Approve"} default button "Reject" cancel button "Reject" '
              f'giving up after {int(seconds)} with icon caution', 'end run']
    args = ["osascript"] + sum((["-e", s] for s in script), []) + [msg]
    notify_mac("approval waiting", f"{job['recipe']}: Approve in the dialog", sound=True)   # heard, not just seen
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=seconds + 30)
    except (OSError, subprocess.TimeoutExpired):
        return "timeout"
    if r.returncode != 0:
        return "reject" if "-128" in (r.stderr or "") else "timeout"
    if "gave up:true" in r.stdout:
        return "timeout"
    return "approve" if "button returned:Approve" in r.stdout else "reject"


def approval_key() -> bytes:
    """The early-approval key: Keychain only (never .env, which the VM can read). Made on first use; b"" if none."""
    import secrets
    from .vault import _keychain, set_keychain
    k = _keychain("NP_APPROVAL_KEY")
    if not k and set_keychain("NP_APPROVAL_KEY", secrets.token_hex(32)):
        k = _keychain("NP_APPROVAL_KEY")
    if not k:
        raise RuntimeError("no Keychain: early approvals are off")
    return k.encode()


# ---- phone approvals (Steven, 2026-10-27: approve from the iOS app, not only at the Mac) ----
# When a mac-tier job reaches its Approve step, the runner emails Steven a one-time link (the mail script's approve
# page). He types his approval passphrase there and taps Approve or Reject. The page never sends the passphrase: it
# sends proof = HMAC(PBKDF2(passphrase, nonce), "answer|job id"), and only this Mac, which keeps the passphrase in
# its Keychain, can check it. The nonce is an HMAC of the job's fingerprint and today's date under the early-
# approval key, so a link is good for that job and that day only. Claude and the VM can read the email and the mail
# script's records but not the Keychain, so neither can produce a proof. Set the passphrase with the phone-setup
# job (a Mac dialog).

def phone_proof(passphrase: str, nonce: str, answer: str, job_id: str) -> str:
    import hashlib
    import hmac
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), nonce.encode(), PHONE_ITERATIONS, 32)
    return hmac.new(derived, f"{answer}|{job_id}".encode(), hashlib.sha256).hexdigest()


def phone_secret() -> str:
    from .vault import _keychain
    return _keychain("NP_APPROVAL_PHRASE")


def set_phone_secret(ask=None) -> str:
    """The phone-setup job: a Mac dialog (hidden answer, twice) stores the approval passphrase in the Keychain."""
    from .vault import set_keychain

    def ask_hidden(prompt: str) -> str:
        script = ['on run argv', 'set r to display dialog (item 1 of argv) default answer "" with hidden answer '
                  'with title "AI Briefing · phone approvals" buttons {"Cancel", "Save"} default button "Save" '
                  'cancel button "Cancel"', 'return text returned of r', 'end run']
        r = subprocess.run(["osascript"] + sum((["-e", s] for s in script), []) + [prompt],
                           capture_output=True, text=True, timeout=600)
        return r.stdout.strip() if r.returncode == 0 else ""
    ask = ask or ask_hidden
    one = ask("Choose a passphrase for approving from your phone (at least 10 characters). You'll type it on "
              "the approval page; your phone's password manager can keep it. It stays in this Mac's Keychain.")
    if len(one) < 10:
        return "not saved: at least 10 characters"
    if ask("Type the passphrase again.") != one:
        return "not saved: the two didn't match"
    return "saved" if set_keychain("NP_APPROVAL_PHRASE", one) else "not saved: the Keychain refused it"


class Phone:
    """send(job_id, nonce, title, summary) -> bool; poll(ids) -> {id: {"answer", "proof", "at"}}; secret() -> str.
    kind "passphrase": proof = phone_proof(passphrase, nonce, answer, id) (the mail script's approve page).
    kind "ntfy": proof = the nonce itself, sent back by a tap on the notification (pipeline/ntfy.py)."""

    def __init__(self, send, poll, secret=None, kind="passphrase"):
        self.send, self.poll, self.secret, self.kind = send, poll, secret or (lambda: ""), kind


def notify_mac(title: str, text: str, sound: bool = False):
    script = ['on run argv', 'display notification (item 2 of argv) with title (item 1 of argv)'
              + (' sound name "Glass"' if sound else ''), 'end run']
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(["osascript"] + sum((["-e", s] for s in script), []) + [f"AI Briefing · {title}", text[:200]],
                       capture_output=True, timeout=15)


class Runner:
    """One pass over the queue. `local` maps local step names to functions run.py provides (argv -> exit code)."""

    def __init__(self, root: Path, dev: Path, local: dict, now=None, ask=ask_mac, notify=notify_mac,
                 busy=None, summary=None, sent_today=None, key=None, phone=None, slot=None):
        self.root, self.dev, self.local = root, dev, local
        self.now = now or dt.datetime.now
        self.ask, self.notify = ask, notify
        self.busy = busy or (lambda: False)               # a production run in progress
        self.summary = summary or (lambda job: "")
        self.sent_today = sent_today or (lambda: False)   # today's edition is out (published and emailed)
        self.key = key                                    # () -> bytes: the early-approval key (Keychain); None = off
        self.phone = phone if (phone and key) else None    # Phone: approve from the phone (needs the key too)
        self.slot = slot                                  # dt.time: the daily release slot; None = no lane rules

    def _edition_out(self) -> bool:
        """The morning is done: today's edition went out and no run is busy (v0.2.13: no waiting for 08:30)."""
        return self.now().time() >= EARLIEST and not self.busy() and bool(self.sent_today())

    def _release_open(self) -> bool:
        t = self.now().time()
        return RELEASE_WINDOW[0] <= t <= RELEASE_WINDOW[1] or (t <= RELEASE_WINDOW[1] and self._edition_out())

    def _slot_used(self, job: dict) -> bool:
        """A slot ship already went out today (one batched release a day)."""
        today = self.now().date().isoformat()
        for p in qdir(self.root, "done").glob("*.json"):
            if p.name.endswith(".queued.json") or p.stem == job["id"]:
                continue
            try:
                j = json.loads(p.read_text("utf-8"))
            except (ValueError, OSError):
                continue
            if j.get("recipe") == "ship" and j.get("status") == "ok" and (j.get("args") or {}).get("lane") != "fix" \
                    and str(j.get("started") or j.get("ended") or "").startswith(today):
                return True
        return False

    def lane_closed(self, job: dict) -> str:
        """Why a slot ship can't go today at all (weekend, or today's slot used); "" when it can."""
        if self.slot is None or job["recipe"] != "ship" or job["args"].get("lane") == "fix":
            return ""
        if self.now().weekday() >= 5:
            return "slot releases are weekdays only; queue it Monday, or lane fix if something is broken"
        if self._slot_used(job):
            return "today's release slot is used; queue it for the next weekday, or lane fix if something is broken"
        return ""

    def _defer(self, job: dict) -> str:
        t = self.now().time()
        if self.slot and job["recipe"] == "ship" and job["args"].get("lane") != "fix" and t < self.slot:
            return f"the daily release slot opens at {self.slot.strftime('%H:%M')}"
        if job["recipe"] in CHANGES_PRODUCTION and (self.busy() or (MORNING[0] <= t < MORNING[1] and not self._edition_out())):
            return "the morning run's window or a run in progress"
        if job["recipe"] in IN_RELEASE_WINDOW and not self._release_open():
            return "releases go out 08:30-20:00 (earlier once the morning edition is out)"
        return ""

    # ---- early approvals: Approve while the job still waits for the morning to finish (v0.2.13) ----
    # The click is kept as an HMAC over the job (id, recipe, args) and today's date, keyed by a secret in this
    # Mac's Keychain. Claude and the VM can write files in data/ but can't read the Keychain, so a file alone
    # can't stand in for the click. It is used once, and only today.
    def _fingerprint(self, job: dict) -> str:
        import hashlib
        return hashlib.sha256(json.dumps({"id": job["id"], "recipe": job["recipe"], "args": job["args"]},
                                         sort_keys=True).encode()).hexdigest()

    def _sign(self, job: dict, day: str) -> str:
        import hmac
        import hashlib
        return hmac.new(self.key(), f"{self._fingerprint(job)}|{day}".encode(), hashlib.sha256).hexdigest()

    def _approval_path(self, job: dict) -> Path:
        return self.root / APPROVED / f"{job['id']}.json"

    def approve_early(self, job: dict):
        day = self.now().date().isoformat()
        p = self._approval_path(job)
        p.parent.mkdir(parents=True, exist_ok=True)
        _write(p, {"id": job["id"], "day": day, "at": self.now().isoformat(timespec="seconds"), "sig": self._sign(job, day)})

    def approved_early(self, job: dict) -> bool:
        import hmac
        if not self.key:
            return False
        try:
            a = json.loads(self._approval_path(job).read_text("utf-8"))
        except (OSError, ValueError):
            return False
        day = self.now().date().isoformat()
        try:
            ok = a.get("day") == day and hmac.compare_digest(str(a.get("sig", "")), self._sign(job, day))
        except Exception:  # noqa: BLE001 - no key, no early approval
            return False
        return ok

    # ---- phone approvals ----
    def _nonce(self, job: dict) -> str:
        return self._sign(job, self.now().date().isoformat() + "|phone")[:40]

    def _phone_send(self, job: dict, raw: dict, src: Path) -> None:
        """Email the approval link once per job and day (it is good for today only)."""
        if not self.phone:
            return
        day = self.now().date().isoformat()
        if raw.get("phone_sent") == day:
            return
        title = f"{job['recipe']} {' '.join(v for v in job['args'].values() if v)}"[:160]
        try:
            ok = self.phone.send(job["id"], self._nonce(job), title, self.summary(job)[:1400])
        except Exception:  # noqa: BLE001 - the Mac dialog still works
            ok = False
        if ok:
            raw["phone_sent"] = day
            job["phone_sent"] = day
            _write(src, {**raw, **{k: job[k] for k in ("phone_sent",)}})

    def _phone_answer(self, job: dict, src: Path | None = None) -> str:
        """'approve' or 'reject' when the phone page sent a valid proof for this job today; else ''. Why not is kept
        in the job file (phone_check), and a proof that doesn't match gets one Mac notification per answer."""
        import hmac
        if not self.phone or job.get("phone_sent") != self.now().date().isoformat():
            return ""

        def note(result: str, at: str = ""):
            job["phone_check"] = {"at": self.now().isoformat(timespec="seconds"), "result": result[:200], "answered": at}
            if src is not None:
                with contextlib.suppress(OSError, ValueError):
                    _write(src, {**_load(src), "phone_check": job["phone_check"]})
        try:
            got = (self.phone.poll([job["id"]]) or {}).get(job["id"]) or {}
        except Exception as e:  # noqa: BLE001
            note(f"poll failed: {type(e).__name__}: {e}")
            return ""
        try:
            secret = self.phone.secret()
        except Exception as e:  # noqa: BLE001
            note(f"no passphrase: {type(e).__name__}")
            return ""
        a, proof = str(got.get("answer", "")), str(got.get("proof", ""))
        if not got:
            note("no answer yet")
            return ""
        if a not in ("approve", "reject") or not (20 <= len(proof) <= 64):
            note(f"malformed answer ({a!r}, proof length {len(proof)})", str(got.get("at", "")))
            return ""
        if self.phone.kind == "ntfy":
            if not hmac.compare_digest(proof, self._nonce(job)):
                note("the tap's token doesn't match this job", str(got.get("at", "")))
                return ""
            return a
        if not secret:
            note("no passphrase in the Keychain")
            return ""
        if not hmac.compare_digest(proof, phone_proof(secret, self._nonce(job), a, job["id"])):
            seen = (job.get("phone_check") or {}).get("answered")
            note("proof does not match: the passphrase typed on the phone differs from the Mac's", str(got.get("at", "")))
            if seen != got.get("at") and self.notify:
                self.notify("phone approval", f"{job['recipe']}: the passphrase didn't match. Open the link again.")
            return ""
        return a

    def _dialog(self, job: dict, summary: str) -> str:
        if self.phone:
            try:
                return self.ask(job, summary, PHONE_DIALOG)
            except TypeError:
                pass
        return self.ask(job, summary)

    def _use_early(self, job: dict):
        with contextlib.suppress(OSError):
            self._approval_path(job).unlink()

    def _step(self, job: dict, i: int, step, log: Path) -> int:
        where, argv = step
        argv = argv_for(argv, job["args"])
        if where in ("local", "local?"):
            fn = self.local.get(argv[0])
            if fn is None and where == "local?":         # optional: a checkout without it skips the step
                return 0
            if fn is None:
                with log.open("a", encoding="utf-8") as f:
                    f.write(f"no local step {argv[0]}\n")
                return 1
            return run_local(fn, argv[0], argv[1:], log)
        code = run_np(self.dev if where == "dev" else self.root, argv, log)
        if code == 3 and argv[:2] == ["staging", "compare"] and job["args"].get("accept"):
            with log.open("a", encoding="utf-8") as f:
                f.write(f"compare needs review; going on: {job['args']['accept']}\n")
            return 0
        return code

    def _run_steps(self, job: dict, steps: list, start: int, log: Path) -> int:
        for i, step in enumerate(steps[start:], start):
            code = self._step(job, i, step, log)
            job.setdefault("steps", []).append({"step": i, "what": " ".join(argv_for(step[1], job["args"]))[:200],
                                                "where": step[0], "code": code})
            if code:
                return code
        return 0

    def _run_approved(self, job: dict, steps: list, start: int, log: Path, how: str) -> int:
        from .presence import granted
        job["approved"] = {"how": how, "at": self.now().isoformat(timespec="seconds")}
        with granted(job["id"]):
            return self._run_steps(job, steps, start, log)

    def run_job(self, src: Path, terminal: bool = False) -> str:
        try:
            raw = _load(src)
            job = validate(raw, src.name)
        except (JobError, OSError) as e:
            jid = JOB_ID.match(src.stem) and src.stem or f"invalid-{int(self.now().timestamp())}"
            _finish(self.root, src, {"id": jid, "recipe": "?", "args": {}}, "invalid", str(e), self.notify)
            return "invalid"
        for k in ("steps", "phase", "prompted_at", "started", "phone_sent", "phone_check"):
            if k in raw:
                job[k] = raw[k]
        closed = self.lane_closed(job)
        if closed:
            _finish(self.root, src, job, "expired", closed, self.notify)
            return "expired"
        why = self._defer(job)
        if why:
            job["deferred"] = why
            _write(src, {**raw, "deferred": why})
            r0 = RECIPES[job["recipe"]]
            chat_ok = job["recipe"] in CHAT_APPROVES and job.get("chat_approval")
            if APPROVE in r0["steps"] and self.key and not chat_ok and not self.approved_early(job) and \
                    self.now().time() < RELEASE_WINDOW[1]:       # ask now; it runs when the morning is done
                self._phone_send(job, raw, src)
                pa = self._phone_answer(job, src)
                if pa == "approve":
                    self.approve_early(job)
                    return "deferred (approved)"
                if pa == "reject":
                    _finish(self.root, src, job, "rejected", "Steven tapped Reject on his phone", self.notify)
                    return "rejected"
                last = raw.get("prompted_at")
                if not last or self.now() - dt.datetime.fromisoformat(last) >= REPROMPT:
                    _write(src, {**raw, "deferred": why, "prompted_at": self.now().isoformat(timespec="seconds")})
                    if self._dialog({**job, "early": True}, "Approve now: it runs as soon as the morning edition is out "
                                "(or at 08:30).\n\n" + self.summary(job)) == "approve":
                        self.approve_early(job)
                        return "deferred (approved)"
            return "deferred"
        r = RECIPES[job["recipe"]]
        steps = r["steps"]
        log = self.root / "logs" / f"runner-{job['id']}.txt"
        log.parent.mkdir(exist_ok=True)
        job.setdefault("started", self.now().isoformat(timespec="seconds"))
        cut = steps.index(APPROVE) if APPROVE in steps else len(steps)
        if job.get("phase") != "approval":
            code = self._run_steps(job, steps[:cut], 0, log)
            if code:
                job["log"] = str(log.relative_to(self.root))
                job["tail"] = _tail(log)
                _finish(self.root, src, job, "failed", f"step {len(job['steps'])} exited {code}", self.notify)
                return "failed"
        if cut < len(steps):                               # mac tier: Steven decides here
            end = dt.datetime.combine(self.now().date(), RELEASE_WINDOW[1])
            if job["recipe"] in IN_RELEASE_WINDOW and not terminal and \
                    self.now() + dt.timedelta(seconds=DIALOG_SECONDS) > end:
                job["phase"] = "approval"                  # an answer would land after 20:00: don't ask tonight
                dst = qdir(self.root, "waiting") / src.name
                _write(dst, job)
                if src != dst:
                    src.unlink()
                return "waiting"
            if terminal:
                answer = "approve"
            elif job["recipe"] in CHAT_APPROVES and job.get("chat_approval"):
                answer = "approve"
                job["approved_by"] = "chat"
            elif self.approved_early(job):
                answer, terminal = "approve", False
                job["approved_early"] = True
                self._use_early(job)
            elif (pa := (self._phone_send(job, raw, src) or self._phone_answer(job, src))):
                answer, terminal = pa, False
                job["approved_by"] = "phone"
            else:
                last = job.get("prompted_at")
                if last and self.now() - dt.datetime.fromisoformat(last) < REPROMPT:
                    return "waiting"
                job["prompted_at"] = self.now().isoformat(timespec="seconds")
                answer = self._dialog(job, self.summary(job))
            if answer == "timeout":
                job["phase"] = "approval"
                dst = qdir(self.root, "waiting") / src.name
                _write(dst, job)
                if src != dst:
                    src.unlink()
                _status(self.root)
                return "waiting"
            if answer != "approve":
                job["log"] = str(log.relative_to(self.root))
                _finish(self.root, src, job, "rejected", "Steven clicked Reject", self.notify)
                return "rejected"
            if job["recipe"] in IN_RELEASE_WINDOW and not self._release_open():
                job["log"] = str(log.relative_to(self.root))
                _finish(self.root, src, job, "expired", "approved after the 08:30-20:00 release window; queue it "
                        "again in the window", self.notify)
                return "expired"
            code = self._run_approved(job, steps, cut + 1, log, "terminal" if terminal else
                                      "chat: " + job["chat_approval"][:200] if job.get("approved_by") == "chat" else
                                      "phone" if job.get("approved_by") == "phone" else
                                      "dialog (early)" if job.get("approved_early") else "dialog")
        else:
            code = 0
        job["log"] = str(log.relative_to(self.root))
        job["tail"] = _tail(log)
        status = "ok" if not code else "failed"
        _finish(self.root, src, job, status, "" if not code else f"exited {code}", self.notify)
        return status

    def expire(self):
        """Waiting jobs lapse at the end of the release window: approvals never sit overnight."""
        for p in qdir(self.root, "waiting").glob("*.json"):
            if self.now().time() > RELEASE_WINDOW[1]:
                try:
                    job = json.loads(p.read_text("utf-8"))
                except ValueError:
                    job = {"id": p.stem, "recipe": "?", "args": {}}
                _finish(self.root, p, job, "expired", "not approved by 20:00; queue it again tomorrow", self.notify)

    def tick(self) -> list:
        from .env import staging
        lock = (self.root / QUEUE)
        lock.mkdir(parents=True, exist_ok=True)
        with open(lock / "runner.lock", "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return ["busy"]
            if staging(self.root):
                return ["the run queue runs only in the production folder"]
            dirty = code_changes(self.root)
            jobs = sorted(qdir(self.root, "pending").glob("*.json")) + sorted(qdir(self.root, "waiting").glob("*.json"))
            if dirty and jobs:
                for p in jobs:
                    try:
                        job = validate(_load(p), p.name)
                    except (JobError, OSError):
                        job = {"id": p.stem, "recipe": "?", "args": {}}
                    _finish(self.root, p, job, "refused", "production has code changes outside a release: " +
                            dirty[:200], self.notify)
                return ["refused: production code changed outside a release"]
            self.expire()
            out = []
            for p in sorted(qdir(self.root, "pending").glob("*.json")) + sorted(qdir(self.root, "waiting").glob("*.json")):
                out.append(f"{p.stem}: {self.run_job(p)}")
            _status(self.root)
            return out


def code_changes(root: Path) -> str:
    from .releaser import CODE_PATHS
    r = subprocess.run(["git", "status", "--porcelain", "--", *CODE_PATHS], cwd=root, capture_output=True, text=True,
                       env=clean_env())
    return r.stdout.strip()


def enqueue(root: Path, recipe: str, args: dict | None = None, chat_approval: str = "", queued_by: str = "Steven") -> Path:
    """Queue a job (what Claude does by writing the same file)."""
    now = dt.datetime.now()
    job = {"id": f"{now:%Y%m%d-%H%M%S}-{recipe}", "recipe": recipe, "args": args or {},
           "queued_by": queued_by, "queued_at": now.isoformat(timespec="seconds")}
    if chat_approval:
        job["chat_approval"] = chat_approval
    validate(job, f"{job['id']}.json")
    p = qdir(root, "pending") / f"{job['id']}.json"
    _write(p, job)
    return p
