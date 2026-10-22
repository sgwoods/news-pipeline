"""The only way the pipeline talks to Gmail: a least-privilege wrapper around an IMAP connection.

The app password can open the whole mailbox, so the code that uses it is fenced in:
  select   only the labels in ALLOWED (sources, feedback); read-only unless writes are enabled for that call
  read     SEARCH and FETCH (by sequence or UID)
  write    only UID STORE +X-GM-LABELS, with every label under "AI-Briefing/" (the day labels); nothing else:
           no COPY/MOVE/EXPUNGE/DELETE/APPEND/CREATE/RENAME, no flag changes, no removing labels
Every operation is appended to data/state/mail-audit.jsonl (operation, folder, counts, never content).
Anything outside these rules raises MailGuardError before reaching Gmail.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

AUDIT = "data/state/mail-audit.jsonl"
LABEL_PREFIX = "AI-Briefing/"
_ROOT = Path(__file__).resolve().parent.parent


class MailGuardError(RuntimeError):
    pass


def allowed_folders(cfg: dict, purpose: str = "") -> set:
    """The Gmail labels a purpose may open (the briefing's sources and feedback labels)."""
    m = cfg.get("email_sources") or {}
    f = cfg.get("feedback") or {}
    labels = {m.get("label", "AI-Briefing/Sources"), f.get("label", "AI-Briefing/Feedback")}
    return labels


_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_LABELS_ARG = re.compile(r'^\((?:\s*"AI-Briefing/[^"\\\x00-\x1f]+")+\s*\)$')


def _clean_args(args) -> None:
    """No CR/LF or other control characters in anything sent to the server (IMAP command injection)."""
    for a in args:
        s = a.decode("latin-1") if isinstance(a, (bytes, bytearray)) else str(a if a is not None else "")
        if _CTRL.search(s):
            raise MailGuardError("mailbox guard: control characters in an IMAP argument")


class GuardedIMAP:
    def __init__(self, box, cfg: dict, purpose: str, root: Path | None = None):
        self.__box, self._allowed, self._purpose = box, allowed_folders(cfg, purpose), purpose
        self._root = root or _ROOT
        self._folder, self._writable = None, False

    # ---- audit ----
    def _log(self, op: str, **kw) -> None:
        try:
            p = self._root / AUDIT
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "purpose": self._purpose,
                                     "op": op, "folder": self._folder, **kw}) + "\n")
        except OSError:
            pass

    # ---- allowed operations ----
    def select(self, folder: str, readonly: bool = True):
        _clean_args([folder])
        name = folder.strip().strip('"').replace('\\"', '"')
        if name not in self._allowed:
            self._log("refused-select", target=name)
            raise MailGuardError(f"mailbox guard: folder {name!r} is not allowed (only {sorted(self._allowed)})")
        self._folder, self._writable = name, not readonly
        self._log("select", readonly=readonly)
        return self.__box.select('"' + name.replace('"', '\\"') + '"', readonly=readonly)

    def _need_folder(self):
        if self._folder is None:
            raise MailGuardError("mailbox guard: select an allowed folder first")

    def search(self, charset, *criteria):
        self._need_folder()
        _clean_args(criteria)
        typ, data = self.__box.search(charset, *criteria)
        self._log("search", hits=len(data[0].split()) if typ == "OK" and data and data[0] else 0)
        return typ, data

    def fetch(self, msg_set, parts):
        self._need_folder()
        _clean_args([msg_set, parts])
        if not re.fullmatch(r"\(?(RFC822|BODY\.PEEK\[\]|RFC822\.HEADER)\)?", str(parts).strip(), re.I):
            raise MailGuardError(f"mailbox guard: fetch of {parts!r} not allowed")
        self._log("fetch")
        return self.__box.fetch(msg_set, parts)

    def uid(self, command: str, *args):
        self._need_folder()
        _clean_args(args)
        cmd = command.upper()
        if cmd == "SEARCH":
            typ, data = self.__box.uid("SEARCH", *args)
            self._log("uid-search", hits=len(data[0].split()) if typ == "OK" and data and data[0] else 0)
            return typ, data
        if cmd == "FETCH":
            if len(args) < 2 or not re.fullmatch(r"\(?(RFC822|BODY\.PEEK\[\])\)?", str(args[1]).strip(), re.I):
                raise MailGuardError("mailbox guard: uid fetch form not allowed")
            self._log("uid-fetch")
            return self.__box.uid("FETCH", *args)
        if cmd == "STORE":
            if not self._writable:
                raise MailGuardError("mailbox guard: folder was selected read-only")
            if len(args) != 3 or args[1] != "+X-GM-LABELS":
                self._log("refused-store", form=str(args[1:2]))
                raise MailGuardError("mailbox guard: only adding labels (+X-GM-LABELS) is allowed")
            labels = re.findall(r'"([^"]+)"', str(args[2]))
            if not _LABELS_ARG.fullmatch(str(args[2]).strip()) or not labels or any(".." in lab for lab in labels):
                self._log("refused-store", labels=labels)
                raise MailGuardError(f"mailbox guard: labels must be under {LABEL_PREFIX!r}: {labels}")
            self._log("label", labels=labels)
            return self.__box.uid("STORE", *args)
        self._log("refused-uid", command=cmd)
        raise MailGuardError(f"mailbox guard: UID {cmd} is not allowed")

    def logout(self):
        self._log("logout")
        try:
            return self.__box.logout()
        except Exception:  # noqa: BLE001
            return None

    def __getattr__(self, name):            # copy, move, expunge, store, append, create, delete, ... -> refused
        raise MailGuardError(f"mailbox guard: IMAP {name.upper()} is not allowed")
