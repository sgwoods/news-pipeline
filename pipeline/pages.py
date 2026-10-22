"""Sources without RSS: discover article URLs from a sitemap or a listing page.

A page source spec (from source_hints.yaml, stored in sources.yaml once verified):
  method:  sitemap | listing
  url:     the sitemap.xml or listing page
  include: path fragments an article URL must contain, e.g. ["/blog/"]
  exclude: extra fragments that disqualify a URL
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

DEFAULT_EXCLUDE = ["/tag/", "/tags/", "/category/", "/categories/", "/author/", "/authors/",
                   "/page/", "/feed", ".xml", ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
                   ".css", ".js", "mailto:", "/search", "/login", "/careers"]
_HREF_RE = re.compile(r'<a\b[^>]*href=["\']([^"\'#]+)', re.I)
MAX_CHILD_SITEMAPS = 40


def _host(u: str) -> str:
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def matches(url: str, base_url: str, include, exclude=()) -> bool:
    if _host(url) != _host(base_url):
        return False
    low = url.lower()
    if "?" in low or any(x in low for x in list(exclude or []) + DEFAULT_EXCLUDE):
        return False
    path = urlparse(url).path
    for inc in include or ["/"]:
        if inc in path and path.rstrip("/") != inc.rstrip("/"):
            return True
    return False


def _strip_ns(root):
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_sitemap(xml_text: str):
    """→ ("index", [child sitemap urls]) or ("urlset", [(loc, lastmod), ...])."""
    root = _strip_ns(ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text))
    if root.tag == "sitemapindex":
        return "index", [s.findtext("loc", "").strip() for s in root.findall("sitemap")]
    return "urlset", [(u.findtext("loc", "").strip(), (u.findtext("lastmod") or "").strip())
                      for u in root.findall("url")]


def links_from_html(html: str, page_url: str) -> list:
    out = []
    for h in _HREF_RE.findall(html):
        u = urljoin(page_url, h.strip())
        if u not in out:
            out.append(u)
    return out


def discover(client, spec: dict) -> list:
    """Return [(url, lastmod_or_empty)] for article URLs matching the spec."""
    method, url = spec["method"], spec["url"]
    include, exclude = spec.get("include") or ["/"], spec.get("exclude") or []
    found = []
    if method == "sitemap":
        queue, visited = [url], 0
        while queue and visited <= MAX_CHILD_SITEMAPS:
            sm = queue.pop(0)
            visited += 1
            r = client.get(sm)
            if r.status_code != 200:
                if sm == url:
                    raise RuntimeError(f"sitemap HTTP {r.status_code}")
                continue
            kind, entries = parse_sitemap(r.content)
            if kind == "index":
                # prefer child sitemaps whose name hints at the content we want
                hinted = [c for c in entries if any(i.strip("/") and i.strip("/") in c for i in include)]
                queue += hinted + [c for c in entries if c not in hinted]
            else:
                found += entries
    elif method == "listing":
        r = client.get(url)
        if r.status_code != 200:
            raise RuntimeError(f"listing HTTP {r.status_code}")
        found = [(u, "") for u in links_from_html(r.text, str(r.url))]
    else:
        raise ValueError(f"unknown page method {method!r}")
    out, seen = [], set()
    for u, lm in found:
        if u and u not in seen and matches(u, url, include, exclude):
            seen.add(u)
            out.append((u, lm))
    return out
