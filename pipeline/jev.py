"""Jev (TypeSafe's System One model) as a shadow filter (Steven, 2026-10-29/30).

Jev answers typed questions about a piece of text with calibrated probabilities, in well under a second, for about
$0.04 per million input tokens. The pipeline's filter stage asks a local model keep/drop for 150-200 items a morning
and takes 2-12 minutes. Before trusting Jev with that, it runs in the SHADOW: after the local filter, every item
the model saw is also asked of Jev, the two answers are logged side by side (data/state/jev-shadow.jsonl), and the
morning report prints the agreement. Nothing Jev says changes the edition until the week's numbers say it should.

Rules: public fetched items only (the prefilter has already removed private hosts); confidential content never
reaches it; the key (TYPESAFE_API_KEY) lives in the Keychain; a daily token budget stops it; off in staging.
Design follows TypeSafe's own skill: one atomic question per judgment, a companion "nothing fits" question, and
thresholds of 0.7/0.3 read as keep/drop with the middle as "not settled".
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
LOG = "data/state/jev-shadow.jsonl"
BUDGET = "data/state/jev-budget.json"
KEEP = "Should this item be analysed for a daily AI briefing written for early-stage (seed to Series A) AI investors? " \
       "Keep anything that plausibly touches: AI research and model quality, real-world AI use and business value, AI " \
       "economics, financing and capex, agent security, sovereign, multilingual or Canadian AI, the compute supply chain, " \
       "China and global models, policy affecting AI companies, or a tracked person's substantive argument. Drop personal " \
       "chatter, jokes with no claim, pure self-promotion with no content, job posts, event logistics and near-empty items."
NOTHING = "Is this item empty, broken, or about nothing at all (no claim, no news, no argument)?"


def jcfg(cfg: dict) -> dict:
    return {"enabled": False, "shadow": True, "model": "jev-latest", "max_items": 250, "state_chars": 1400,
            "daily_tokens": 400_000, **(cfg.get("jev") or {})}


def key() -> str:
    from .vault import get
    return get("TYPESAFE_API_KEY")


def state_of(it: dict, chars: int) -> str:
    """The item as a person would read it: who, where from, when, then the text. Nothing private is in `it`."""
    from .stages import _clean, content_text
    who = it.get("source_label") or it.get("person") or ""
    head = f"{who} · {it.get('source_kind', '')} · {str(it.get('published') or '')[:10]}".strip(" ·")
    title = str(it.get("title") or "").strip()
    return "\n".join(x for x in (head, title, _clean(content_text(it))[:chars]) if x)


def ask(state: str, questions: dict, model: str, client=None, timeout: int = 20) -> dict:
    import httpx
    tok = key()
    if not tok:
        raise RuntimeError("TYPESAFE_API_KEY is not set (queue the jev-setup job)")
    r = (client or httpx).post(API, json={"model": model, "state": state, "questions": questions},
                               headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}, timeout=timeout)
    if r.status_code >= 300:
        raise RuntimeError(f"jev HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _budget(root: Path, day: str) -> dict:
    try:
        b = json.loads((root / BUDGET).read_text("utf-8"))
        if b.get("day") == day:
            return b
    except (OSError, ValueError):
        pass
    return {"day": day, "tokens": 0, "calls": 0}


def _save_budget(root: Path, b: dict) -> None:
    p = root / BUDGET
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(b), "utf-8")


def shadow(root: Path, cfg: dict, day: str, items: list, decisions: dict, log=print, client=None) -> dict:
    """Ask Jev about every item the local filter judged; log both. -> summary for the run record."""
    c = jcfg(cfg)
    from .env import staging
    if not c["enabled"] or staging(root) or not key():
        return {}
    b = _budget(root, day)
    rows, agree, unsettled, errors = [], 0, 0, 0
    judged = [it for it in items if it["id"] in decisions and not decisions[it["id"]].get("rule")][: int(c["max_items"])]
    for it in judged:
        if b["tokens"] >= int(c["daily_tokens"]):
            log(f"jev shadow: daily token budget reached ({b['tokens']}); stopping")
            break
        try:
            out = ask(state_of(it, int(c["state_chars"])), {"keep": {"type": "noul", "instructions": KEEP},
                                                            "nothing": {"type": "noul", "instructions": NOTHING}},
                      c["model"], client)
        except Exception as e:  # noqa: BLE001
            errors += 1
            if errors <= 2:
                log(f"jev shadow: {e}"[:200])
            if errors >= 5:
                break
            continue
        u = out.get("usage") or {}
        b["tokens"] += int(u.get("input_tokens") or 0)
        b["calls"] += 1
        p = float(((out.get("answers") or {}).get("keep") or {}).get("noul") or 0)
        nothing = float(((out.get("answers") or {}).get("nothing") or {}).get("noul") or 0)
        local = bool(decisions[it["id"]]["keep"])
        jev = "keep" if p >= 0.7 else "drop" if p <= 0.3 else "unsettled"
        if jev == "unsettled":
            unsettled += 1
        elif (jev == "keep") == local:
            agree += 1
        rows.append({"day": day, "id": it["id"], "local": local, "p_keep": round(p, 3), "p_nothing": round(nothing, 3),
                     "jev": jev, "title": str(it.get("title") or "")[:120]})
    _save_budget(root, b)
    if rows:
        p = root / LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    settled = len(rows) - unsettled
    summ = {"asked": len(rows), "agree": agree, "settled": settled, "unsettled": unsettled, "errors": errors,
            "agreement": round(agree / settled, 3) if settled else None, "tokens_today": b["tokens"],
            "would_drop_kept": sum(1 for r in rows if r["local"] and r["jev"] == "drop"),
            "would_keep_dropped": sum(1 for r in rows if not r["local"] and r["jev"] == "keep")}
    log(f"jev shadow: {summ['asked']} asked, agreement {summ['agreement']} on {settled} settled, "
        f"{unsettled} unsettled, would drop {summ['would_drop_kept']} kept / keep {summ['would_keep_dropped']} dropped, "
        f"{b['tokens']} tokens today")
    return summ


def report(root: Path, days: int = 7) -> dict:
    """The shadow's record over the last DAYS days: agreement, and the disagreements to look at."""
    p = root / LOG
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = []
    if p.exists():
        for ln in p.read_text("utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("day", "") >= since:
                rows.append(r)
    settled = [r for r in rows if r["jev"] != "unsettled"]
    agree = sum(1 for r in settled if (r["jev"] == "keep") == r["local"])
    return {"days": days, "asked": len(rows), "settled": len(settled), "agreement": round(agree / len(settled), 3) if settled else None,
            "would_drop_kept": [r for r in rows if r["local"] and r["jev"] == "drop"][:20],
            "would_keep_dropped": [r for r in rows if not r["local"] and r["jev"] == "keep"][:20]}


def set_key(ask_hidden=None) -> str:
    """The jev-setup job: a Mac dialog stores the API key in the Keychain, then one tiny live call checks it."""
    import subprocess
    from .vault import set_keychain

    def dialog(prompt: str) -> str:
        script = ['on run argv', 'set r to display dialog (item 1 of argv) default answer "" with hidden answer '
                  'with title "AI Briefing · Jev" buttons {"Cancel", "Save"} default button "Save" cancel button "Cancel"',
                  'return text returned of r', 'end run']
        r = subprocess.run(["osascript"] + sum((["-e", s] for s in script), []) + [prompt], capture_output=True, text=True, timeout=600)
        return r.stdout.strip() if r.returncode == 0 else ""
    tok = (ask_hidden or dialog)("Paste the TypeSafe API key from console.typesafe.ai. It stays in this Mac's Keychain.")
    if len(tok) < 16:
        return "not saved: that doesn't look like a key"
    if not set_keychain("TYPESAFE_API_KEY", tok):
        return "not saved: the Keychain refused it"
    try:
        out = ask("OpenAI cut API prices by 80% this quarter.", {"keep": {"type": "noul", "instructions": KEEP}}, "jev-latest")
        p = ((out.get("answers") or {}).get("keep") or {}).get("noul")
        return f"saved: test call ok (p_keep={p}, {int((out.get('usage') or {}).get('input_tokens') or 0)} tokens)"
    except Exception as e:  # noqa: BLE001
        return f"saved, but the test call failed: {e}"[:200]
