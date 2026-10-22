"""Requests to URLs that came from content (links in posts, newsletters, model output) may only reach the
public internet: never localhost, the LAN, link-local or cloud-metadata addresses (server-side request
forgery from the Mac). Applied to every request, including each redirect hop, via an httpx event hook."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class BlockedURL(RuntimeError):
    pass


_BAD_SUFFIX = (".local", ".lan", ".internal", ".home", ".localhost", ".arpa")


_CACHE: dict = {}


def _host_ok(host: str) -> bool:
    """Checked again after 60 s at most (a long cache would widen a DNS-rebinding window)."""
    import time
    hit = _CACHE.get(host)
    if hit and time.monotonic() - hit[1] < 60:
        return hit[0]
    ok = _host_ok_now(host)
    _CACHE[host] = (ok, time.monotonic())
    return ok


def _host_ok_now(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith(_BAD_SUFFIX):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def is_public_url(url: str) -> bool:
    u = urlparse(url or "")
    return u.scheme in ("http", "https") and _host_ok(u.hostname or "")


def check(url: str) -> None:
    if not is_public_url(url):
        raise BlockedURL(f"blocked non-public URL: {urlparse(url or '').hostname or url!r}")


def hook(request) -> None:
    """httpx event hook: refuse any request (including redirects) to a non-public address."""
    check(str(request.url))


def client(**kw):
    import httpx
    hooks = kw.pop("event_hooks", {}) or {}
    hooks.setdefault("request", []).append(hook)
    return httpx.Client(event_hooks=hooks, **kw)
