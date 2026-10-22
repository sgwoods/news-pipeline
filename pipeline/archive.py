"""Append-only archive on plain files. Nothing in here ever deletes or rewrites history.

data/raw/YYYY-MM-DD/items.jsonl   every new item fetched that day (full text + source URL)
data/index.jsonl                  one line per item ever seen (dedupe + retrospective entry point)
data/runs.jsonl                   one line per pipeline run (status, per-stage results)
data/state/<key>.json             small per-source state (e.g. page URLs already seen)
data/run_current.json             live status of an in-progress run (for the dashboard; not committed)
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def append_jsonl(path: Path, rows) -> int:
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n")
    return len(rows)


def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue  # never crash on a damaged line; it stays in the file
    return out


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


class Archive:
    def __init__(self, root: Path, paths: dict):
        self.root = root
        self.raw_dir = root / paths.get("raw", "data/raw")
        self.index_path = root / paths.get("index", "data/index.jsonl")
        self.runs_path = root / paths.get("runs", "data/runs.jsonl")
        self.state_dir = root / paths.get("state", "data/state")
        self.current_path = root / paths.get("run_current", "data/run_current.json")

    # ---- items ----
    def raw_file(self, day: str) -> Path:
        return self.raw_dir / day / "items.jsonl"

    def known_ids(self) -> set:
        return {r.get("id") for r in read_jsonl(self.index_path)}

    def add_items(self, items: list, day: str) -> int:
        """Append only items whose id isn't already in the index. Returns count added."""
        known = self.known_ids()
        new, seen = [], set()
        for it in items:
            if it["id"] in known or it["id"] in seen:
                continue
            seen.add(it["id"])
            new.append(it)
        raw = self.raw_file(day)
        append_jsonl(raw, new)
        rel = str(raw.relative_to(self.root))
        append_jsonl(self.index_path, [{
            "id": it["id"], "url": it["url"], "title": it.get("title", ""),
            "person": it.get("person", ""), "source_kind": it.get("source_kind", ""),
            "published": it.get("published", ""), "first_seen": day,
            "run_id": it.get("run_id", ""), "raw": rel} for it in new])
        return len(new)

    # ---- runs ----
    def append_run(self, record: dict) -> None:
        append_jsonl(self.runs_path, [record])

    def write_current(self, record: dict) -> None:
        self.current_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.current_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.current_path)

    # ---- per-source state ----
    def load_state(self, key: str):
        p = self.state_dir / f"{slug(key)}.json"
        return json.loads(p.read_text("utf-8")) if p.exists() else None

    def save_state(self, key: str, state: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / f"{slug(key)}.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")

    # ---- git ----
    def git_commit(self, message: str, paths=("data", "briefings", "sources.yaml")) -> str:
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        from .env import staging
        if staging(self.root):                           # staging outputs are thrown away, never committed
            return "not committed (staging)"
        existing = [p for p in paths if (self.root / p).exists()]
        if not existing:
            return "nothing to commit"
        r = git("add", "--", *existing)
        if r.returncode:
            return f"git add failed: {r.stderr.strip()}"
        if git("diff", "--cached", "--quiet").returncode == 0:
            return "nothing to commit"
        r = git("commit", "-q", "-m", message)
        return "committed" if r.returncode == 0 else f"git commit failed: {r.stderr.strip()}"
