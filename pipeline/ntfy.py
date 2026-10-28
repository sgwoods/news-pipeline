"""Notifications on Steven's phone through ntfy (Steven, 2026-10-28: "more control from my iPhone").

ntfy is a free, open-source push service with an iOS app. The Mac publishes to a private topic (a random name
kept only in this Mac's Keychain; the phone subscribes to it once). Two uses:

- Approvals. A mac-tier job's Approve step posts a notification with Approve and Reject buttons. A tap posts
  "approve|<job id>|<nonce>" to a second private topic, which the runner polls. The nonce is an HMAC of the job
  and the day under the early-approval key (pipeline/runner.py), so a tap is good for that job, that day; nobody
  who can't read the private topic (Claude, the VM) can produce it. ntfy.sh carries the messages, so each is
  single-use and names nothing private.
- Nudges. The takes page is ready, the evening note is out, a run needs attention: one notification, one tap to
  the existing owner page. Owner links are minted here the way the mail script mints them (HMAC over
  email|scope|day with the script secret), so nothing new is trusted.

Setup: the ntfy-setup job (Mac Approve) makes the topics, keeps them in the Keychain and copies the subscribe
topic to the clipboard for the phone. Never log or email a topic name: whoever knows it can read the notifications.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import subprocess
from pathlib import Path

SERVER = "https://ntfy.sh"
TOPIC, REPLY = "NP_NTFY_TOPIC", "NP_NTFY_REPLY"
_ANSWER = re.compile(r"^(approve|reject)\|([A-Za-z0-9_.-]{6,80})\|([0-9a-f]{20,64})$")


def topics() -> tuple:
    from .vault import _keychain
    return _keychain(TOPIC), _keychain(REPLY)


def enabled() -> bool:
    return bool(topics()[0])


def _post(url: str, payload: dict, timeout: int = 20) -> bool:
    import httpx
    r = httpx.post(url, json=payload, timeout=timeout)
    return r.status_code < 300


def publish(topic: str, title: str, message: str, click: str = "", actions: list | None = None, priority: int = 3,
            tags: tuple = (), post=None) -> bool:
    payload = {"topic": topic, "title": title[:120], "message": message[:1500], "priority": int(priority)}
    if click:
        payload["click"] = click
    if actions:
        payload["actions"] = actions
    if tags:
        payload["tags"] = list(tags)
    return bool((post or _post)(SERVER, payload))


def notify(cfg: dict, title: str, message: str, click: str = "", priority: int = 3, tags: tuple = (), post=None,
           root: Path | None = None) -> bool:
    """One notification to the phone; a no-op without a topic, in staging, or when ntfy is unreachable."""
    from .env import staging
    if staging(root):
        return False
    topic, _ = topics()
    if not topic or not (cfg.get("approvals") or {}).get("ntfy", True):
        return False
    try:
        return publish(topic, title, message, click, priority=priority, tags=tags, post=post)
    except Exception:  # noqa: BLE001 - never breaks the caller
        return False


# ---- approvals ----

def approval_actions(reply_topic: str, job_id: str, nonce: str) -> list:
    url = f"{SERVER}/{reply_topic}"
    return [{"action": "http", "label": "Approve", "url": url, "method": "POST", "body": f"approve|{job_id}|{nonce}",
             "clear": True},
            {"action": "http", "label": "Reject", "url": url, "method": "POST", "body": f"reject|{job_id}|{nonce}",
             "clear": True}]


def send_approval(job_id: str, nonce: str, title: str, summary: str, post=None) -> bool:
    topic, reply = topics()
    if not topic or not reply:
        return False
    return publish(topic, f"Approve? {title}", summary or job_id, actions=approval_actions(reply, job_id, nonce),
                   priority=4, tags=("white_check_mark",), post=post)


def parse_answers(lines: list) -> dict:
    """ntfy's JSON lines -> {job id: {"answer", "proof", "at"}}, the latest per job."""
    out = {}
    for ln in lines:
        try:
            m = json.loads(ln) if isinstance(ln, str) else ln
        except ValueError:
            continue
        if m.get("event", "message") != "message":
            continue
        hit = _ANSWER.match(str(m.get("message", "")).strip())
        if not hit:
            continue
        at = int(m.get("time") or 0)
        cur = out.get(hit.group(2))
        if not cur or at >= cur["_t"]:
            out[hit.group(2)] = {"answer": hit.group(1), "proof": hit.group(3), "at": str(at), "_t": at}
    return {k: {kk: v for kk, v in d.items() if kk != "_t"} for k, d in out.items()}


def poll(ids: list, get=None, since: str = "12h") -> dict:
    """Answers tapped on the phone for these jobs (the reply topic's recent messages)."""
    _, reply = topics()
    if not reply:
        return {}
    if get is None:
        import httpx
        def get(url):
            r = httpx.get(url, timeout=20)
            return r.text if r.status_code < 300 else ""
    text = get(f"{SERVER}/{reply}/json?poll=1&since={since}")
    got = parse_answers([x for x in text.splitlines() if x.strip()])
    return {i: got[i] for i in ids if i in got}


# ---- owner links (as the mail script mints them: Code.gs ownerToken_) ----

def owner_token(email: str, scope: str, secret: str, day: str) -> str:
    sig = hmac.new(secret.encode(), f"{email.lower()}|{scope}|{day}".encode(), hashlib.sha256).digest()
    return "o" + scope + day + base64.urlsafe_b64encode(sig).decode().rstrip("=")[:32]


def owner_link(cfg: dict, scope: str, day: str = "") -> str:
    """'t': the takes review page for DAY; 'q': the deep-dive queue page. '' when email isn't set up."""
    import datetime as dt
    from .mailer import ecfg, key
    e = ecfg(cfg)
    email, secret, script = (e.get("test_to") or "").strip(), key(), e.get("script_url") or ""
    if not (email and secret and script.startswith("https://script.google.com/")):
        return ""
    today = dt.datetime.utcnow().strftime("%Y%m%d")
    t = owner_token(email, scope, secret, today)
    if scope == "t":
        return f"{script}?action=review&t={t}&d={day}"
    return f"{script}?action=queue&t={t}"


# ---- setup ----

def setup(show=None, copy=None) -> str:
    """The ntfy-setup job: new private topics in the Keychain; the subscribe topic on the clipboard and in a dialog."""
    import secrets
    from .vault import set_keychain
    topic, reply = f"aib-{secrets.token_urlsafe(18)}", f"aib-r-{secrets.token_urlsafe(18)}"
    topic, reply = topic.replace("-_", "-a").replace("_", "x"), reply.replace("_", "x")
    if not (set_keychain(TOPIC, topic) and set_keychain(REPLY, reply)):
        return "not saved: the Keychain refused it"
    (copy or _pbcopy)(topic)
    (show or _dialog)("Phone notifications are on.\n\nThe topic name is on the clipboard (Universal Clipboard pastes it "
                      "on your iPhone). In the ntfy app: + (Subscribe to topic), paste it, Subscribe. Then tell "
                      "Claude \"ntfy test\".\n\nTopic: " + topic)
    return "saved"


def _pbcopy(text: str) -> None:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _dialog(text: str) -> None:
    script = ['on run argv', 'display dialog (item 1 of argv) with title "AI Briefing · phone notifications" '
              'buttons {"OK"} default button "OK"', 'end run']
    try:
        subprocess.run(["osascript"] + sum((["-e", s] for s in script), []) + [text], capture_output=True, timeout=600)
    except Exception:  # noqa: BLE001
        pass
