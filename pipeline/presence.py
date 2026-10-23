"""Is a person here to approve? A terminal, or the run queue's approval dialog clicked on this Mac.

Approvals (release-check approve, releases, rollbacks, the public code push) need Steven, not a script, an agent
or the dashboard. Until v0.1.12 that meant a terminal (sys.stdin.isatty). The run queue (pipeline/runner.py) adds
one more way: Steven clicks Approve in a dialog on this Mac, and the runner grants presence for that one job, in
memory, for as long as the job's approval step runs. Nothing on disk or in the environment can grant it, so a
file Claude (or anything else) writes can't stand in for the click.
"""
from __future__ import annotations

import contextlib
import sys

_granted: list = []                                       # job ids, in memory only


def confirmed() -> bool:
    """True when a person is here: a terminal, or an approval dialog clicked for the job now running."""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return True
    except (AttributeError, ValueError):
        pass
    return bool(_granted)


@contextlib.contextmanager
def granted(job_id: str):
    """Only pipeline/runner.py calls this, right after Steven clicked Approve (release invariant 10)."""
    _granted.append(job_id)
    try:
        yield
    finally:
        _granted.remove(job_id)
