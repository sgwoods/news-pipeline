"""Who runs this instance: names, addresses, organization, public bio.

The values live in owner.yaml at the project root. That file is private (kept out of the public code repo);
the defaults below are neutral, so a fresh clone runs without it. See owner.example.yaml.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT = {
    "name": "the editor",            # first name used in private notes and prompts
    "full_name": "",
    "account": "",                   # Gmail account the newsletter / feedback labels live in
    "briefing_account": "",          # the account the edition is sent from (Apps Script)
    "addresses": [],                 # the owner's own addresses: editor replies, forwards, privacy scrub
    "forwarders": [],                # addresses whose forwards count as the owner's
    "share_addresses": [],           # routes where the owner's mail is cleared for public use (internal included)
    "extra_personal": [],            # routing addresses to scrub from public text (plus-addresses etc.)
    "org": "",                       # employer, for the "opinions are personal" line and internal-mail rules
    "org_domains": [],               # mail and links from these domains are internal, never public
    "not_names": [],                 # Two Capitalised Words that are not people (private-name check)
    "bluesky_list": "",
    "record_who": "",                # how to tell the owner apart from namesakes (public-record search)
    "site": {},                      # public bio for the site (see site.site_cfg)
}


@lru_cache(maxsize=8)
def _parse(path: str, mtime: float) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text("utf-8")) or {}


def _load(path: str) -> dict:
    p = Path(path)
    return _parse(path, p.stat().st_mtime) if p.is_file() else {}


def get(root: Path | None = None) -> dict:
    """DEFAULT merged with owner.yaml, or with owner.example.yaml (placeholder values) when there is none."""
    r = root or ROOT
    mine = r / "owner.yaml"
    return {**DEFAULT, **_load(str(mine if mine.is_file() else r / "owner.example.yaml"))}


def addresses(root: Path | None = None) -> list:
    o = get(root)
    return [a.lower() for a in o["addresses"]]
