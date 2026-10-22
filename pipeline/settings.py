"""Change single values in config.yaml without disturbing comments or layout.

Used by the dashboard (e.g. "Use this voice") and setup scripts. Only edits an existing
`  key: value` line inside a top-level `section:` block.
"""
from __future__ import annotations

import re
from pathlib import Path


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value)
    return s if re.fullmatch(r"[A-Za-z0-9_.:/+-]+", s) else '"' + s.replace('"', '\\"') + '"'


def set_value(path: Path, section: str, key: str, value) -> bool:
    lines = path.read_text("utf-8").splitlines(keepends=True)
    in_sec = False
    for i, ln in enumerate(lines):
        if re.match(r"^\S", ln):
            in_sec = ln.startswith(f"{section}:")
            continue
        m = re.match(rf"^(  {re.escape(key)}:\s*)(\S.*?|)(\s+#.*)?(\n?)$", ln) if in_sec else None
        if m:
            old_val, comment, new_val = m.group(2), m.group(3) or "", _fmt(value)
            if comment:   # keep the comment's column
                gap = len(comment) - len(comment.lstrip())
                comment = " " * max(1, len(old_val) + gap - len(new_val)) + comment.lstrip()
            lines[i] = f"{m.group(1)}{new_val}{comment}{m.group(4)}"
            path.write_text("".join(lines), "utf-8")
            return True
    return False
