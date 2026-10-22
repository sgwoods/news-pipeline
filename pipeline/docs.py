"""Public documentation on the site: <site>/docs/, rebuilt at every publish from the same markdown as the public
code repo, so there is one source and it can't drift.

- Pages: DOCS below (each scrubbed like the public code export: PRIVATE blocks removed, owner details replaced),
  with the diagrams in docs/img/ embedded. Each page shows the running version and when the file last changed.
- Generated sections: `<!-- GENERATED: components -->` becomes the component table (every public module's own
  one-line description) and `<!-- GENERATED: facts -->` the current facts (release, schedule, models). The public
  code export expands them the same way.
- Drift checks (tests/test_docs.py): the architecture page names the current version, and every module it names exists.
"""
from __future__ import annotations

import ast
import datetime as dt
import html as htmllib
import re
import shutil
import subprocess
from pathlib import Path


def _clean_env() -> dict:
    """The environment without GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE: git here always acts on the repo at cwd."""
    import os
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}

ROOT = Path(__file__).resolve().parent.parent
DOCS = [("ARCHITECTURE.md", "architecture", "Architecture", "How the pipeline is built: stages, components, privacy, repositories, releases."),
        ("FACT-CHECKING.md", "fact-checking", "Fact checking", "What is checked before anything goes out."),
        ("SOURCE-PROFILES.md", "source-profiles", "Source profiles", "Weighing evidence by the kind of source."),
        ("DEEP-DIVES.md", "deep-dives", "Deep dives", "The second segment: how topics are chosen and made.")]
MARK = re.compile(r"^<!-- GENERATED: (\w+) -->\s*$", re.M)


def public_modules(root: Path = ROOT) -> list:
    """[(module, one-line description)] for pipeline/*.py that the public export includes."""
    import fnmatch
    from .owner import get as owner
    excl = list(owner(root).get("export_exclude") or [])
    out = []
    for p in sorted((root / "pipeline").glob("*.py")):
        rel = f"pipeline/{p.name}"
        if p.name == "__init__.py" or any(fnmatch.fnmatch(rel, g) for g in excl):
            continue
        try:
            doc = ast.get_docstring(ast.parse(p.read_text("utf-8"))) or ""
        except SyntaxError:
            doc = ""
        first = re.split(r"(?<=[.:])\s", doc.strip().split("\n\n")[0].replace("\n", " "), maxsplit=1)[0] if doc else ""
        out.append((p.name, first.rstrip(":")))
    return out


def _components(root: Path) -> str:
    rows = "\n".join(f"| `{m}` | {d.replace('|', '/')} |" for m, d in public_modules(root))
    return ("_Generated from each module's own description at build time._\n\n| Module | Purpose |\n|---|---|\n" + rows + "\n")


def _facts(root: Path, cfg: dict) -> str:
    from .version import full, releases
    rel = releases(root)
    when = rel[0][0].split("·")[-1].strip() if rel else ""
    times = ", ".join((cfg.get("schedule") or {}).get("times") or [])
    local = ((cfg.get("llm") or {}).get("local") or {}).get("model") or ""
    lines = [f"- **Release:** v{full(root)}" + (f" ({when})" if when else ""),
             f"- **Schedule:** daily at {times} (local time; later times are retries)" if times else "",
             f"- **Local model:** {local}" if local else "",
             f"- **Modules:** {len(public_modules(root))} in `pipeline/`"]
    return "_Generated at build time._\n\n" + "\n".join(x for x in lines if x) + "\n"


def expand(text: str, root: Path = ROOT, cfg: dict | None = None) -> str:
    def sub(m):
        kind = m.group(1)
        if kind == "components":
            return _components(root)
        if kind == "facts":
            return _facts(root, cfg or {})
        return m.group(0)
    return MARK.sub(sub, text)


def last_changed(root: Path, rel: str) -> str:
    r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", rel], cwd=root, env=_clean_env(), capture_output=True, text=True)
    return r.stdout.strip() or dt.date.today().isoformat()


def render_md(text: str) -> str:
    import markdown
    body = markdown.markdown(text.replace("&", "&amp;").replace("<", "&lt;").replace("&lt;br>", "<br>"),
                             extensions=["tables", "fenced_code"])
    slugs = {f: s for f, s, _, _ in DOCS}

    def link(m):
        u = m.group(1)
        if re.match(r"https?://|#", u):
            return f'href="{u}"' + (' rel="noopener" target="_blank"' if u.startswith("http") else "")
        name = u.split("/")[-1].split("#")[0]
        if name in slugs:
            return f'href="{slugs[name]}.html"'
        if name == "CHANGELOG.md":
            return 'href="../releases/index.html"'
        return 'href="#"'
    return re.sub(r'href="([^"]*)"', link, body)


def build(root: Path, cfg: dict, out: Path, page) -> int:
    """Write <out>/docs/: an index and one page per doc. `page(title, body, rel, cfg)` is site._page."""
    from . import scrub as export
    from .owner import get as owner
    from .version import full
    o = owner(root)
    d = out / "docs"
    (d / "img").mkdir(parents=True, exist_ok=True)
    for svg in (root / "docs" / "img").glob("*.svg"):
        (d / "img" / svg.name).write_text(export.scrub(svg.read_text("utf-8"), o), "utf-8")
    items, n = [], 0
    for fname, slug, title, blurb in DOCS:
        src = root / "docs" / fname
        if not src.is_file():
            continue
        text = expand(export.scrub(src.read_text("utf-8"), o), root, cfg)
        meta = (f'<p class="small muted">Running v{htmllib.escape(full(root))} · this page last changed '
                f'{last_changed(root, f"docs/{fname}")} · <a href="index.html">All docs</a></p>')
        (d / f"{slug}.html").write_text(page(f"AI Briefing · {title}", meta + f'<div class="doc">{render_md(text)}</div>',
                                             "../", cfg), "utf-8")
        items.append(f'<li><a href="{slug}.html"><b>{htmllib.escape(title)}</b></a> · {htmllib.escape(blurb)}</li>')
        n += 1
    items.append('<li><a href="../releases/index.html"><b>Release notes</b></a> · what changed in each release.</li>')
    code = cfg.get("code_repo") or ""
    if code:
        items.append(f'<li><a href="https://github.com/{htmllib.escape(code)}"><b>Source code</b></a> · the public '
                     f'repository (MIT).</li>')
    (d / "index.html").write_text(page("AI Briefing · Documentation",
                                       f'<h1>Documentation</h1><p class="muted">Running v{htmllib.escape(full(root))}. '
                                       f'Rebuilt at every publish from the project\'s own docs.</p><ul>{"".join(items)}</ul>',
                                       "../", cfg), "utf-8")
    return n
