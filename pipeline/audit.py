"""The daily accuracy audit (critic 2026-10-24, #10D; Steven 2026-10-27).

After the edition ships, about five of its factual claims (sentences with a figure or a named fact, from Must read
"What happened" lines first) are checked against the story's own source texts by a model, claim by claim:
supported, partly, not found, or contradicted. The consistency checks' flags for the day (claims the edition's own
body or the last two weeks contradict) are counted as contradictions. The result is saved in data/audit/DAY.json;
a claim that is contradicted or only partly right sends Steven one alert, so he can decide on a correction. The
public accuracy page shows the daily counts and every correction (pipeline/shipped.py), never the model's notes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import factcheck
from .stages import _ask, _one_line, prompt

DIR = "data/audit"
N_CLAIMS = 5
_FIG = re.compile(r"[$€£]\s?\d|\d[\d,.]*\s?(?:%|percent|[BMK]\b|bn\b|billion|million|trillion)|\b(?:19|20)\d\d\b|\b\d{2,}\b")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
VERDICTS = ("supported", "partly", "not found", "contradicted")


def _plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\s*\((?:[A-Z][^()]{1,40}(?:,\s*)?)+\)", "", s)          # "(Crunchbase News, Latent Space)"
    return s.replace("**", "").replace("*", "").strip()


def claims(md: str, stories: list, n: int = N_CLAIMS) -> list:
    """[{n, text, story, ids}]: sentences with a figure from Must read What happened lines, then Worth knowing."""
    by_head = {s.get("headline", ""): s for s in stories}
    out, seen = [], set()
    must = md.split("## Must read", 1)[1].split("\n## ", 1)[0] if "## Must read" in md else ""
    blocks = re.split(r"(?m)^### \d+\. ", must)[1:]
    pool = []
    for b in blocks:
        head = b.splitlines()[0].strip()
        s = by_head.get(head) or next((x for k, x in by_head.items() if k[:40] == head[:40]), {})
        m = re.search(r"- \*\*What happened:\*\* (.+)", b)
        if m:
            for sent in _SENT.split(_plain(m.group(1))):
                pool.append((0 if _FIG.search(sent) else 1, head, s, sent))
    worth = md.split("## Worth knowing", 1)[1].split("\n## ", 1)[0] if "## Worth knowing" in md else ""
    for ln in worth.splitlines():
        m = re.match(r"- \*\*\d+\. (.+?)\*\* (.+)", ln)
        if m:
            head = m.group(1).rstrip(".")
            s = by_head.get(head) or next((x for k, x in by_head.items() if k[:40] == head[:40]), {})
            for sent in _SENT.split(_plain(m.group(2)))[:1]:
                pool.append((2 if _FIG.search(sent) else 3, head, s, sent))
    used_story = {}
    for pri, head, s, sent in sorted(pool, key=lambda x: x[0]):
        sent = sent.strip()
        if len(sent.split()) < 6 or sent in seen or not s.get("ids") or used_story.get(head, 0) >= 2:
            continue
        seen.add(sent)
        used_story[head] = used_story.get(head, 0) + 1
        out.append({"n": len(out) + 1, "text": sent, "story": head, "ids": s["ids"]})
        if len(out) >= n:
            break
    return out


def _excerpt(texts: list, claim: str, limit: int = 2400) -> str:
    """The parts of the source texts that share the claim's figures and names."""
    keys = {w.lower() for w in re.findall(r"[A-Z][\w.-]+|\d[\d,.]*", claim) if len(w) > 1}
    parts = []
    for t in texts:
        for para in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", t)):
            low = para.lower()
            hits = sum(1 for k in keys if k in low)
            if hits >= 2 or (hits == 1 and len(keys) <= 2):
                parts.append(para[:400])
    txt = " … ".join(dict.fromkeys(parts))
    return txt[:limit] if txt else " ".join(texts)[:limit]


def _stories(root: Path, day: str) -> list:
    try:
        rows = [json.loads(x) for x in (root / "data" / "stories" / f"{day}.jsonl").read_text("utf-8").splitlines() if x.strip()]
        return rows[-1]["stories"] if rows else []
    except (OSError, ValueError, KeyError):
        return []


def contradictions(root: Path, day: str) -> list:
    from . import consistency
    try:
        rep = consistency.audit(root, [day], log=lambda *a: None)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for d in rep.get("days", []):
        out += [f"against the last two weeks: {x}" for x in d.get("cross_day", [])]
        out += [f"against its own body: {x}" for x in d.get("header", [])]
    return [str(x)[:200] for x in out]


def run(root: Path, day: str, llm, system: str, log=print) -> dict:
    root = Path(root)
    md = (root / "briefings" / f"{day}.md").read_text("utf-8")
    cl = claims(md, _stories(root, day))
    tmpl, version = prompt("audit")
    blocks = []
    for c in cl:
        texts = factcheck.corpus(root, c["ids"])
        c["sources"] = len(texts)
        blocks.append(f"CLAIM {c['n']} (story: {c['story']}): {c['text']}\nSOURCE EXCERPTS: {_excerpt(texts, c['text'])}")
    checks = {}
    if cl:
        try:
            out = _ask(llm, system, tmpl.replace("{{claims}}", "\n\n".join(blocks)), 300 + 120 * len(cl))
            for x in out.get("checks") or []:
                v = str(x.get("verdict", "")).lower().strip()
                if v in VERDICTS and str(x.get("n", "")).isdigit():
                    checks[int(x["n"])] = {"verdict": v, "why": _one_line(str(x.get("why") or ""))[:240],
                                           "source": _one_line(str(x.get("source") or ""))[:80]}
        except Exception as e:  # noqa: BLE001
            log(f"audit: model check failed: {type(e).__name__}: {e}"[:200])
    rows = []
    for c in cl:
        r = {"n": c["n"], "claim": c["text"], "story": c["story"], "sources": c.get("sources", 0),
             **checks.get(c["n"], {"verdict": "unchecked", "why": "", "source": ""})}
        rows.append(r)
    con = contradictions(root, day)
    res = {"day": day, "prompt": version, "model": getattr(llm, "label", ""), "claims": rows,
           "checked": sum(1 for r in rows if r["verdict"] != "unchecked"),
           "supported": sum(1 for r in rows if r["verdict"] == "supported"),
           "issues": [r for r in rows if r["verdict"] in ("partly", "contradicted")],
           "contradictions": con}
    p = root / DIR / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    return res


def load_all(root: Path) -> list:
    out = []
    for p in sorted((Path(root) / DIR).glob("????-??-??.json")):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except (OSError, ValueError):
            pass
    return out


def summary(res: dict) -> str:
    return (f"{res['checked']} claims checked, {res['supported']} supported, {len(res['issues'])} to look at, "
            f"{len(res['contradictions'])} contradiction flag(s)")
