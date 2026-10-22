"""Read-only parser for perspective.md.

perspective.md is hand-edited by Steven. This module only ever reads it.
The full raw text is also exposed so prompts can use the whole lens verbatim;
the structured bits (people table, bullet lists) drive source resolution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Bluesky mention with a handle, e.g. "Bluesky (edzitron.com)"
_BSKY_RE = re.compile(r"bluesky\s*\(([^)]+)\)", re.IGNORECASE)
# Bare domains with optional path, e.g. "garymarcus.substack.com", "example.ai/blog"
_DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})(/[a-z0-9\-_/]*)?", re.IGNORECASE)
# Platforms we know have no free feed (handled in Phase 3)
_NO_FEED_PLATFORMS = ("x", "threads", "linkedin", "podcast", "guest appearances")


@dataclass
class Person:
    name: str
    tier: str                 # e.g. "follow closely", "candidate", "scrutiny"
    flags: list[str]          # e.g. ["PORTFOLIO"], ["Canadian"]
    where: str                # raw "Where" cell
    notes: str
    scrutiny: bool
    sites: list[str] = field(default_factory=list)            # "domain[/path]"
    bluesky: list[str] = field(default_factory=list)          # handles
    other_platforms: list[str] = field(default_factory=list)  # X, podcast, ...


@dataclass
class Perspective:
    raw: str
    sections: dict[str, str]
    people: list[Person]

    def bullets(self, heading_startswith: str) -> list[str]:
        """Bullet lines from the first section whose heading starts with the given text."""
        for title, body in self.sections.items():
            if title.lower().startswith(heading_startswith.lower()):
                return [ln.strip()[2:].strip() for ln in body.splitlines()
                        if ln.strip().startswith(("- ", "* "))]
        return []

    @property
    def topics(self) -> list[str]:
        return self.bullets("Topics")

    @property
    def skepticism(self) -> list[str]:
        return self.bullets("What I'm skeptical")

    @property
    def importance_rules(self) -> list[str]:
        return self.bullets("Importance")


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current, buf = m.group(1).strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _parse_tier(cell: str) -> tuple[str, list[str], bool]:
    flags = [f.strip() for f in re.findall(r"\(([^)]+)\)", cell)]
    tier = re.sub(r"\([^)]*\)", "", cell).strip().lower()
    return tier, flags, "scrutiny" in tier


def _parse_where(cell: str) -> tuple[list[str], list[str], list[str]]:
    bluesky = [h.strip().lstrip("@") for h in _BSKY_RE.findall(cell)]
    rest = _BSKY_RE.sub("Bluesky", cell)
    sites = []
    for dom, path in _DOMAIN_RE.findall(rest):
        site = (dom + (path or "")).lower().rstrip("/")
        if site not in sites:
            sites.append(site)
    # platform words, comma/slash separated, with parenthesised bits removed
    words = re.split(r"[,/+]", re.sub(r"\([^)]*\)", "", cell))
    others = []
    for w in (w.strip().lower() for w in words):
        if w in _NO_FEED_PLATFORMS or w.startswith("podcast"):
            others.append(w)
    if re.search(r"\bbluesky\b", cell, re.IGNORECASE) and not bluesky:
        others.append("bluesky (no handle given)")
    return sites, bluesky, others


def _parse_people(section: str) -> list[Person]:
    rows = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 3:
        return []
    header = [c.strip().lower() for c in rows[0].strip().strip("|").split("|")]
    idx = {k: header.index(k) for k in ("name", "tier", "where", "notes") if k in header}
    people = []
    for row in rows[2:]:  # skip header + separator
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        get = lambda k: cells[idx[k]] if k in idx and idx[k] < len(cells) else ""
        name = get("name")
        if not name:
            continue
        tier, flags, scrutiny = _parse_tier(get("tier"))
        sites, bsky, others = _parse_where(get("where"))
        people.append(Person(name=name, tier=tier, flags=flags, where=get("where"),
                             notes=get("notes"), scrutiny=scrutiny, sites=sites,
                             bluesky=bsky, other_platforms=others))
    return people


def parse(text: str) -> Perspective:
    sections = _split_sections(text)
    people_section = next((b for t, b in sections.items()
                           if t.lower().startswith("tracked people")), "")
    return Perspective(raw=text, sections=sections, people=_parse_people(people_section))


def load(path: str | Path = "perspective.md") -> Perspective:
    return parse(Path(path).read_text(encoding="utf-8"))
