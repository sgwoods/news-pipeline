"""Fact checks inside the takes email (Steven, 2026-11-04): everything the checks found goes to Steven BEFORE the
edition is sent, at the bottom of the takes email, as numbered items F1, F2, ... each with options and a
recommendation. He answers in the same reply as his takes ("F1: B"); an item he doesn't answer gets the
recommendation. The choices are applied to the written edition (and the deep dive) before it is published, and the
podcast is re-recorded if anything it says changed.

Options, the same letters everywhere:
    rewritten by the check (already in the edition):  A keep the rewrite  · B go back to the original wording
    a line or sentence to look at:                     A keep as written   · B use the proposed rewrite (when there is
                                                       one, re-checked)    · C cut it

Sources: the pre-send check (data/audit/DAY-presend.json), the deep-dive check (DAY-deepdive.json) and the accuracy
audit (DAY.json), which now runs before the takes email instead of after sending.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DECISIONS = "data/audit/{day}-decisions.json"
_CHOICE = re.compile(r"^\s*F\s*(\d{1,2})\s*[:.)\-–=]?\s*([A-Da-d])\b")


def _plain(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s or "")
    return " ".join(s.replace("**", "").replace("*", "").split()).strip(" -")


def items(root: Path, day: str) -> list:
    """[{id, src, kind, text, why, options: [(letter, label)], rec, ...}] in a stable order."""
    from .audit import DIR, load_deepdive_check, load_presend
    out = []
    pc, dd = load_presend(root, day), load_deepdive_check(root, day)
    try:
        acc = json.loads((Path(root) / DIR / f"{day}.json").read_text("utf-8"))
    except (OSError, ValueError):
        acc = {}

    def add(**k):
        out.append({"id": f"F{len(out) + 1}", **k})

    for f in pc.get("fixes") or []:
        add(src="edition", kind="fixed", text=_plain(f["after"]), was=_plain(f["before"]), why=f.get("why", ""),
            before_md=f["before"], after_md=f["after"],
            options=[("A", "keep the rewrite"), ("B", "go back to the original wording")], rec="A")
    for h in pc.get("held") or []:
        prop = h.get("proposed_md")
        rech = h.get("recheck") or []
        rec = ("B" if prop and rech.count("supported") * 2 >= len(rech) else
               "C" if h.get("verdict") in ("contradicted", "unsupported") or (prop and "contradicted" in rech) else "A")
        opts = [("A", "keep as written")] + ([("B", "use the proposed rewrite")] if prop else []) + [("C", "cut it")]
        add(src="edition", kind="check", text=_plain(h.get("before_md") or h["claim"]), why=h.get("why", ""),
            before_md=h.get("before_md") or "", claim=h["claim"], proposed_md=prop or "",
            proposed=_plain(prop) if prop else "", options=opts, rec=rec)
    for h in dd.get("held") or []:
        prop = h.get("proposed") or ""
        opts = [("A", "keep as written")] + ([("B", "use the proposed rewrite")] if prop else []) + [("C", "cut it")]
        add(src="deepdive", kind="check", text=h["claim"], why=h.get("why", ""), claim=h["claim"], section=h.get("section", ""),
            proposed=prop, options=opts, rec=("B" if prop else "C") if h.get("verdict") != "not found" else "A")
    for c in acc.get("issues") or []:
        if any(c["claim"] in (i.get("text") or "") for i in out):
            continue
        add(src="edition", kind="check", text=c["claim"], why=f"{c.get('verdict')}: {c.get('why', '')}".strip(": "),
            claim=c["claim"], options=[("A", "keep as written"), ("C", "cut it")],
            rec="C" if c.get("verdict") == "contradicted" else "A")
    return out


def section(its: list) -> tuple:
    """(text lines, html) for the bottom of the takes email."""
    import html as h
    if not its:
        return [], ""
    head = (f"Fact checks ({len(its)}): reply with your choice on its own line, e.g. \"{its[0]['id']}: "
            f"{its[0]['options'][-1][0]}\", in the same reply as your takes. No answer = my recommendation.")
    L, H = ["", "FACT CHECKS", head], [
        '<div style="margin:22px 0 0;padding:14px 16px;border:1px solid #fcd34d;border-radius:10px;background:#fffbeb">'
        f'<div style="font-weight:700;font-size:15px;margin:0 0 6px">Fact checks</div>'
        f'<p style="margin:0 0 10px;font-size:13px;color:#374151">{h.escape(head)}</p>']
    for it in its:
        where = "Deep dive" if it["src"] == "deepdive" else "Edition"
        lines = [f"{it['id']} · {where}: {it['text'][:280]}"]
        if it["kind"] == "fixed":
            lines.append(f"   was: {it['was'][:240]}")
        if it.get("why"):
            lines.append(f"   why: {it['why'][:220]}")
        if it.get("proposed"):
            lines.append(f"   proposed: {it['proposed'][:240]}")
        opts = "   " + "  ·  ".join(f"{k}) {lab}" for k, lab in it["options"]) + f"   → I recommend {it['rec']}"
        lines.append(opts)
        L += lines + [""]
        H.append('<div style="margin:0 0 10px;font-size:13px;line-height:1.5;color:#111827">'
                 + "<br>".join(h.escape(x.strip()) if i else f"<b>{h.escape(x)}</b>" for i, x in enumerate(lines))
                 + "</div>")
    H.append("</div>")
    return L, "".join(H)


def parse(text: str) -> dict:
    """'F1: B' lines in a reply -> {"F1": "B"}."""
    out = {}
    for ln in (text or "").replace("\r\n", "\n").split("\n"):
        m = _CHOICE.match(ln)
        if m:
            out[f"F{int(m.group(1))}"] = m.group(2).upper()
    return out


def _replace_in_md(md: str, old_md: str, old_plain: str, new: str | None) -> tuple:
    """Replace (or with new=None, cut) a line or sentence. -> (md, applied)."""
    if old_md and old_md in md:
        return (md.replace(old_md, new, 1) if new is not None else
                "\n".join(ln for ln in md.split("\n") if ln != old_md) if old_md in md.split("\n") else md.replace(old_md, "", 1)), True
    if old_plain and old_plain in md:                    # a sentence written without markup
        if new is None:
            return re.sub(r"\s*" + re.escape(old_plain), "", md, count=1), True
        return md.replace(old_plain, new, 1), True
    return md, False


def apply(root: Path, cfg: dict, day: str, choices: dict, log=print) -> dict:
    """Apply each item's choice (Steven's, else the recommendation). -> {edition_changed, deepdive_changed, results}."""
    its = items(root, day)
    b = Path(root) / (cfg.get("paths") or {}).get("briefings", "briefings")
    mdp = b / f"{day}.md"
    md = mdp.read_text("utf-8") if mdp.exists() else ""
    md0 = md
    from .deepdive import DIR as DDDIR
    pp = Path(root) / DDDIR / f"{day}.parts.json"
    parts = json.loads(pp.read_text("utf-8")) if pp.exists() else None
    parts0 = json.dumps(parts)
    results = []
    for it in its:
        pick = choices.get(it["id"]) or it["rec"]
        if pick not in [k for k, _ in it["options"]]:
            pick = it["rec"]
        done, note = True, ""
        if it["src"] == "edition":
            if it["kind"] == "fixed" and pick == "B":
                md, done = _replace_in_md(md, it["after_md"], "", it["before_md"])
            elif it["kind"] == "check" and pick == "B":
                md, done = _replace_in_md(md, it.get("before_md", ""), "", it["proposed_md"])
            elif it["kind"] == "check" and pick == "C":
                md, done = _replace_in_md(md, it.get("before_md", ""), it.get("claim", ""), None)
        elif parts is not None and pick in ("B", "C"):
            done = False
            for p in parts["parts"]:
                if it["claim"] in p[1]:
                    p[1] = p[1].replace(it["claim"], it["proposed"] if pick == "B" else "", 1).replace("  ", " ")
                    done = True
                    break
        if not done:
            note = "not applied: the text was not found (already changed?)"
        results.append({"id": it["id"], "pick": pick, "by": "Steven" if it["id"] in choices else "recommendation",
                        "text": it["text"][:200], **({"note": note} if note else {})})
    if md != md0:
        mdp.write_text(md, "utf-8")
    dd_changed = parts is not None and json.dumps(parts) != parts0
    if dd_changed:
        pp.write_text(json.dumps(parts, ensure_ascii=False), "utf-8")
    out = {"edition_changed": md != md0, "deepdive_changed": dd_changed, "results": results}
    p = Path(root) / DECISIONS.format(day=day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", "utf-8")
    for r in results:
        if r["pick"] != "A" or r["by"] == "Steven":
            log(f"fact check {r['id']}: {r['pick']} ({r['by']}){' ' + r['note'] if r.get('note') else ''}")
    return out
