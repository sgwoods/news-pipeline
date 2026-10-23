"""Run queue: Claude queues a named recipe, this Mac runs it, Steven decides (docs/plans/run-queue.md).

    data/queue/pending/<id>.json   a job: {"id", "recipe", "args": {...}, "chat_approval": "...", "queued_by"}
    data/queue/waiting/<id>.json   a job waiting for Approve in the dialog on this Mac
    data/queue/done/<id>.json      the job and its result: status, each step's exit code, log file and last lines

A launchd agent (`./np runner install`) ticks every minute and when a job file appears. Jobs are data: the runner
runs only the recipes below, with validated arguments, as argument lists (never a shell). Three tiers:

- auto: tests, staging sync / preview / compare, doctor, the gate's status, verify. Run as soon as queued.
- chat: corrections, publish, restore. Need `chat_approval`: Steven's yes in the Claude chat, quoted.
- mac:  ship, release, rollback, release-check approve, public code push, git hooks. Run only after Steven clicks
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
DIALOG_SECONDS = 600
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
    "restore": {"tier": "chat", "args": {}, "steps": [("prod", ["publish", "restore"]), ("local", ["verify"])]},
    "ship":    {"tier": "mac", "args": {"version": "version", "note": "reviewed"},
                "steps": [("dev", ["staging", "sync"]), ("dev", ["tests"]), APPROVE,
                          ("local", ["release", "{version}", "{note}"]), ("local", ["verify"])]},
    "release": {"tier": "mac", "args": {"version": "version", "note": "reviewed"},
                "steps": [APPROVE, ("local", ["release", "{version}", "{note}"]), ("local", ["verify"])]},
    "rollback": {"tier": "mac", "args": {"note": "reviewed"},
                 "steps": [APPROVE, ("local", ["rollback", "{note}"]), ("local", ["verify"])]},
    "approve": {"tier": "mac", "args": {"note": "reviewed"},
                "steps": [("prod", ["release-check"]), APPROVE, ("local", ["approve", "{note}"])]},
    "install-hooks": {"tier": "mac", "args": {}, "steps": [APPROVE, ("local", ["install-hooks"])]},
}
CHANGES_PRODUCTION = {"correct", "publish", "restore", "ship", "release", "rollback", "approve", "install-hooks",
                      "push-code"}
IN_RELEASE_WINDOW = {"ship", "release"}
NEEDS_APPROVAL = {"release", "rollback", "approve", "install-hooks", "push-code"}   # local steps behind the click


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
            if where not in ("dev", "prod", "local"):
                bad.append(f"{name}: unknown place {where}")
            if where == "local" and argv[0] in NEEDS_APPROVAL and not (r["tier"] == "mac" and seen_approve):
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


def ask_mac(job: dict, summary: str, seconds: int = DIALOG_SECONDS) -> str:
    """The approval dialog on this Mac: 'approve', 'reject' or 'timeout'. The text goes in as an argument."""
    msg = (f"Approve this run-queue job?\n\n{job['recipe']} {' '.join(v for v in job['args'].values() if v)}\n\n"
           f"{summary}\n\nQueued by {job.get('queued_by') or '?'} · {job['id']}")[:1800]
    script = ['on run argv', 'display dialog (item 1 of argv) with title "AI Briefing · approval" '
              'buttons {"Reject", "Approve"} default button "Reject" cancel button "Reject" '
              f'giving up after {int(seconds)} with icon caution', 'end run']
    args = ["osascript"] + sum((["-e", s] for s in script), []) + [msg]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=seconds + 30)
    except (OSError, subprocess.TimeoutExpired):
        return "timeout"
    if r.returncode != 0:
        return "reject" if "-128" in (r.stderr or "") else "timeout"
    if "gave up:true" in r.stdout:
        return "timeout"
    return "approve" if "button returned:Approve" in r.stdout else "reject"


def notify_mac(title: str, text: str):
    script = ['on run argv', 'display notification (item 2 of argv) with title (item 1 of argv)', 'end run']
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(["osascript"] + sum((["-e", s] for s in script), []) + [f"AI Briefing · {title}", text[:200]],
                       capture_output=True, timeout=15)


class Runner:
    """One pass over the queue. `local` maps local step names to functions run.py provides (argv -> exit code)."""

    def __init__(self, root: Path, dev: Path, local: dict, now=None, ask=ask_mac, notify=notify_mac,
                 busy=None, summary=None):
        self.root, self.dev, self.local = root, dev, local
        self.now = now or dt.datetime.now
        self.ask, self.notify = ask, notify
        self.busy = busy or (lambda: False)               # a production run in progress
        self.summary = summary or (lambda job: "")

    def _defer(self, job: dict) -> str:
        t = self.now().time()
        if job["recipe"] in CHANGES_PRODUCTION and (MORNING[0] <= t < MORNING[1] or self.busy()):
            return "the morning run's window or a run in progress"
        if job["recipe"] in IN_RELEASE_WINDOW and not (RELEASE_WINDOW[0] <= t <= RELEASE_WINDOW[1]):
            return "releases go out 08:30-20:00"
        return ""

    def _step(self, job: dict, i: int, step, log: Path) -> int:
        where, argv = step
        argv = argv_for(argv, job["args"])
        if where == "local":
            fn = self.local.get(argv[0])
            if fn is None:
                with log.open("a", encoding="utf-8") as f:
                    f.write(f"no local step {argv[0]}\n")
                return 1
            return run_local(fn, argv[0], argv[1:], log)
        return run_np(self.dev if where == "dev" else self.root, argv, log)

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
        for k in ("steps", "phase", "prompted_at", "started"):
            if k in raw:
                job[k] = raw[k]
        why = self._defer(job)
        if why:
            job["deferred"] = why
            _write(src, {**raw, "deferred": why})
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
            if terminal:
                answer = "approve"
            else:
                last = job.get("prompted_at")
                if last and self.now() - dt.datetime.fromisoformat(last) < REPROMPT:
                    return "waiting"
                job["prompted_at"] = self.now().isoformat(timespec="seconds")
                answer = self.ask(job, self.summary(job))
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
            code = self._run_approved(job, steps, cut + 1, log, "terminal" if terminal else "dialog")
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
