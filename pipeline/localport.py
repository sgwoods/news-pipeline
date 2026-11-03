"""Shared localhost agreement (Steven, 2026-11-02): several projects run local web servers on the same Macs.

    Ports      Project              Default
    8760-8769  virtual-bookshelf    8765
    8770-8779  news pipeline        8775    <- this project
    8780-8789  aurora               8785
    8790-8799  Star Swarm (game)    8795

Rules this module enforces for the dashboard:
- stay in our block, bind 127.0.0.1 only; default port first, then only the other ports in the block; if the whole
  block is busy, stop and name the processes holding it;
- one copy at a time: ~/.config/news-pipeline/server.json holds {pid, port, started}. If that pid is alive and its
  /whoami names this project, ask it to stop (SIGTERM), kill it after a few seconds, wait for the port, take it.
  Never stop a process whose /whoami names another project or that does not answer /whoami;
- GET /whoami -> {"project", "port", "pid", "version"} (dashboard/app.py);
- ~/.config/local-ports.tsv is the shared registry: we add our own line (and a header if the file is new), never
  edit anyone else's, and warn when our block overlaps another line;
- `./np dash --status` reads the registry and asks every project's ports for /whoami.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

PROJECT = "news-pipeline"
LABEL = "News"
FIRST, LAST = 8770, 8779
DEFAULT = 8775
ICON = "📰"
HEADER = "# name\tports\tdefault\trepo"


class PortsBusy(RuntimeError):
    pass


def home() -> Path:
    return Path(os.environ.get("NP_PORTS_HOME") or Path.home())      # tests point this at a temp dir


def state_path(h: Path | None = None) -> Path:
    return (h or home()) / ".config" / PROJECT / "server.json"


def registry_path(h: Path | None = None) -> Path:
    return (h or home()) / ".config" / "local-ports.tsv"


def block() -> list:
    return [DEFAULT] + [p for p in range(FIRST, LAST + 1) if p != DEFAULT]


def in_block(port: int) -> bool:
    return FIRST <= int(port) <= LAST


# ---- probing -------------------------------------------------------------------------------------------------

def whoami(port: int, timeout: float = 0.8) -> dict | None:
    """The server's own answer on 127.0.0.1:port, or None (nothing there, or it doesn't speak /whoami)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/whoami", timeout=timeout) as r:
            d = json.loads(r.read(4096).decode("utf-8", "replace"))
            return d if isinstance(d, dict) and d.get("project") else None
    except Exception:  # noqa: BLE001 - refused, timeout, not JSON: all mean "not a server we can identify"
        return None


