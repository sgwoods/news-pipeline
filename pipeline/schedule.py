"""When the scheduled jobs actually run: decided here, by this machine's local wall clock, not by launchd.

launchd fires the daily and preflight agents every half hour (StartCalendarInterval with Minute only), and
`./np scheduled daily|preflight` asks due() whether a configured time (schedule.times, schedule.preflight) has
just passed. Why: on 2026-10-17..22 every job fired exactly one hour early (05:00 -> 04:00, 20:30 -> 19:30)
because launchd's idea of local time disagreed with the system clock's. Minutes are the same in every whole-hour
time zone, so the half-hour tick is reliable whatever launchd believes, and the hour is checked here.
"""
from __future__ import annotations

import datetime as dt

TICK_MINUTES = (0, 30)       # launchd fires at these minutes of every hour
WINDOW = dt.timedelta(minutes=30)


def times(cfg: dict, kind: str) -> list:
    s = cfg.get("schedule") or {}
    if kind == "daily":
        base = [str(t) for t in s.get("times", ["06:30", "07:30"])]
        if (cfg.get("takes") or {}).get("enabled"):      # the edition waits for takes: retry after the cutoff too
            base += [str(t) for t in s.get("after_takes", ["09:30", "10:30", "12:00"]) if str(t) not in base]
        return base
    if kind == "preflight":
        return [str(s.get("preflight", "20:30"))]
    return []


def due(cfg: dict, kind: str, now: dt.datetime | None = None) -> str:
    """The configured time that falls in the last half hour ('' if none): exactly one tick matches each time."""
    now = now or dt.datetime.now()
    for t in times(cfg, kind):
        h, m = (int(x) for x in t.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if dt.timedelta(0) <= now - at < WINDOW:
            return t
    return ""


def check(cfg: dict) -> list:
    """Configured times the half-hour tick can't hit (must be on :00 or :30)."""
    return [t for k in ("daily", "preflight") for t in times(cfg, k) if int(t.split(":")[1]) not in TICK_MINUTES]
