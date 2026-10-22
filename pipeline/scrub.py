"""Scrubbing shared by the public code export and the public docs: PRIVATE blocks out, owner details replaced
with neutral placeholders, and a scan for terms that must not appear. Generic: the owner's own values come from
owner.yaml; nothing private is named here."""
from __future__ import annotations

import re
from pathlib import Path

B, E = "PRIVATE" + "-BEGIN", "PRIVATE" + "-END"    # spelled apart so this file passes its own scan
BEGIN = re.compile(r"^\s*(?:#|//|<!--|\{#)\s*" + B + r"\b.*$")
END = re.compile(r"^\s*(?:#|//|<!--|\{#)\s*" + E + r"\b.*$")
TEXT = {".py", ".md", ".html", ".yaml", ".yml", ".txt", ".js", ".css", ".gs", ".svg", ".example", ".gitignore", ""}

def strip_private(text: str) -> str:
    """Drop every private ... end-private block (marker lines included). Unbalanced markers raise."""
    out, depth = [], 0
    for ln in text.split("\n"):
        if BEGIN.match(ln):
            depth += 1
            continue
        if END.match(ln):
            if not depth:
                raise ValueError(f"{E} without {B}")
            depth -= 1
            continue
        if not depth:
            out.append(ln)
    if depth:
        raise ValueError(f"{B} without {E}")
    return "\n".join(out)


def substitutions(o: dict) -> list:
    """(pattern, replacement): the owner's addresses -> you@example.com forms, organization -> 'your firm'."""
    subs = []
    for a in sorted({*o.get("addresses", []), *o.get("forwarders", []), *o.get("extra_personal", []),
                     *o.get("share_addresses", []),
                     o.get("account", ""), o.get("briefing_account", "")} - {""}, key=len, reverse=True):
        local, dom = a.lower().split("@", 1)
        base = local.split("+", 1)[0]
        tag = "briefing" if base == (o.get("briefing_account") or "@").split("@")[0].split("+")[0].lower() else "you"
        subs.append((re.compile(re.escape(base) + r"(\+[\w-]+)?@" + re.escape(dom), re.I),
                     lambda m, t=tag: f"{t}{m.group(1) or ''}@example.com"))
    for d in o.get("org_domains") or []:
        subs.append((re.compile(r"(?<![\w-])" + re.escape(d) + r"\b", re.I), "example-firm.com"))
    if o.get("org"):
        subs.append((re.compile(r"\b" + re.escape(o["org"]) + r"(?: Capital)?('s)?\b"), lambda m: "your firm" + (m.group(1) or "")))
    return subs


def scrub(text: str, o: dict) -> str:
    text = strip_private(text)
    for pat, rep in substitutions(o):
        text = pat.sub(rep, text)
    return text


def scan(out: Path, terms: list) -> list:
    pats = [(t, re.compile(r"(?<![\w])" + re.escape(t) + r"(?![\w])", re.I)) for t in terms]
    hits = []
    for p in sorted(out.rglob("*")):
        if ".git" in p.parts or not p.is_file() or (p.suffix not in TEXT and p.name != "np"):
            continue
        t = p.read_text("utf-8", errors="replace")
        for term, pat in pats:
            for m in pat.finditer(t):
                line = t.count("\n", 0, m.start()) + 1
                hits.append(f"{p.relative_to(out)}:{line}: {term}")
    return hits