def free(port: int) -> bool:
    """Nothing listens on the port (on any address) and we could bind 127.0.0.1:port the way the server does
    (SO_REUSEADDR, so a just-closed copy's TIME_WAIT does not count as busy)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as c:
        c.settimeout(0.5)
        if c.connect_ex(("127.0.0.1", int(port))) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", int(port)))
            return True
        except OSError:
            return False


def alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def holder(port: int) -> str:
    """'pid command' of whatever listens on port (best effort, via lsof), plus its /whoami project if it has one."""
    who = whoami(port, 0.4)
    tag = f" (whoami: {who['project']})" if who else ""
    try:
        r = subprocess.run(["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fpc"],
                           capture_output=True, text=True, timeout=5)
        pid = next((ln[1:] for ln in r.stdout.splitlines() if ln.startswith("p")), "")
        cmd = next((ln[1:] for ln in r.stdout.splitlines() if ln.startswith("c")), "")
        if pid:
            return f"pid {pid} {cmd}{tag}"
    except (OSError, subprocess.SubprocessError):
        pass
    return f"unknown process{tag}"


# ---- one copy at a time --------------------------------------------------------------------------------------

def read_state(h: Path | None = None) -> dict:
    try:
        d = json.loads(state_path(h).read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(port: int, pid: int | None = None, h: Path | None = None) -> dict:
    d = {"pid": pid or os.getpid(), "port": int(port), "started": dt.datetime.now().isoformat(timespec="seconds")}
    p = state_path(h)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d) + "\n", "utf-8")
    tmp.replace(p)
    return d


def clear_state(pid: int | None = None, h: Path | None = None) -> None:
    """On a clean exit: remove the file, but only if it still names us (a newer copy may have taken over)."""
    if read_state(h).get("pid") == (pid or os.getpid()):
        try:
            state_path(h).unlink()
        except OSError:
            pass


def replace_old(h: Path | None = None, log=print, grace: float = 4.0, port_wait: float = 10.0) -> int | None:
    """Stop our own older copy named in server.json. Returns the port it freed, or None.
    Only a live pid whose /whoami says this project (and, when it reports one, this pid) is ever signalled."""
    st = read_state(h)
    pid, port = st.get("pid"), st.get("port")
    if not pid or not port or pid == os.getpid():
        return None
    if not alive(pid):
        return None                                       # stale file from a crash: nothing to stop
    who = whoami(port)
    if not who or who.get("project") != PROJECT or (who.get("pid") not in (None, pid)):
        log(f"{PROJECT}: pid {pid} on port {port} is not this project's server "
            f"({'whoami: ' + who['project'] if who else 'no /whoami answer'}); leaving it alone")
        return None
    log(f"{PROJECT}: stopping the older copy (pid {pid}, port {port})")
    try:
        os.kill(pid, signal.SIGTERM)                      # ask
    except OSError:
        pass
    end = time.time() + grace
    while time.time() < end and alive(pid):
        time.sleep(0.1)
    if alive(pid):
        log(f"{PROJECT}: pid {pid} did not stop in {grace:.0f}s; killing it")
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    end = time.time() + port_wait
    while time.time() < end and not free(port):
        time.sleep(0.1)
    return int(port) if in_block(port) else None


def choose(prefer: int | None = None) -> int:
    """The port to bind: prefer (a port we just freed) if it is in the block, then the default, then the rest of
    the block. Never a port outside 8770-8779."""
    order = block()
    if prefer and in_block(prefer):
        order = [prefer] + [p for p in order if p != prefer]
    for p in order:
        if free(p):
            return p
    held = "; ".join(f"{p}: {holder(p)}" for p in range(FIRST, LAST + 1))
    raise PortsBusy(f"{PROJECT}: every port in {FIRST}-{LAST} is busy, so the dashboard did not start. Held by: {held}")


# ---- shared registry -----------------------------------------------------------------------------------------

def _parse(line: str) -> dict | None:
    parts = line.rstrip("\n").split("\t")
    if not line.strip() or line.lstrip().startswith("#") or len(parts) < 2:
        return None
    try:
        a, b = (int(x) for x in parts[1].split("-", 1))
    except ValueError:
        return None
    return {"name": parts[0].strip(), "first": a, "last": b,
            "default": int(parts[2]) if len(parts) > 2 and parts[2].strip().isdigit() else a,
            "repo": parts[3].strip() if len(parts) > 3 else ""}


def registry(h: Path | None = None) -> list:
    try:
        return [r for r in (_parse(ln) for ln in registry_path(h).read_text("utf-8").splitlines()) if r]
    except OSError:
        return []


def ensure_registry(repo: str, h: Path | None = None, log=print) -> list:
    """Add our line if it is missing (create the file with a header first). Other lines are never touched.
    Returns warnings about blocks that overlap ours."""
    p = registry_path(h)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(HEADER + "\n", "utf-8")
    rows = registry(h)
    if not any(r["name"] == PROJECT for r in rows):
        text = p.read_text("utf-8")
        with p.open("a", encoding="utf-8") as f:
            f.write(("" if text.endswith("\n") or not text else "\n") + f"{PROJECT}\t{FIRST}-{LAST}\t{DEFAULT}\t{repo}\n")
        rows = registry(h)
    warns = [f"{PROJECT}: port block {FIRST}-{LAST} overlaps {r['name']} ({r['first']}-{r['last']}) in {p}"
             for r in rows if r["name"] != PROJECT and r["first"] <= LAST and r["last"] >= FIRST]
    for w in warns:
        log("WARNING " + w)
    return warns


def status(h: Path | None = None, out=print) -> list:
    """Which registered projects are running, on which port and version (every port in every block asks /whoami)."""
    rows = registry(h) or [{"name": PROJECT, "first": FIRST, "last": LAST, "default": DEFAULT, "repo": ""}]
    found = []
    for r in rows:
        hits = []
        for port in range(r["first"], r["last"] + 1):
            w = whoami(port, 0.5)
            if w:
                hits.append((port, w))
        if not hits:
            out(f"{r['name']:<20} {r['first']}-{r['last']}  not running")
        for port, w in hits:
            other = "" if w.get("project") == r["name"] else f"  (answers as {w.get('project')}: outside its block)"
            out(f"{r['name']:<20} {r['first']}-{r['last']}  running on {port} · pid {w.get('pid', '?')} · "
                f"version {w.get('version', '?')}{other}")
            found.append({"block": r["name"], "port": port, **w})
    return found


# ---- startup -------------------------------------------------------------------------------------------------

def claim(repo: str, log=print) -> int:
    """Everything the agreement asks for before binding: registry line + overlap warning, replace our older copy,
    pick a port in the block. Raises PortsBusy."""
    ensure_registry(repo, log=log)
    freed = replace_old(log=log)
    return choose(freed)


def url(path: str = "") -> str:
    """The dashboard's address for links in notes and messages: the running copy's port, else the default."""
    st = read_state()
    port = st.get("port") if st.get("pid") and alive(st["pid"]) and in_block(st.get("port") or 0) else DEFAULT
    return f"http://127.0.0.1:{port}{path}"
