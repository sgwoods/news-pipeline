"""Records every run: per-stage status, counts, errors, timings → data/runs.jsonl.

Also keeps data/run_current.json up to date while a run is in progress, and writes a
plain-text log to logs/run-<run_id>.log.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from .archive import Archive

STAGES = ["fetch", "filter", "rank", "critique", "cluster", "editorial", "write", "audio"]


class Run:
    def __init__(self, archive: Archive, logs_dir: Path, cfg: dict):
        now = dt.datetime.now().astimezone()
        self.archive = archive
        self.run_id = now.strftime("%Y%m%dT%H%M%S")
        n = 1
        while (logs_dir / f"run-{self.run_id}.log").exists():   # two runs in the same second
            n += 1
            self.run_id = now.strftime("%Y%m%dT%H%M%S") + f"-{n}"
        self.day = now.strftime("%Y-%m-%d")
        llm = cfg.get("llm", {})
        backend = llm.get("backend", "")
        self.record = {
            "run_id": self.run_id, "day": self.day, "started": now.isoformat(timespec="seconds"),
            "ended": None, "status": "running",
            "llm": {"backend": backend, "model": (llm.get(backend) or {}).get("model", ""),
                    "stages": llm.get("stages") or {}},
            "stages": {s: {"status": "pending"} for s in STAGES},
            "log": f"logs/run-{self.run_id}.log",
        }
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(f"run.{self.run_id}")
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
        for h in (logging.FileHandler(logs_dir / f"run-{self.run_id}.log", encoding="utf-8"),
                  logging.StreamHandler()):
            h.setFormatter(fmt)
            self.log.addHandler(h)
        self._flush()

    def _flush(self):
        self.archive.write_current(self.record)

    @contextmanager
    def stage(self, name: str):
        rec = {"status": "running", "started": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        self.record["stages"][name] = rec
        self._flush()
        self.log.info("stage %s: start", name)
        t0 = time.monotonic()
        try:
            yield rec
            rec["status"] = rec.get("status") if rec.get("status") not in ("running", None) else "ok"
        except Exception as e:
            rec["status"] = "error"
            rec["error"] = f"{type(e).__name__}: {e}"
            self.log.error("stage %s failed: %s\n%s", name, e, traceback.format_exc())
            raise
        finally:
            rec["seconds"] = round(time.monotonic() - t0, 1)
            self.log.info("stage %s: %s (%.1fs)", name, rec["status"], rec["seconds"])
            self._flush()

    def skip(self, name: str, reason: str):
        self.record["stages"][name] = {"status": "skipped", "reason": reason}
        self._flush()

    def finish(self, status: str):
        self.record["status"] = status
        self.record["ended"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        self.archive.append_run(self.record)
        self._flush()
        self.log.info("run %s finished: %s", self.run_id, status)
