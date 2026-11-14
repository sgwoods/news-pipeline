"""The pipeline's clock: the edition keeps Eastern time wherever the Mac is (Steven, travelling, 2026-11-11).

`schedule.timezone` (config.yaml; empty = the Mac's own zone, as before) names the zone the schedule, the takes
cutoff and the morning check are read in. launchd still fires the agents every half hour by the Mac's clock; the
hour is checked here, in the configured zone, so a Mac set to Costa Rica time still runs the 05:00 Toronto edition
at 05:00 Toronto (04:00 on its own clock). Minutes are the same in every whole-hour zone (pipeline/schedule.py).
Everything written to files (timestamps) stays in the Mac's local time, as before.
"""
from __future__ import annotations

import datetime as dt


def zone(cfg: dict):
    name = str(((cfg or {}).get("schedule") or {}).get("timezone") or "").strip()
    if not name:
        return None
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - a typo in config.yaml must not stop the schedule
        return None


def now(cfg: dict) -> dt.datetime:
    """Wall-clock time in the configured zone, naive (what the schedule and cutoffs compare against)."""
    z = zone(cfg)
    if z is None:
        return dt.datetime.now()
    return dt.datetime.now(dt.timezone.utc).astimezone(z).replace(tzinfo=None)


def today(cfg: dict) -> str:
    return now(cfg).date().isoformat()


def mismatch(cfg: dict) -> str:
    """'' when the Mac's zone is the configured one (or none is configured); else a one-line note for the dashboard."""
    z = zone(cfg)
    if z is None:
        return ""
    here = dt.datetime.now().astimezone()
    there = dt.datetime.now(dt.timezone.utc).astimezone(z)
    if here.utcoffset() == there.utcoffset():
        return ""
    diff = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600
    return (f"This Mac's clock is {abs(diff):g} h {'behind' if diff > 0 else 'ahead of'} {z.key}; the schedule, "
            f"the takes cutoff and the morning check follow {z.key} ({there:%H:%M} there, {here:%H:%M} here).")
