#!/usr/bin/env python3
"""Daily AI news pipeline. One command: python run.py"""
from __future__ import annotations

import argparse
import re
import datetime as dt
import sys
from pathlib import Path

import yaml

from pipeline import fetch, llm, perspective, sources, stages
from pipeline.archive import Archive
from pipeline.runlog import Run

ROOT = Path(__file__).resolve().parent


def load_config(profile: str | None = None) -> dict:
    """config.yaml with the active tuning profile (or `profile`) overlaid: see pipeline/tuning.py."""
    from pipeline import tuning
    raw = yaml.safe_load((ROOT / "config.yaml").read_text("utf-8")) or {}
    return tuning.apply(raw, ROOT, profile)


def experiment_dir(cfg: dict, day: str) -> Path:
    return ROOT / cfg["paths"]["briefings"] / "experiments" / day


def cmd_verify_sources(cfg: dict, force: bool = False) -> int:
    paths = cfg["paths"]
    persp = perspective.load(ROOT / paths["perspective"])
    hints_file = ROOT / paths["source_hints"]
    hints = yaml.safe_load(hints_file.read_text("utf-8")) if hints_file.exists() else {}
    from pipeline import suggest
    managed = suggest.load_managed(ROOT)
    m_people, m_hints = suggest.managed_people(managed)
    names = {p.name for p in persp.people}
    people = persp.people + [p for p in m_people if p.name not in names]
    hints = {**(hints or {}), **{k: v for k, v in m_hints.items() if k not in (hints or {})}}
    print(f"Verifying feeds for {len(persp.people)} tracked people + {len(people) - len(persp.people)} added "
          f"on the Sources page...")
    summary = sources.verify_all(people, hints, cfg)
    removed = suggest.removed_urls(managed)
    if removed:
        def url_of(r):
            return sources.split_page_candidate(r.winner.url)[1] if r.group.kind == "pages" else r.winner.url
        skipped = [r for r in summary["results"] if r.winner and url_of(r) in removed]
        summary["results"] = [r for r in summary["results"] if r not in skipped]
        for r in skipped:
            print(f"  skip {r.group.person} [{r.group.label}]: removed on the Sources page")
    target = ROOT / paths["sources"]
    prev = 0
    if target.exists():
        prev = len((yaml.safe_load(target.read_text("utf-8")) or {}).get("sources") or [])
    n_ok = len({r.winner.url for r in summary["results"] if r.winner})
    if prev and n_ok < prev / 2 and not force:
        # Probably offline or a bad run: don't clobber a good sources.yaml.
        target = target.with_name("sources.new.yaml")
        print(f"\nWARNING: only {n_ok} feeds verified vs {prev} before. Kept {paths['sources']} "
              f"unchanged and wrote {target.name} instead. Use --force to overwrite.")
    n = sources.write_sources_yaml(summary, target)
    logs = ROOT / paths["logs"]
    logs.mkdir(exist_ok=True)
    report = logs / f"source-verification-{dt.date.today()}.md"
    sources.write_report(summary, report)
    failed = sum(1 for r in summary["results"] if not r.winner)
    print(f"\n{n} verified feeds -> {target.name}; {failed} failed; "
          f"{len(summary['no_candidates'])} with no candidates.\nReport: {report.relative_to(ROOT)}")
    return 0


def _sources_commit(cfg: dict, msg: str) -> None:
    if cfg.get("archive", {}).get("git_commit", True):
        r = Archive(ROOT, cfg["paths"]).git_commit(msg, paths=("data/sources", "sources_managed.yaml", cfg["paths"]["sources"]))
        print(f"git: {r}")


def cmd_sources(cfg: dict, argv: list) -> int:
    """./np sources list | suggest [N] | find NAME [NOTE] | add NAME URL [URL] [NOTE] | accept ID | deny ID [REASON] |
    reconsider ID | recheck ID | remove URL [REASON] | restore URL"""
    from pipeline import suggest
    sub, rest = (argv[0] if argv else "list"), argv[1:]
    store = suggest.load_store(ROOT)
    if sub == "list":
        groups = suggest.summary(store)
        for st in suggest.STATUSES:
            print(f"\n{st.upper()} ({len(groups[st])})")
            for x in groups[st]:
                src = ", ".join(v["url"] + (" (STALE)" if suggest.is_stale(v, suggest.stale_days(cfg)) else "")
                                for v in x.get("verified") or []) or "no live web source"
                print(f"  {x['id']}  {x['name']} — {x.get('why', '')[:110]}\n            {src}")
        return 0
    if sub == "suggest":
        n = int(rest[0]) if rest else int((cfg.get("suggest") or {}).get("count", 10))
        print(f"Asking for {n} suggestions (Claude may search the web; ~2-6 min)...")
        cands = suggest.ask_suggestions(ROOT, cfg, n + 3, store)        # a few spare in case of dupes
        print(f"Model returned {len(cands)}: {', '.join(c['name'] for c in cands)}")
        added = suggest.enqueue(ROOT, cfg, cands, "auto", store, limit=n)
        suggest.save_store(ROOT, store)
        ok = sum(1 for a in added if a["reachable"])
        print(f"\nQueued {len(added)} suggestion(s): {ok} with a live web source, {len(added) - ok} without "
              "(kept for later, e.g. X-only).")
        _sources_commit(cfg, f"sources: {len(added)} new suggestion(s)")
        return 0
    if sub == "find":
        if not rest:
            print("usage: ./np sources find \"Full Name\" [note]")
            return 2
        name, note = rest[0].strip()[:80], " ".join(rest[1:])[:300]
        print(f"Searching for sources for {name} (~1-3 min)...")
        c = suggest.ask_find(ROOT, cfg, name, note)
        if not c:
            print("The model returned nothing usable.")
            return 1
        c["why"] = ("Added by Steven" + (f" ({note})" if note else "") + ". " + c.get("why", "")).strip()
        row = suggest.enqueue(ROOT, cfg, [c], "manual", store)[0]
        suggest.save_store(ROOT, store)
        print(f"\nQueued {row['id']} {name}: {len(row['verified'])} live source(s), {len(row['failed'])} failed"
              + ("" if row["reachable"] else "; no live web source, kept for later"))
        _sources_commit(cfg, f"sources: queued {name} (manual)")
        return 0
    if sub == "add":                             # a named source with known feed URLs: verify live, then wire in
        urls = [a for a in rest[1:] if a.startswith("https://")]
        note = " ".join(a for a in rest[1:] if not a.startswith("https://"))[:300]
        if not rest or not urls:
            print("usage: ./np sources add \"Name\" https://feed-url [https://alt-url] [note]")
            return 2
        name = rest[0].strip()[:80]
        c = {"name": name, "why": ("Added by Steven" + (f" ({note})" if note else "")).strip(), "sites": [],
             "bluesky": [], "feeds": urls}
        row = suggest.enqueue(ROOT, cfg, [c], "manual", store)[0]
        suggest.save_store(ROOT, store)
        already = [u for u in urls if u in suggest._wired_urls(ROOT, cfg)]
        if not row["reachable"] and already:
            suggest.deny(ROOT, row["id"], "already a source")
            print(f"{name}: already a source ({', '.join(already)}); nothing to add")
            _sources_commit(cfg, f"sources: {name} already tracked")
            return 0
        if not row["reachable"]:
            print(f"{name}: no feed answered ({'; '.join(str(f) for f in row['failed'])[:300]}); queued as {row['id']}, "
                  f"not wired in")
            _sources_commit(cfg, f"sources: queued {name} (no live feed)")
            return 1
        s = suggest.accept(ROOT, cfg, row["id"])
        print(f"{name}: {len(row['verified'])} live feed(s) verified and wired in ({s['status']})")
        _sources_commit(cfg, f"sources: added {name}")
        return 0
    if sub in ("accept", "deny", "reconsider", "recheck") and not rest:
        print(f"usage: ./np sources {sub} ID")
        return 2
    if sub == "accept":
        s = suggest.accept(ROOT, cfg, rest[0], urls=rest[1:] or None)     # optional: only these channel URLs
        _sources_commit(cfg, f"sources: accepted {s['name']} ({s['status']})")
        return 0
    if sub == "deny":
        s = suggest.deny(ROOT, rest[0], " ".join(rest[1:]))
        print(f"Denied {s['name']}")
        _sources_commit(cfg, f"sources: denied {s['name']}")
        return 0
    if sub == "reconsider":
        s = suggest.reconsider(ROOT, rest[0])
        print(f"{s['name']} is back in the queue")
        _sources_commit(cfg, f"sources: reconsider {s['name']}")
        return 0
    if sub == "recheck":
        s = suggest.find(store, rest[0])
        if s["status"] not in ("pending", "watch"):
            print(f"{s['name']} is {s['status']}; only pending or watch-list entries can be rechecked")
            return 2
        row = suggest.enqueue(ROOT, cfg, [dict(s)], "recheck", store)[0]
        suggest.save_store(ROOT, store)
        print(f"{row['name']}: {len(row['verified'])} live source(s)")
        _sources_commit(cfg, f"sources: rechecked {row['name']}")
        return 0
    if sub in ("remove", "restore"):
        if not rest:
            print(f"usage: ./np sources {sub} URL")
            return 2
        if sub == "remove":
            r = suggest.remove_source(ROOT, cfg, rest[0], " ".join(rest[1:]))
            print(f"Removed {r.get('person')} [{r.get('kind')}] {rest[0]}")
        else:
            suggest.restore_source(ROOT, rest[0])
            print(f"Restored {rest[0]}: run ./np verify to wire it back in")
        _sources_commit(cfg, f"sources: {sub} {rest[0]}")
        return 0
    print(cmd_sources.__doc__)
    return 2


def cmd_x(cfg: dict, argv: list) -> int:
    """./np x [status | fetch [HOURS] | digest [DAYS] [@handle ...] | import FILE]: mirrors, Claude's weekly digest, or a browser pull"""
    import logging
    from pipeline import xdigest, xsource
    sub = argv[0] if argv else "status"
    if sub == "digest":
        rest = argv[1:]
        days = int(rest[0]) if rest and rest[0].isdigit() else None
        handles = [h for h in rest if not h.isdigit()]
        res = xdigest.digest(ROOT, cfg, "digest", print, days, handles)
        archive = Archive(ROOT, cfg["paths"])
        added = archive.add_items(res["items"], dt.date.today().isoformat())
        failed = [p["handle"] for p in res["per"] if p.get("error")]
        print(f"digest: {len(res['per'])} account(s), {len(res['items'])} post(s), {added} new archived"
              + (f"; failed: {', '.join(failed)}" if failed else ""))
        if added and cfg.get("archive", {}).get("git_commit", True):
            print("git:", archive.git_commit(f"archive: {added} X post(s) from the weekly digest"))
        return 1 if failed and not res["items"] else 0
    if sub == "import":
        if len(argv) < 2:
            print("usage: ./np x import data/raw/x-pulls/FILE.json")
            return 2
        res = xsource.import_pull(ROOT, cfg, ROOT / argv[1])
        archive = Archive(ROOT, cfg["paths"])
        added = archive.add_items(res["items"], dt.date.today().isoformat())
        print(f"import: list {res['list']!r}, {res['read']} post(s) read, {len(res['items'])} usable, {added} new archived")
        if added and cfg.get("archive", {}).get("git_commit", True):
            print("git:", archive.git_commit(f"archive: {added} X post(s) from a browser pull of {res['list']}"))
        return 0
    if sub == "status":
        st = xsource.status(ROOT)
        print(f"X mirrors: last good {st['last_good'] or 'none yet'}" + (f" · last total failure {st['last_fail'][:16]}" if st["last_fail"] else ""))
        d = xdigest._stamp(ROOT)
        print(f"Weekly Claude digest: last {d.get('at', 'never')[:16]}" + (f" · {sum(p.get('posts', 0) for p in d.get('per', []))} post(s)" if d else "")
              + (" · due now" if xdigest.due(ROOT) else ""))
        for i in st["instances"]:
            print(f"  {'OK  ' if i.get('ok') else 'FAIL' if 'ok' in i else '    '} {i['url']} {i.get('note', '')} {(i.get('at') or '')[:16]}")
        rc = xdigest.reach(ROOT)
        print("Accounts (X itself is unreachable; 'digest' items come from the weekly web search). Where else they publish:")
        for a in st["accounts"]:
            places = (rc.get(a["handle"]) or {}).get("places", [])
            print(f"  {a['tier']:14} @{a['handle']:16} {a['name']:22} {a['count']:3} archived · latest {a['latest'] or 'never'}")
            for p in places:
                print(f"      {p['kind']:10} {p['url']}  {p.get('note', '')}")
            if not places:
                print("      (nowhere else known yet)")
        for l in st.get("lists", []):
            part = "" if l.get("complete", True) else f" of {l.get('members_total', '?')} (partial)"
            print(f"  List \"{l['name']}\": {len(l['members'])} member(s){part} · {l['url']}")
        return 0
    if sub == "fetch":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        hours = int(argv[1]) if len(argv) > 1 else None
        res = xsource.fetch(ROOT, cfg, "manual", logging.getLogger("x"), hours)
        archive = Archive(ROOT, cfg["paths"])
        added = archive.add_items(res["items"], dt.date.today().isoformat())
        print(f"mirror: {res['instance'] or 'none answered'} · {len(res['items'])} post(s) in window, {added} new archived.")
        if added and cfg.get("archive", {}).get("git_commit", True):
            print("git:", archive.git_commit(f"archive: {added} X item(s) via mirror"))
        return 0 if res["instance"] else 1
    print(cmd_x.__doc__)
    return 2


def cmd_todo(cfg: dict, argv: list) -> int:
    """./np todo [list | seed | done ID [note] | reopen ID | add "title" [group]]"""
    from pipeline import todos
    sub, rest = (argv[0] if argv else "list"), argv[1:]
    if sub == "seed":
        n = todos.seed(ROOT, todos.STARTER)
        print(f"{n} new to-do(s) added")
    elif sub == "done" and rest:
        r = todos.set_status(ROOT, rest[0], "done", " ".join(rest[1:]))
        print(f"done: {r['title']}")
    elif sub == "reopen" and rest:
        r = todos.set_status(ROOT, rest[0], "open")
        print(f"reopened: {r['title']}")
    elif sub == "add" and rest:
        r = todos.add(ROOT, rest[0], rest[1] if len(rest) > 1 else "setup")
        print(f"added {r['id']}: {r['title']}")
    elif sub != "list":
        print(cmd_todo.__doc__)
        return 2
    print(todos.markdown(ROOT))
    if sub != "list" and cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"todo: {sub}", paths=("data/todos.json",)))
    return 0


def cmd_bluesky(cfg: dict, argv: list) -> int:
    """./np bluesky [status | fetch [HOURS] | find NAME...]: Steven's Bluesky list(s) + own posts as sources; find = look people up"""
    import httpx
    import logging
    from pipeline import bluesky
    b = bluesky.bcfg(cfg)
    sub = argv[0] if argv else "status"
    if sub == "find":
        names = argv[1:] or [a["name"] for a in __import__("pipeline.xsource", fromlist=["load_x"]).load_x(ROOT)["accounts"]]
        with httpx.Client(timeout=20) as c:
            for n in names:
                print(f"\n{n}:")
                for a in bluesky.find(c, n):
                    print(f"   @{a['handle']:34} {a['name'][:28]:28} {a['followers']:>7}  {a['bio']}")
        return 0
    if sub == "status":
        print(f"Bluesky: {len(b['lists'])} list(s), own posts: {b['own'] or 'off'}, lookback {b['lookback_hours']} h")
        with httpx.Client(timeout=20) as c:
            for url in b["lists"]:
                try:
                    info = bluesky.list_info(c, url)
                    print(f"  list \"{info['name']}\": {len(info['members'])} members · {url}")
                    for m in info["members"]:
                        print(f"     {m['name']:32} @{m['handle']}")
                except Exception as e:  # noqa: BLE001
                    print(f"  FAIL {url}: {type(e).__name__}: {e}")
            if b["handles"]:
                print("  individual handles (latest post, so a dead mirror shows up):")
                for h in b["handles"]:
                    if not isinstance(h, dict) or not h.get("handle"):
                        continue
                    try:
                        latest = bluesky.latest_post(c, h["handle"])
                        print(f"     @{h['handle']:36} latest {latest or 'none'}{'  (mirror)' if h.get('mirror') else ''}"
                              f"{'  max ' + str(h['max']) + '/fetch' if h.get('max') else ''}")
                    except Exception as e:  # noqa: BLE001
                        print(f"     @{h['handle']:36} FAIL {type(e).__name__}: {e}")
        return 0
    if sub == "fetch":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        hours = int(argv[1]) if len(argv) > 1 else None
        res = bluesky.fetch(cfg, "manual", logging.getLogger("bluesky"), hours)
        archive = Archive(ROOT, cfg["paths"])
        added = archive.add_items(res["items"], dt.date.today().isoformat())
        print(f"{len(res['items'])} post(s) in window, {added} new archived. Analyze with ./np analyze.")
        if cfg.get("archive", {}).get("git_commit", True):
            print("git:", archive.git_commit(f"archive: {added} Bluesky list item(s)"))
        return 0
    print(cmd_bluesky.__doc__)
    return 2


def cmd_newsletters(cfg: dict, argv: list) -> int:
    """./np newsletters [status | test | fetch [DAYS] | label [DAY]]"""
    from pipeline import mailsource
    sub = argv[0] if argv else "status"
    if sub == "label":
        day = argv[1] if len(argv) > 1 else dt.date.today().isoformat()
        try:
            mailsource.label_day(ROOT, cfg, day)
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"Gmail labels: {e}")
            return 1
    st = mailsource.status(ROOT, cfg)
    if sub == "status":
        m = st["config"]
        print(f"Gmail newsletters: {'on' if m['enabled'] else 'off'} (config email_sources.enabled) · account {m['account']} · "
              f"label {m['label']} · app password {'set' if st['password_set'] else 'NOT set in .env'}")
        for n in st["newsletters"]:
            print(f"  {n['tier']:14} {n['name']:36} {n['count']:3} archived · latest {n['latest'] or 'never'}")
        if st.get("confirms"):
            print("Subscription confirmations waiting under the label (click them in Gmail):")
            for a, u in st["confirms"].items():
                print(f"  {a}  {u.get('date', '')}  {u.get('subject', '')[:60]}")
        if st["unlisted"]:
            print("Senders under the label that are not in newsletters.yaml (add them or unsubscribe):")
            for a, u in st["unlisted"].items():
                print(f"  {a}  ({u.get('name', '')}) · {u.get('date', '')} · {u.get('subject', '')[:60]}")
        return 0
    if sub == "test":
        try:
            box = mailsource.connect(cfg)
            typ, data = box.select(st["config"]["label"], readonly=True)
            n = data[0].decode() if typ == "OK" and data and data[0] else "?"
            box.logout()
            print(f"Login OK; label {st['config']['label']} has {n} message(s)" if typ == "OK"
                  else f"Login OK but the label {st['config']['label']!r} does not exist yet")
            return 0 if typ == "OK" else 1
        except mailsource.MailError as e:
            print(f"Newsletters: {e}")
            return 1
    if sub == "fetch":
        import logging
        days = int(argv[1]) if len(argv) > 1 else None
        archive = Archive(ROOT, cfg["paths"])
        log = logging.getLogger("newsletters")
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        try:
            res = mailsource.fetch(ROOT, cfg, "manual", log, lookback_days=days)
        except mailsource.MailError as e:
            print(f"Newsletters: {e}")
            return 1
        added = archive.add_items(res["items"], dt.date.today().isoformat())
        print(f"{len(res['items'])} email(s) read, {added} new item(s) archived, {len(res['unlisted'])} unlisted sender(s). "
              "They are analyzed in the next run (or now: ./np analyze).")
        if cfg.get("archive", {}).get("git_commit", True):
            print("git:", archive.git_commit(f"archive: {added} newsletter item(s) from Gmail"))
        return 0
    print(cmd_newsletters.__doc__)
    return 2


def cmd_email(cfg: dict, argv: list) -> int:
    """./np email status | key [new] | url URL | list | add EMAIL [--confirmed] | remove EMAIL | test [EMAIL] [DAY] | send [DAY] [--force] | catchup [DAY]"""
    from pipeline import mailer
    sub, rest = (argv[0] if argv else "status"), argv[1:]
    latest = max((f.stem for f in (ROOT / cfg["paths"]["briefings"]).glob("????-??-??.md")), default="")
    try:
        if sub == "status":
            miss = mailer.ready(cfg)
            print("Email: " + ("ready" if not miss else f"not set up: {miss}") +
                  f" · daily send {'on' if mailer.ecfg(cfg)['enabled'] else 'off'} (config email.enabled)")
            if not miss:
                d = mailer.subscribers(cfg)
                act = [x for x in d["subscribers"] if x["status"] == "active"]
                print(f"{len(act)} active, {len(d['subscribers']) - len(act)} pending/unsubscribed · quota left today {d.get('quota')}")
            return 0
        if sub == "key":                      # create (once) the shared secret in .env and copy it to the clipboard
            import secrets
            import shutil
            import subprocess
            envf = ROOT / ".env"
            text = envf.read_text("utf-8") if envf.exists() else ""
            m = re.search(r"(?m)^EMAIL_SCRIPT_KEY=(\S+)", text)
            rotate = "new" in rest or "--new" in rest   # word form: argparse eats "--new" as an abbreviation of --newsletters
            if m and rotate:                       # rotate: replace the old key
                text = re.sub(r"(?m)^EMAIL_SCRIPT_KEY=\S+\n?", "", text)
                m = None
            k = m.group(1) if m else secrets.token_urlsafe(32)
            if not m:
                envf.write_text(text + ("" if not text or text.endswith("\n") else "\n") + f"EMAIL_SCRIPT_KEY={k}\n", "utf-8")
                envf.chmod(0o600)
                from pipeline import vault
                if vault.where("EMAIL_SCRIPT_KEY") == "Keychain" or rotate:   # keep the Keychain copy in step
                    vault.set_keychain("EMAIL_SCRIPT_KEY", k)
            if shutil.which("pbcopy"):
                subprocess.run(["pbcopy"], input=k, text=True)
                print(("Existing" if m else "New") + " key saved in .env and copied to the clipboard "
                      "(paste it as the SECRET script property). It is not printed here on purpose.")
            else:
                print("Key saved in .env as EMAIL_SCRIPT_KEY (copy it from there).")
            return 0
        if sub == "url" and rest:
            from pipeline import settings
            u = rest[0].strip()
            if not re.match(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec$", u):
                print("That isn't an Apps Script Web app URL (https://script.google.com/macros/s/.../exec)")
                return 2
            settings.set_value(ROOT / "config.yaml", "email", "script_url", u)
            print("Saved email.script_url in config.yaml")
            if cfg.get("archive", {}).get("git_commit", True):
                Archive(ROOT, cfg["paths"]).git_commit("email: script_url set", paths=("config.yaml",))
            return 0
        if sub == "list":
            for x in mailer.subscribers(cfg)["subscribers"]:
                print(f"  {x['status']:13} {x['email']:40} {str(x.get('source', '')):10} {str(x.get('created', ''))[:10]}")
            return 0
        if sub == "add" and rest:
            note = "added from the terminal; consent confirmed by Steven" if "--confirmed" in rest else ""
            print(mailer.add(cfg, rest[0], note, source="terminal"))
            return 0
        if sub == "remove" and rest:
            print(mailer.remove(cfg, rest[0]))
            return 0
        if sub == "test":
            to = next((x for x in rest if "@" in x), "") or (cfg.get("email") or {}).get("test_to") or _owner()["account"]
            day = next((x for x in rest if "@" not in x), "") or latest
            print(mailer.send_day(ROOT, cfg, day, to=to))
            return 0
        if sub == "catchup":                         # only people who confirmed after DAY went out
            day = next((x for x in rest if not x.startswith("-")), "") or latest
            print(mailer.send_new(ROOT, cfg, day))
            if cfg.get("archive", {}).get("git_commit", True):
                Archive(ROOT, cfg["paths"]).git_commit(f"email: {day} catch-up", paths=("data/email-log.jsonl",))
            return 0
        if sub == "send":
            day = next((x for x in rest if not x.startswith("--")), "") or latest
            print(mailer.send_day(ROOT, cfg, day, force="--force" in rest))
            if cfg.get("archive", {}).get("git_commit", True):
                Archive(ROOT, cfg["paths"]).git_commit(f"email: {day} sent", paths=("data/email-log.jsonl",))
            return 0
    except mailer.MailError as e:
        print(f"Email: {e}")
        return 1
    print(cmd_email.__doc__)
    return 2


def cmd_rebuild_history(cfg: dict, start: str = "", end: str = "") -> int:
    """Rebuild every day's briefing + audio with the current profile, oldest first (threads chain forward).
    Every earlier version stays in briefings/versions/."""
    bdir = ROOT / cfg["paths"]["briefings"]
    days = sorted(f.stem for f in bdir.glob("????-??-??.md"))
    days = [d for d in days if (not start or d >= start) and (not end or d <= end)]
    prof = (cfg.get("tuning_profile") or {}).get("name", "")
    print(f"Rebuilding {len(days)} day(s) with profile {prof}: {', '.join(days)}")
    results = []
    for d in days:
        print(f"\n===== {d} =====")
        results.append((d, cmd_run(cfg, rebrief_day=d)))
    print("\n" + "\n".join(f"  {d}: {'ok' if c == 0 else 'FAILED'}" for d, c in results))
    if cfg.get("publish", {}).get("auto") and any(c == 0 for _, c in results):
        cmd_publish(cfg)
    return 0 if all(c == 0 for _, c in results) else 1


def cmd_record(cfg: dict, argv: list) -> int:
    """./np record list | search | words | apply-words | accept ID | deny ID [NOTE] | export"""
    from pipeline import record
    sub, rest = (argv[0] if argv else "list"), argv[1:]
    msg = ""
    if sub == "list":
        q = record.load_queue(ROOT)
        for st in record.STATUSES:
            rows = [c for c in q if c["status"] == st]
            print(f"\n{st.upper()} ({len(rows)})")
            for c in rows:
                print(f"  {c['id']}  {c.get('date', ''):10} {c['type']:13} {c['title'][:70]}\n             {c['url']}")
        print(f"\nMentions logged: {len(record.recent_mentions(ROOT, 100000))}")
        return 0
    if sub == "search":
        print("Searching the web for new appearances and mentions (Claude, ~3-8 min)...")
        rows = record.search(ROOT, cfg)
        msg = f"record: web search, {len(rows)} new candidate(s)"
    elif sub == "words":
        print("Reading the archive's sources and extracting your stated views (~3-8 min)...")
        rec = record.own_words(ROOT, cfg)
        msg = f"record: own words, {rec['views']} views from {rec['with_text']}/{rec['sources']} sources"
    elif sub == "apply-words":
        if not record.apply_own_words(ROOT):
            print("Nothing to apply: run ./np record words first")
            return 1
        msg = "lens: 'In my own words' added to author.md"
    elif sub in ("accept", "deny") and rest:
        c = record.decide(ROOT, rest[0], "accepted" if sub == "accept" else "denied", " ".join(rest[1:]))
        print(f"{c['status']}: {c['title']}")
        msg = f"record: {c['status']} {c['title'][:60]}"
    elif sub == "export":
        print(f"Wrote {record.export(ROOT).relative_to(ROOT)}")
        msg = "record: export manifest candidates"
    else:
        print(cmd_record.__doc__)
        return 2
    if cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(msg, paths=("data/public-record", "author.md")))
    return 0


def cmd_dive(cfg: dict, day: str, key: str) -> int:
    """./np dive DAY STORY: deep dive on one story (STORY = key from data/stories, or its number in the briefing)."""
    from pipeline import dive, editorial
    if key.isdigit():
        rows = stages.read_jsonl(ROOT / "data" / "stories" / f"{day}.jsonl")
        match = [s for s in (rows[-1]["stories"] if rows else []) if s.get("n") == int(key)]
        if not match:
            print(f"No story number {key} in the {day} briefing")
            return 2
        key = match[0]["key"]
    try:
        rec = dive.run(ROOT, cfg, day, key)
    except (KeyError, llm.LLMError) as e:
        print(f"Dive failed: {e}")
        return 1
    if cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"dive: {day} {rec['headline'][:60]}",
                                                         paths=("briefings/dives", "data/dives.jsonl")))
    print(f"Read it: http://127.0.0.1:{cfg.get('dashboard', {}).get('port', 8765)}/dives/{day}/{key}")
    return 0


def save_briefing(run, cfg, day, md, order, entries, models, prompt_versions, briefings_log, extra=None) -> dict:
    paths = cfg["paths"]
    ids = [e.get("id") for e in entries if e.get("id")]
    md, unq = stages.verify_quotes(md, stages.source_texts(ROOT, ids) + [str(e.get("title", "")) for e in entries])
    if unq:
        run.log.warning("briefing: %d quotation(s) not found word for word in the sources, quote marks removed: %s",
                        len(unq), "; ".join(q[:50] for q in unq[:5]))
    from pipeline.editorial import money_style
    md = money_style(md)
    names = stages.private_names()
    allow = stages.allowed_names(names, [e.get("person", "") for e in entries] + [e.get("author", "") for e in entries])
    md, hits = stages.scrub_private(md, names, allow)
    if hits:
        run.log.warning("briefing: removed %d private name(s) from the text: %s", len(hits), ", ".join(sorted(set(hits))))
    from pipeline.links import scrub_output
    md, gone = scrub_output(md, cfg)
    if gone:
        run.log.warning("briefing: removed %d personal link(s)/address(es) (trackers, account pages)", len(gone))
    bdir = ROOT / paths["briefings"]
    (bdir / "versions").mkdir(parents=True, exist_ok=True)
    version_file = bdir / "versions" / f"{day}-{run.run_id}.md"
    version_file.write_text(md, "utf-8")
    (bdir / f"{day}.md").write_text(md, "utf-8")
    stages.append_jsonl(briefings_log, [{
        "day": day, "run_id": run.run_id, "file": f"{paths['briefings']}/{day}.md",
        "version_file": str(version_file.relative_to(ROOT)), "item_ids": order,
        "considered_ids": [r["id"] for r in entries], "models": models,
        "prompt_versions": prompt_versions, "quotes_removed": len(unq), "private_removed": len(hits),
        "personal_links_removed": len(gone), **(extra or {})}])
    return {"items": len(order), "file": f"{paths['briefings']}/{day}.md",
            "version_file": str(version_file.relative_to(ROOT)), "words": len(md.split())}


def write_v2(run, cfg, backends, system, entries, day, dropped, meta, briefings_log, experiment=None) -> None:
    """cluster → select → merge (local) → editorial (Claude) → threads → render.
    experiment=<profile>: write to briefings/experiments/<day>/<profile>.md instead of the real briefing."""
    from pipeline import editorial
    acfg = cfg.get("analysis", {})
    stories_dir = ROOT / "data" / "stories"
    threads_on = acfg.get("threads", True)
    earlier = editorial.earlier_stories(stories_dir, day, int(acfg.get("thread_days", 7))) if threads_on else []
    raw = stages.raw_items(ROOT, [r["id"] for r in entries])
    for r in entries:                       # what the citation needs from the fetched item (the article behind a post)
        it = raw.get(r["id"]) or {}
        for k in ("linked_url", "source_kind", "public_url"):
            if it.get(k) and not r.get(k):
                r[k] = it[k]
    try:
        from pipeline import links
        n_fixed = links.enrich(ROOT, entries, cfg, run.log)
        if n_fixed:
            run.log.info("  links: %d citation(s) now point at the article", n_fixed)
    except Exception as e:  # noqa: BLE001 - a link lookup never stops the briefing
        run.log.warning("links: %s", e)
    by_id = {r["id"]: r for r in entries}
    with run.stage("cluster") as st:
        raw, cv, errs = editorial.run_cluster(backends["cluster"], entries, system, acfg, run.log)
        stories = editorial.build_stories(raw, by_id)
        sel = editorial.select(stories, acfg)
        mv, merrs = editorial.run_merge(backends["merge"], sel["must"] + sel["worth"], system, run.log)
        errs += merrs
        st.update({"records": len(entries), "stories": len(stories),
                   "multi_source": sum(1 for s in stories if len(s["ids"]) > 1),
                   "must": len(sel["must"]), "worth": len(sel["worth"]), "brief": len(sel["brief"]),
                   "more": sel["more"], "model": f'{backends["cluster"].label} + merge {backends["merge"].label}',
                   "errors": errs[:10]})
        if errs:
            st["status"] = "partial"
    with run.stage("verify") as st:              # every Must read gets an evidence check (fact review 2026-10-18)
        need = [s["lead"] for s in sel["must"] if not (s["lead"].get("critique_detail") or {}).get("verdict")]
        st.update({"needed": len(need), "checked": 0})
        if need:
            from pipeline import reader
            raw_need = stages.raw_items(ROOT, [r["id"] for r in need])
            targets = [dict(raw_need[r["id"]]) for r in need if r["id"] in raw_need]
            try:
                st["reader"] = reader.read_thin(ROOT, targets, cfg, run.log)
            except Exception as e:  # noqa: BLE001
                run.log.warning("verify: reader skipped: %s", e)
            summ = {r["id"]: {k: r.get(k, "") for k in ("claim", "so_what", "agenda_flag")} for r in need}
            crit, _v, verrs = stages.run_critique(backends["critique"], targets, summ, system, acfg, run.log)
            for r in need:
                if r["id"] in crit:
                    r["critique_detail"] = crit[r["id"]]
                    r["critique"] = stages.critique_text(crit[r["id"]])
            st.update({"checked": len(crit), "errors": verrs[:5],
                       "verdicts": {x: sum(1 for c in crit.values() if c["verdict"] == x) for x in stages.VERDICTS}})
            if verrs:
                st["status"] = "partial"
    with run.stage("editorial") as st:
        ed, ev, eerrs = editorial.run_editorial(backends["editorial"], sel, system, run.log, cfg, earlier)
        if threads_on:
            editorial.mark_threads(sel, stories_dir, day)
        st.update({"top_of_mind": len(ed.get("top_of_mind", [])), "open_questions": len(ed.get("open_questions", [])),
                   "developing": sum(1 for s in sel["must"] + sel["worth"] if s.get("thread_day", 1) > 1),
                   "editor_views":
                   sum(1 for s in sel["must"] + sel["worth"] if s.get("editor_view")),
                   "day_in_brief": bool(ed.get("day_in_brief")), "model": backends["editorial"].label,
                   "errors": eerrs})
        if eerrs:
            st["status"] = "partial"
    with run.stage("write") as st:
        models = sorted({b.label for b in backends.values()})
        n_sources = len({stages.display_name(r) for r in entries})
        md, order, trimmed = editorial.fit(day, sel, ed, {
            "models": ", ".join(models), "n_items": len(entries), "n_sources": n_sources, "dropped": dropped,
            "generated": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")},
            int(acfg.get("max_words", 1500)))
        if trimmed:
            run.log.info("  write: %d lower item(s) left out to stay within %s words", trimmed, acfg.get("max_words", 1500))
        srec = editorial.story_records(sel, run.run_id, day)
        srec["editorial"] = ed
        from pipeline import profiles
        evs = [s.get("evidence") or profiles.evidence(s["records"]) for s in sel["must"] + sel["worth"]]
        musts = [s.get("evidence") or profiles.evidence(s["records"]) for s in sel["must"]]
        stance_mix = {}
        for e in evs:
            for k, v in e["stances"].items():
                stance_mix[k] = stance_mix.get(k, 0) + len(v)
        balance = {"must_grounded": sum(1 for e in musts if e["grounded"]), "must": len(musts),
                   "reports": sum(e["reports"] for e in evs), "primary": sum(e["primary"] for e in evs),
                   "commentary": sum(e["commentary"] for e in evs), "stances": stance_mix}
        st["balance"] = balance
        pv = {**meta["prompt_versions"], "cluster": cv, "merge": mv, "editorial": ev}
        tp = cfg.get("tuning_profile") or {}
        try:                                     # every figure traced to the sources it cites (fact review 2026-10-18)
            from pipeline import factcheck
            ids = [i for s_ in srec.get("stories", []) for i in s_.get("ids", [])]
            finder = factcheck_finder(cfg, ids, run.log)
            md, fc = factcheck.check(md, factcheck.corpus(ROOT, ids), find=finder)
            st["factcheck"] = {"checked": fc["checked"], "cut": fc["cut"][:20], "flagged": fc["flagged"][:20],
                               "sourced": fc["sourced"][:20], "searches": getattr(finder, "requests", 0)}
            for c in fc["sourced"]:
                run.log.info("fact check: found %s via %s (%s)", c["figure"], c["how"], c["url"])
            for c in fc["cut"]:
                run.log.warning("fact check: cut %s", c)
            for c in fc["flagged"]:
                run.log.info("fact check: flagged %s", c)
        except Exception as e:  # noqa: BLE001
            run.log.warning("fact check skipped: %s", e)
        try:                                     # a stated difference that doesn't add up is corrected before saving
            from pipeline import numbers
            md, st["number_fixes"] = numbers.fix(md)
            for f_ in st["number_fixes"]:
                run.log.info("number check: corrected %s", f_)
        except Exception as e:  # noqa: BLE001
            run.log.warning("number fix skipped: %s", e)
        try:                                     # the lines readers see first agree with the checked body (v0.1.14)
            from pipeline import consistency, factcheck
            ids = [i for s_ in srec.get("stories", []) for i in s_.get("ids", [])]
            md, hn = consistency.check_briefing(md, " ".join(factcheck.corpus(ROOT, ids)))
            earlier = {}
            for k in range(1, 15):
                f_ = ROOT / cfg["paths"]["briefings"] / f"{(dt.date.fromisoformat(day) - dt.timedelta(days=k)).isoformat()}.md"
                if f_.exists():
                    earlier[f_.stem] = f_.read_text("utf-8")
            xd = consistency.cross_day(md, earlier)
            st["consistency"] = {"dropped": hn[:20], "cross_day": xd[:10]}
            for n_ in hn:
                run.log.warning("consistency: %s", n_)
            for x_ in xd:
                run.log.info("consistency: review: says %s wasn't disclosed, but %s gave it: %s", x_["term"],
                             x_["earlier_day"], x_["earlier"][:120])
        except Exception as e:  # noqa: BLE001
            run.log.warning("consistency check skipped: %s", e)
        if experiment:
            out = experiment_dir(cfg, day)
            out.mkdir(parents=True, exist_ok=True)
            f = out / f"{experiment}.md"
            f.write_text(stages.scrub_private(md)[0], "utf-8")
            stages.append_jsonl(ROOT / "data" / "experiments.jsonl", [{
                "day": day, "profile": experiment, "fingerprint": tp.get("fingerprint", ""), "run_id": run.run_id,
                "file": str(f.relative_to(ROOT)), "created": dt.datetime.now().isoformat(timespec="seconds"),
                "models": models, "prompt_versions": pv, "words": len(md.split()), "stories": srec}])
            st.update({"items": len(order), "file": str(f.relative_to(ROOT)), "words": len(md.split()),
                       "experiment": experiment})
        else:
            stages.append_jsonl(stories_dir / f"{day}.jsonl", [srec])
            st.update(save_briefing(run, cfg, day, md, order, entries, models, pv, briefings_log,
                                    {"format": "v2", "stories_file": f"data/stories/{day}.jsonl", "balance": balance,
                                     "profile": tp.get("name", ""), "profile_fingerprint": tp.get("fingerprint", "")}))
        st["topline_bullets"] = len(ed.get("top_of_mind", []))
        st["model"] = "code"
        try:                                     # stated arithmetic and figures given two ways (pipeline/numbers.py)
            from pipeline import numbers
            st["number_issues"] = numbers.check(md)
            for i in st["number_issues"]:
                run.log.warning("number check: %s", i)
        except Exception as e:  # noqa: BLE001
            run.log.warning("number check skipped: %s", e)


def _align_with_deepdive(run, cfg: dict, day: str) -> None:
    """The briefing agrees with the day's deep dive and doesn't tell its story twice (consistency.align_deepdive),
    before the briefing audio is made. Never fails the edition."""
    import json as _json
    try:
        from pipeline import consistency, deepdive
        rec = deepdive.latest(ROOT, day) or {}
        if rec.get("status") not in ("written", "published"):
            return
        pf = ROOT / deepdive.DIR / f"{day}.parts.json"
        if not pf.exists():
            return
        parts = _json.loads(pf.read_text("utf-8")).get("parts", [])
        body = " ".join(str(t_) for n_, t_ in parts if n_ not in ("Opener", "Outro"))
        head = " ".join(str(x) for x in ((rec.get("pick") or {}).get("why_today", ""), rec.get("title", "")))
        bfile = ROOT / cfg["paths"]["briefings"] / f"{day}.md"
        md = bfile.read_text("utf-8")
        md2, notes, flags = consistency.align_deepdive(md, rec.get("title") or "", body, head)
        for n_ in notes:
            run.log.warning("deep-dive alignment: %s", n_)
        for f_ in flags:
            run.log.info("deep-dive alignment: review: %s", f_)
        if md2 != md:
            bfile.write_text(md2, "utf-8")
            (ROOT / cfg["paths"]["briefings"] / "versions" / f"{day}-{run.run_id}-aligned.md").write_text(md2, "utf-8")
        run.record["stages"].setdefault("write", {})["deepdive_alignment"] = {"changes": notes[:10], "review": flags[:10]}
    except Exception as e:  # noqa: BLE001
        run.log.warning("deep-dive alignment skipped: %s", e)


def make_audio(run, cfg: dict, day: str, experiment=None) -> None:
    """Stage 'audio': spoken script (LLM) + TTS + delivery. Never fails the briefing.
    experiment=<profile>: read and write briefings/experiments/<day>/<profile>.*, no delivery."""
    from pipeline import audio
    acfg = cfg.get("audio", {})
    if not acfg.get("enabled", True):
        run.skip("audio", "audio.enabled is false")
        return
    bdir = experiment_dir(cfg, day) if experiment else ROOT / cfg["paths"]["briefings"]
    stem = experiment or day
    md_file = bdir / f"{stem}.md"
    if not md_file.exists():
        run.skip("audio", "no briefing")
        return
    try:
        with run.stage("audio") as st:
            eng = audio.engine_from(cfg)
            eng.check()
            backend = llm.for_stage(cfg, "script")
            backend.check()
            persp = perspective.load(ROOT / cfg["paths"]["perspective"])
            system, _ = stages.system_prompt(persp.raw)
            md = md_file.read_text("utf-8")
            if not experiment:
                try:
                    from pipeline import deepdive
                    dd = deepdive.latest(ROOT, day)          # hand off only to a deep dive that is ready
                    if dd and dd.get("status") in ("written", "published"):
                        cfg = {**cfg, "audio": {**acfg, "_handoff": dd.get("title") or (dd.get("pick") or {}).get("topic", "")}}
                except Exception:  # noqa: BLE001
                    pass
            parts, sv, errs = audio.build_script(backend, md, system, cfg, run.log)
            if not parts:
                raise RuntimeError("no script sections produced")
            scrubbed = []
            pnames = stages.private_names()
            pallow = [n for n in pnames if n in md]            # names the briefing kept are published sources
            for i, (name, text) in enumerate(parts):
                text2, hits = stages.scrub_private(text, pnames, pallow)
                if hits:
                    scrubbed += hits
                    parts[i] = (name, text2)
            if scrubbed:
                run.log.warning("script: removed private name(s): %s", ", ".join(sorted(set(scrubbed))))
            if acfg.get("cold_open", True) and not experiment:
                cold = audio.cold_open(md)
                if cold:
                    parts.insert(0, ("Cold open", cold))
            title = audio.parse_briefing(md)["title"]
            voice = f"{eng.name}:{getattr(eng, 'voice', '')}"
            script = audio.script_markdown(title, parts, {"script_model": backend.label, "voice": voice})
            (bdir / f"{stem}.script.md").write_text(script, "utf-8")
            from pipeline import speech
            table = speech.load_table(ROOT)
            said = [(name, speech.spoken(text, table)) for name, text in parts]
            odd = speech.lint(" ".join(t_ for _, t_ in said), table)
            if odd:
                run.log.info("pronunciation: check these in pronunciations.yaml: %s", ", ".join(odd))
            (bdir / f"{stem}.spoken.txt").write_text("\n\n".join(f"[{n}]\n{t}" for n, t in said) + "\n", "utf-8")
            mp3 = bdir / f"{stem}.mp3"
            minutes = audio.render_mp3(eng, said, mp3, title, acfg.get("bitrate", "64k"))
            if not experiment:
                from pipeline import episodes as eps
                v = eps.rebuilt(ROOT, day)
                if v > 1:
                    run.log.info("  audio: %s was already published; this is episode version %d (new GUID)", day, v)
            delivered = "experiment: not delivered" if experiment else audio.deliver(cfg, mp3, run.log)
            st.update({"minutes": round(minutes, 1), "words": sum(len(t.split()) for _, t in parts),
                       "voice": voice, "model": backend.label, "script_prompt": sv,
                       "mp3": str(mp3.relative_to(ROOT)), "delivered": delivered, "errors": errs[:10]})
            if errs or delivered.startswith("folder missing"):
                st["status"] = "partial"
    except Exception as e:  # noqa: BLE001 - the text briefing still stands
        run.log.warning("audio failed: %s", e)


def cmd_audio(cfg: dict, day: str = None) -> int:
    """(Re)build only the audio for a day: ./np audio [DAY]."""
    archive = Archive(ROOT, cfg["paths"])
    run = Run(archive, ROOT / cfg["paths"]["logs"], cfg)
    day = day or max((f.stem for f in (ROOT / cfg["paths"]["briefings"]).glob("????-??-??.md")), default=None)
    for s in ("fetch", "filter", "rank", "critique", "cluster", "editorial", "write"):
        run.skip(s, "audio only")
    make_audio(run, cfg, day)
    st = run.record["stages"].get("audio", {})
    status = "ok" if st.get("status") == "ok" else ("partial" if st.get("status") == "partial" else "error")
    run.finish(status)
    if cfg.get("archive", {}).get("git_commit", True):
        archive.git_commit(f"audio: {day} ({status})")
    print(f"Audio {day}: {st.get('status')} {st.get('minutes', '')} min, {st.get('delivered', st.get('error', ''))}")
    return 0 if status != "error" else 1




def cmd_hub(cfg: dict, argv: list) -> int:
    """./np hub status | push: AI Briefing's status on the public project hub (pipeline/hub.py)."""
    from pipeline import hub
    sub = (argv or ["status"])[0]
    try:
        if sub == "push":
            print(hub.push(ROOT, cfg))
            return 0
        b = hub.build(ROOT, cfg)
        print(b["files"][hub.ALLOW[0]], end="")
        print(f"(page {hub.ALLOW[1]}: {len(b['files'][hub.ALLOW[1]])} bytes; nothing pushed. To push: ./np hub push)")
        return 0
    except hub.HubExportError as e:
        print(f"Hub export refused: {e}")
        return 1


def cmd_dev(cfg: dict, argv: list) -> int:
    """./np dev setup: create the development checkout (pipeline/devenv.py). Run from production."""
    from pipeline import devenv
    try:
        if (argv or ["setup"])[0] == "setup":
            print(devenv.setup(ROOT, cfg))
            return 0
        print(cmd_dev.__doc__)
        return 2
    except devenv.DevError as e:
        print(f"Dev: {e}")
        return 1


def cmd_staging(cfg: dict, argv: list) -> int:
    """./np staging sync | run [DAY] [--email] [--force] | compare [DAY] | publish [setup] | reset | status (dev checkout)."""
    from pipeline import devenv, env
    sub, rest = (argv or ["status"])[0], (argv or [])[1:]
    try:
        if sub == "status":
            print(f"{'STAGING (dev checkout)' if env.staging(ROOT) else 'PRODUCTION'} · {ROOT}")
            return 0
        if sub == "sync":
            print(devenv.sync(ROOT, cfg))
            return 0
        if sub == "reset":
            print(devenv.reset(ROOT))
            return 0
        if sub == "publish":                     # the development preview: sgwoods.github.io/ai-briefing-staging/
            devenv._need_staging(ROOT)
            from pipeline import publish, site
            srepo = (cfg.get("publish") or {}).get("staging_repo") or "sgwoods/ai-briefing-staging"
            if "setup" in rest:
                print(publish.setup(ROOT, srepo))
                print("Then turn on Pages: GitHub repo Settings -> Pages -> Deploy from branch main, / (root)")
            # the preview carries the newest day's audio only: a full set of MP3s makes GitHub time out (HTTP 408)
            res = site.build(ROOT, site.staging_cfg(cfg), base_url=site.staging_site_url(cfg), audio_days=1)
            print(f"Built the preview: {res['days']} briefings, {res['audio']} MP3")
            print(publish.push(ROOT, ROOT / "site", srepo, f"Preview {dt.datetime.now():%Y-%m-%d %H:%M}", cfg,
                               staging_site=True))
            print(f"Development preview: {site.staging_site_url(cfg)}")
            return 0
        if sub == "compare":
            from pipeline import compare
            day = next((a for a in rest if not a.startswith("--")), "") or devenv.latest_day(ROOT)
            r = compare.write(ROOT, devenv.production_root(ROOT), day)
            print(r["summary"])
            print(f"Full report: {r['file']}")
            return 0 if not r["review"] else 3
        if sub == "run":
            devenv._need_staging(ROOT)
            devenv.check_window("--force" in rest)
            day = next((a for a in rest if not a.startswith("--")), "") or devenv.latest_day(ROOT)
            print(f"Staging run: rebuilding {day} with the dev code (outbound off)")
            code = cmd_run(cfg, rebrief_day=day, commit=False)
            from pipeline import site
            res = site.build(ROOT, site.staging_cfg(cfg), base_url=site.staging_site_url(cfg), audio_days=1)
            print(f"Built the development preview in site/: {res['days']} briefings. Publish it: ./np staging publish")
            if "--email" in rest:
                from pipeline import mailer
                print(mailer.send_day(ROOT, cfg, day, to=(cfg.get("email") or {}).get("test_to") or _owner()["account"],
                                      force=True))
            return code
    except devenv.DevError as e:
        print(f"Staging: {e}")
        return 1
    print(cmd_staging.__doc__)
    return 2


def cmd_release(cfg: dict, argv: list, rollback: bool = False) -> int:
    """./np release VERSION "reviewed: ..." [--force] | ./np rollback "reviewed: ...": promote dev to production,
    or return to the previous release (pipeline/releaser.py). Then the public code, backup and hub status."""
    from pipeline import releaser
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    try:
        if rollback:
            r = releaser.rollback(ROOT, cfg, " ".join(argv).strip())
            print(f"Rolled back: v{r['previous']} -> v{r['version']} (commit {r['commit']})")
        else:
            if not argv:
                print(cmd_release.__doc__)
                return 2
            r = releaser.promote(ROOT, cfg, argv[0], " ".join(argv[1:]).strip(), force=force)
            print(f"Released v{r['version']} (was v{r['previous']}, commit {r['commit']})")
            try:                                          # what the weekly docs refresh picks up
                from pipeline import docs
                rep = docs.impact(ROOT, f"v{r['previous']}", "HEAD") if r.get("previous") else None
                if rep:
                    docs.save_impact(ROOT, rep, r["version"])
                    print(docs.impact_line(rep))
            except Exception as e:  # noqa: BLE001
                print(f"docs impact skipped: {e}"[:200])
    except releaser.ReleaseError as e:
        print(f"Release: {e}")
        return 1
    from pipeline import publish
    try:
        print("backup:", publish.backup_push(ROOT, cfg))
    except Exception as e:  # noqa: BLE001
        print(f"backup push failed: {e}"[:300])
    try:
        from pipeline import hub
        print(hub.push(ROOT, cfg))
    except Exception as e:  # noqa: BLE001
        print(f"hub export skipped: {e}"[:400])
    print("Tomorrow's run is the canary. If it fails: ./np rollback \"reviewed: <why>\"")
    return 0


def cmd_correct(cfg: dict, argv: list) -> int:
    """./np correct DAY "what changed": record a hand edit to a shipped edition (briefing or deep dive) as a
    correction. The note is shown on the day page and the deep-dive page; the next publish carries it."""
    from pipeline import env, shipped
    if len(argv) < 2 or not " ".join(argv[1:]).strip():
        print(cmd_correct.__doc__)
        return 2
    day, note = argv[0], " ".join(argv[1:]).strip()
    if env.staging(ROOT):
        print("corrections are made in production")
        return 1
    if not shipped.is_shipped(ROOT, day):
        print(f"{day} hasn't shipped: edit it freely, no correction needed")
        return 1
    print("correction recorded:", shipped.correct(ROOT, day, note)["note"])
    if cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"correction {day}: {note[:60]}",
                                                            paths=("briefings", shipped.FILE, shipped.CORRECTIONS)))
    print("Publish it: ./np publish")
    return 0


def cmd_remaster(cfg: dict, day: str) -> int:
    """./np remaster DAY: rebuild DAY's podcast in the current style (deep dive re-recorded with the current opener and
    sign-off, briefing audio rebuilt with the hand-off, one combined episode), then publish. No email is re-sent."""
    from pipeline import deepdive
    dd = deepdive.latest(ROOT, day)
    if dd and dd.get("status") == "published":
        deepdive.revoice(ROOT, cfg, day)
    code = cmd_audio(cfg, day)                   # make_audio hands off to a published deep dive
    if code:
        return code
    if (deepdive.latest(ROOT, day) or {}).get("status") == "published":
        deepdive.make_podcast(ROOT, cfg, day)
    if cfg.get("archive", {}).get("git_commit", True):
        Archive(ROOT, cfg["paths"]).git_commit(f"remaster {day}", paths=(deepdive.DIR, deepdive.LOG, "data/episodes.json"))
    return cmd_publish(cfg)


def cmd_script_preview(cfg: dict, argv: list) -> int:
    """./np script-preview DAY [tts]: write DAY's audio script with the current settings to
    briefings/experiments/DAY/script-preview.{script.md,spoken.txt} (+ .mp3 with tts). Nothing real is touched:
    no delivery, no publish, no commit."""
    import logging
    from pipeline import audio, speech
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("script")
    day = argv[0] if argv else max((f.stem for f in (ROOT / cfg["paths"]["briefings"]).glob("????-??-??.md")), default="")
    md = (ROOT / cfg["paths"]["briefings"] / f"{day}.md").read_text("utf-8")
    backend = llm.for_stage(cfg, "script")
    backend.check()
    system, _ = stages.system_prompt(perspective.load(ROOT / cfg["paths"]["perspective"]).raw)
    parts, version, errs = audio.build_script(backend, md, system, cfg, log)
    pnames = stages.private_names()
    parts = [(n, stages.scrub_private(t, pnames, [x for x in pnames if x in md])[0]) for n, t in parts]
    out = experiment_dir(cfg, day)
    out.mkdir(parents=True, exist_ok=True)
    title = audio.parse_briefing(md)["title"]
    (out / "script-preview.script.md").write_text(
        audio.script_markdown(title, parts, {"script_model": backend.label, "voice": "preview"}), "utf-8")
    table = speech.load_table(ROOT)
    said = [(n, speech.spoken(t, table)) for n, t in parts]
    (out / "script-preview.spoken.txt").write_text("\n\n".join(f"[{n}]\n{t}" for n, t in said) + "\n", "utf-8")
    words = sum(len(t.split()) for _, t in parts)
    print(f"script: {len(parts)} sections, {words} words (~{words / audio.WPM:.1f} min), prompt {version}")
    for e in errs:
        print("  " + e)
    if "tts" in argv[1:]:
        eng = audio.engine_from(cfg)
        eng.check()
        mins = audio.render_mp3(eng, said, out / "script-preview.mp3", title, cfg.get("audio", {}).get("bitrate", "64k"))
        print(f"audio: {mins:.1f} min -> {(out / 'script-preview.mp3').relative_to(ROOT)}")
    print(f"written to {out.relative_to(ROOT)}/script-preview.*")
    return 0 if not errs else 1


def cmd_release_check(cfg: dict, argv: list) -> int:
    """./np release-check [live] | approve "what you reviewed" | install-hooks"""
    from pipeline import release
    argv = [a.lstrip("-") if a in ("--live", "--approve", "--install-hooks") else a for a in argv]
    if "install-hooks" in argv:
        print("git hooks installed: " + ", ".join(release.install_hooks(ROOT)))
        return 0
    if "require" in argv:                        # the pre-push hook: fast when this code already passed
        try:
            release.require(ROOT, cfg, "git push")
            return 0
        except release.ReleaseBlocked as e:
            print(e)
            return 1
    if "approve" in argv:
        i = argv.index("approve")
        note = " ".join(argv[i + 1:]).strip()
        try:
            rec = release.approve(ROOT, cfg, note)
        except release.ReleaseBlocked as e:
            print(e)
            return 1
        if cfg.get("archive", {}).get("git_commit", True):
            print("git:", Archive(ROOT, cfg["paths"]).git_commit("security: release approval", paths=(release.APPROVALS,)))
        if rec["passed"]:                        # a morning held back by the gate goes out as soon as it's approved
            from pipeline.archive import read_jsonl
            today = dt.date.today().isoformat()
            built = any(r.get("day") == today and not r.get("experiment")
                        and (r.get("stages", {}).get("write") or {}).get("status") == "ok"
                        for r in read_jsonl(ROOT / cfg["paths"]["runs"]))
            if built:
                print("Today's edition is built; sending anything the gate held back...")
                _retry_outbound(cfg, today)
        return 0 if rec["passed"] else 1
    rec = release.run(ROOT, cfg, live="live" in argv)
    return 0 if rec["passed"] else 1


def _runner_verify(cfg: dict) -> int:
    """After a run-queue job: what's running, tagged and guarded now (read only)."""
    import json as _json
    import subprocess as _sp
    from pipeline import release, releaser
    from pipeline.version import full
    env = releaser._clean_env()
    tag = _sp.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT, capture_output=True, text=True, env=env).stdout.strip()
    print(f"VERSION v{full(ROOT)} · latest tag {tag or '-'}" + ("" if tag == f"v{full(ROOT)}" else "  (VERSION and tag differ)"))
    hook = ROOT / ".git" / "hooks" / "pre-push"
    hook_ok = hook.exists() and "release-check require" in hook.read_text("utf-8", errors="replace")
    print(f"pre-push hook: {'fast gate (release-check require)' if hook_ok else 'OLD or missing: ./np release-check install-hooks'}")
    fp, sfp = release.fingerprint(release.CODE, ROOT), release.fingerprint(release.SENSITIVE, ROOT)
    ok, detail = release.check_approval(ROOT)
    print(f"gate: code {fp} {'passed before' if release.passed_before(ROOT, fp, sfp) else 'not yet passed'} · {detail}")
    dirty = _sp.run(["git", "status", "--porcelain", "--", *releaser.CODE_PATHS], cwd=ROOT, capture_output=True,
                    text=True, env=env).stdout.strip()
    print("production code: " + ("clean (matches the release)" if not dirty else "CHANGED outside a release:\n" + dirty[:400]))
    try:
        from pipeline import shipped
        led = _json.loads((ROOT / shipped.FILE).read_text("utf-8"))
        days = sorted(led.get("days", led) if isinstance(led, dict) else [])
        if days:
            print(f"shipped editions: {len(days)} (latest {days[-1]})")
    except (OSError, ValueError, TypeError):
        pass
    return 0 if hook_ok and ok and not dirty else 1


def _runner_summary(cfg: dict, job: dict) -> str:
    """What the approval dialog shows: the commits and files a release brings, or the note."""
    import subprocess as _sp
    from pipeline import releaser
    env = releaser._clean_env()
    lines = []
    if job["recipe"] in ("ship", "release"):
        g = lambda *a: _sp.run(["git", *a], cwd=ROOT, capture_output=True, text=True, env=env).stdout.strip()  # noqa: E731
        n = len([x for x in g("log", "--oneline", "HEAD..dev").splitlines() if x])
        lines.append(f"{n} commit(s) from dev · {g('diff', '--shortstat', 'HEAD', 'dev') or 'no file changes'}")
        try:
            from pipeline import docs
            lines.append(docs.impact_line(docs.impact(ROOT, "HEAD", "dev")))
        except Exception:  # noqa: BLE001
            pass
        ch = g("show", "dev:CHANGELOG.md")
        v = job["args"].get("version", "")
        if f"## v{v}" in ch:
            sec = ch.split(f"## v{v}", 1)[1].split("\n## ", 1)[0].strip().splitlines()[1:6]
            lines += [x[:160] for x in sec]
    if job["args"].get("note"):
        lines.append("Note: " + job["args"]["note"])
    if job.get("chat_approval"):
        lines.append("In chat: " + job["chat_approval"][:200])
    return "\n".join(lines)


def cmd_runner(cfg: dict, argv: list) -> int:
    """./np runner status | tick | approve ID | reject ID | install | remove: the run queue (pipeline/runner.py).
    Claude queues jobs (data/queue/pending/); this Mac runs them; mac-tier jobs wait for Approve in a dialog."""
    import json as _json
    from pipeline import devenv, runner, service
    from pipeline.releaser import run_in_progress
    sub, rest = (argv or ["status"])[0], (argv or [])[1:]
    local = {"verify": lambda a: _runner_verify(cfg),
             "release": lambda a: cmd_release(cfg, a),
             "rollback": lambda a: cmd_release(cfg, a, rollback=True),
             "approve": lambda a: cmd_release_check(cfg, ["approve", *a]),
             "install-hooks": lambda a: cmd_release_check(cfg, ["install-hooks"])}
    r = runner.Runner(ROOT, devenv.dev_path(ROOT, cfg), local, busy=lambda: run_in_progress(ROOT),
                      summary=lambda job: _runner_summary(cfg, job))
    if sub == "tick":
        for line in r.tick():
            print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {line}")
        return 0
    if sub == "install":
        print(service.install("runner", ROOT, cfg))
        return 0
    if sub == "remove":
        print(service.remove("runner"))
        return 0
    if sub in ("approve", "reject") and rest:
        from pipeline.presence import confirmed
        p = runner.qdir(ROOT, "waiting") / f"{rest[0]}.json"
        if not p.exists():
            print(f"no waiting job {rest[0]}: ./np runner status")
            return 1
        if sub == "reject":
            job = _json.loads(p.read_text("utf-8"))
            runner._finish(ROOT, p, job, "rejected", "rejected in Terminal")
            print(f"{rest[0]}: rejected")
            return 0
        import sys as _sys
        if not (_sys.stdin is not None and _sys.stdin.isatty() and confirmed()):
            print("approve needs you at a terminal (or click Approve in the dialog)")
            return 1
        print(f"{rest[0]}: {r.run_job(p, terminal=True)}")
        return 0
    s = runner.qdir(ROOT, "pending").parent / "status.json"
    runner._status(ROOT)
    st = _json.loads(s.read_text("utf-8"))
    print(f"service: {'loaded' if service.loaded('runner') else 'not installed: ./np runner install'}")
    print(f"pending: {', '.join(st['pending']) or '-'}")
    print(f"waiting for Approve: {', '.join(st['waiting']) or '-'}")
    for j in st["last"]:
        print(f"  {j['ended']}  {j['id']}  {j['status']}  {j.get('detail') or ''}")
    return 0


def cmd_consistency(cfg: dict, argv: list) -> int:
    """./np consistency [DAY|all]: dry run of the first-lines checks (day in brief, Top of mind, Agenda roles,
    deep-dive summaries) and the cross-day check over published editions. Nothing is edited."""
    from pipeline import consistency
    days = None if not argv or argv[0] == "all" else [a for a in argv if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)]
    r = consistency.audit(ROOT, days)
    n = 0
    for d in r["days"]:
        for h in d["header"]:
            print(f"{d['day']}  CHANGE  {h}")
            n += 1
        for h in d["roles"]:
            print(f"{d['day']}  ROLE    unsourced role in an Agenda line: {h}")
            n += 1
        for x in d["cross_day"]:
            print(f"{d['day']}  REVIEW  says {x['term']} wasn't disclosed; {x['earlier_day']} gave it: {x['earlier'][:120]}")
            n += 1
    for d in r["deepdives"]:
        for h in d["header"]:
            print(f"{d['day']}  DEEP DIVE  {h}")
            n += 1
    print(f"Checked {len(r['days'])} editions and {len(r['deepdives'])} deep dives: {n} finding(s). Nothing edited; "
          f"to fix a shipped edition, edit it and ./np correct DAY \"what changed\".")
    return 0


def cmd_takes(cfg: dict, argv: list) -> int:
    """./np takes status [DAY] | email [DAY] | preview [DAY] | done [DAY]: Steven's takes (pipeline/takes.py).
    preview prints the takes email and what replies so far would publish; done releases a held edition now."""
    from pipeline import takes
    sub = (argv or ["status"])[0]
    day = next((a for a in argv[1:] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)), dt.date.today().isoformat())
    if sub == "done":
        print(takes.release_now(ROOT, day))
        return 0
    if sub == "email":
        m = takes.build_email(ROOT, cfg, day)
        print(m["subject"] + "\n\n" + m["text"])
        return 0
    if sub == "preview":
        replies = takes.fetch_replies(ROOT, cfg, day, print)
        merged = {}
        for r in replies:
            merged.update(r["takes"])
        merged = {**takes.slack_takes(ROOT, day, takes.slots(ROOT, day)), **merged}
        for k, v in sorted(merged.items()):
            why = takes.problems(v, cfg)
            print(f"{k}: {'HELD (' + '; '.join(why) + ')' if why else 'ok'}: {v[:160]}")
        print(f"{len(replies)} reply(ies); nothing saved (dry run)")
        return 0
    st = takes.state(ROOT, day)
    c = takes.tcfg(cfg)
    print(f"takes: {'on' if c['enabled'] else 'off'} · cutoff {c['cutoff']} · {day}: "
          f"{'WAITING' if takes.waiting(ROOT, day) else ('released ' + st['released_at'][11:16] if st.get('released_at') else 'not started')}"
          f" · email {'sent ' + st['emailed_at'][11:16] if st.get('emailed_at') else 'not sent'}")
    for x in st.get("published", []):
        print(f"  published {x['slot']} ({x['from']}): {x['text'][:120]}")
    for x in st.get("held", []):
        print(f"  HELD {x['slot']}: {'; '.join(x['why'])}")
    return 0


def cmd_critic(cfg: dict, argv: list) -> int:
    """./np critic preview [DATE] | email [DATE] | list: the weekly critic email (pipeline/critic.py)."""
    from pipeline import critic
    sub = (argv or ["preview"])[0]
    date = next((a for a in argv[1:] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)), None)
    try:
        if sub == "list":
            for w in critic.history(ROOT):
                print(f"{w['date']}  us {w['ours']['overall']:.1f}  ({len(w.get('shows', []))} shows rated)")
            return 0
        if sub == "email":
            print(critic.send(ROOT, cfg, date))
            return 0
        print(critic.render(ROOT, date)["text"])
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"Critic: {e}")
        return 1


def cmd_secrets(cfg: dict, argv: list) -> int:
    """./np secrets status | set NAME | migrate: where secrets live (never prints values); hidden-prompt entry; .env -> Keychain"""
    from pipeline import vault
    sub = argv[0] if argv else "status"
    if sub == "set" and len(argv) > 1:              # typed at a hidden prompt: never in chat, argv or history
        import getpass
        if not sys.stdin.isatty():
            print("run this in Terminal: ./np secrets set NAME")
            return 1
        name = argv[1].upper()
        if name not in vault.NAMES:
            print("one of: " + ", ".join(vault.NAMES))
            return 1
        v = getpass.getpass(f"{name} (input hidden): ").strip().replace(" ", "") if name == "GMAIL_APP_PASSWORD" \
            else getpass.getpass(f"{name} (input hidden): ").strip()
        print("stored in the Keychain" if v and vault.set_keychain(name, v) else "not stored")
        return 0
    if sub == "migrate":
        try:
            done = vault.migrate()
        except RuntimeError as e:
            print(e)
            return 1
        print("Stored in the Keychain (service news-pipeline): " + (", ".join(done) or "nothing"))
        if done:
            print("Check with ./np secrets status, then delete those lines from .env yourself.")
        return 0
    for n in vault.NAMES:
        print(f"  {n:22} {vault.where(n)}")
    print(f"  .env permissions: {'ok (owner only)' if vault.env_file_mode_ok() else 'TOO OPEN: run chmod 600 .env'}")
    return 0


def cmd_note(cfg: dict, argv: list) -> int:
    """./np note [preview|send] [DAY]: Steven's private note (tomorrow's deep dive, suggestions, watchlist)"""
    from pipeline import editor_note
    sub = argv[0] if argv else "preview"
    day = argv[1] if len(argv) > 1 else dt.date.today().isoformat()
    if sub == "preview":
        m = editor_note.build(ROOT, cfg, day)
        print(m["subject"] + "\n\n" + m["text"])
        return 0
    if sub == "send":
        print(editor_note.send(ROOT, cfg, day, force=True))
        return 0
    print(cmd_note.__doc__)
    return 1


def cmd_watchlist(cfg: dict, argv: list) -> int:
    """./np watchlist [list] | fetch | weekly | backfill [DAYS] | add NAME [relation] | remove NAME | test"""
    import json as _json
    from pipeline import watchlist as wl
    sub = argv[0] if argv else "list"
    commit = lambda m: print("git:", Archive(ROOT, cfg["paths"]).git_commit(m, paths=(wl.FILE, "data/watchlist"))) \
        if cfg.get("archive", {}).get("git_commit", True) else None
    if sub == "list":
        ms = wl.mentions(ROOT, 30)
        for c in wl.load(ROOT):
            mine = [m for m in ms if m["company"] == c["name"]]
            print(f"{c['name']:18} {c.get('relation', ''):13} {len(mine):3} mention(s) in 30 days · search: {wl.query_of(c)}")
            for m in mine[:3]:
                print(f"{'':20}{(m.get('published') or m['found'])[:10]}  [{m['source']}] {m['title'][:80]}")
        return 0
    if sub in ("fetch", "test"):                 # ./np watchlist fetch [DAYS]: DAYS of Google News (default 2)
        nd = int(argv[1]) if len(argv) > 1 and str(argv[1]).isdigit() else 2
        r = wl.fetch(ROOT, cfg, print, news_days=min(nd, 90))
        if sub == "test":
            print("GDELT news search: " + ("OK" if not r["errors"] else "FAILED for " + ", ".join(r["errors"])))
        if r["new"]:
            commit(f"watchlist: {len(r['new'])} new mention(s)")
        return 0 if not r["errors"] or sub == "fetch" else 1
    if sub == "weekly":
        new = wl.weekly_search(ROOT, cfg, log=print)
        commit(f"watchlist: weekly search, {len(new)} new")
        return 0
    if sub == "backfill":
        days = int(argv[1]) if len(argv) > 1 else 14
        items = []
        for d in sorted((ROOT / cfg["paths"]["raw"]).glob("????-??-??"))[-days:]:
            f = d / "items.jsonl"
            if f.exists():
                items += [_json.loads(ln) for ln in f.read_text("utf-8").splitlines() if ln.strip()]
        new = wl.add_mentions(ROOT, wl.scan_items(wl.load(ROOT), items))
        print(f"Watchlist backfill: {len(new)} mention(s) found in {len(items)} archived items")
        commit(f"watchlist: backfill {days} days")
        return 0
    if sub == "add" and len(argv) > 1:
        try:
            wl.add(ROOT, argv[1], argv[2] if len(argv) > 2 else "other")
        except ValueError as e:
            print(e)
            return 1
        commit(f"watchlist: add {argv[1]}")
        return 0
    if sub == "remove" and len(argv) > 1:
        print("removed" if wl.remove(ROOT, argv[1]) else "not on the list")
        commit(f"watchlist: remove {argv[1]}")
        return 0
    print(cmd_watchlist.__doc__)
    return 1


def cmd_deepdive(cfg: dict, argv: list) -> int:
    """./np deepdive [DAY] [--topic "..."] [--force] [--no-audio]: today's topical deep-dive episode"""
    from pipeline import deepdive
    day, topic, force, tts = dt.date.today().isoformat(), "", False, True
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--topic" and i + 1 < len(argv):
            topic, i = argv[i + 1], i + 1
        elif a == "--force":
            force = True
        elif a == "--no-audio":
            tts = False
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", a):
            day = a
        i += 1
    try:
        rec = deepdive.run(ROOT, cfg, day, print, topic=topic, force=force or bool(topic), tts=tts)
        if rec.get("status") == "published":
            deepdive.make_podcast(ROOT, cfg, day)
    except Exception as e:  # noqa: BLE001
        print(f"Deep dive failed: {type(e).__name__}: {e}")
        return 1
    if rec.get("status") in ("published", "written") and cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"deep dive {day}: {rec.get('title', '')[:60]}",
                                                         paths=(deepdive.DIR, deepdive.LOG, "data/episodes.json")))
    elif cfg.get("archive", {}).get("git_commit", True):
        Archive(ROOT, cfg["paths"]).git_commit(f"deep dive {day}: {rec.get('status')}", paths=(deepdive.LOG,))
    return 0 if rec.get("status") in ("published", "written", "skipped") else 1


def factcheck_finder(cfg: dict, ids: list, log=None):
    """Search-before-cut for the fact check (pipeline/factsearch.py); None when switched off or offline."""
    if not (cfg.get("factcheck") or {}).get("search", True):
        return None
    from pipeline import factsearch, netguard, reader
    try:
        ua = (cfg.get("fetch") or {}).get("user_agent", "news-pipeline/0.1")
        c = netguard.client(follow_redirects=True, timeout=12, headers={"User-Agent": ua})
    except Exception as e:  # noqa: BLE001
        if log:
            log.warning("fact search: no HTTP client (%s)", e)
        return None
    raw = stages.raw_items(ROOT, list(dict.fromkeys(ids)), days=30)
    own = [u for it in raw.values() for u in reader.candidates(it) if not reader._text_path(ROOT, u).exists()]
    return factsearch.Finder(c, own[:12], log)


def cmd_factcheck(cfg: dict, argv: list) -> int:
    """./np factcheck [DAY] | probe "sentence" FIGURE: dry run of the fact check (with search-before-cut) on a
    saved briefing, or one live search. Nothing is edited; requests go to logs/news-search.jsonl."""
    import json
    from pipeline import factcheck, factsearch
    if argv and argv[0] == "probe":
        if len(argv) < 3:
            print('usage: ./np factcheck probe "sentence with the figure" FIGURE')
            return 2
        snt, raw = argv[1], argv[2]
        figs = [f for f in factcheck.values(raw)] or factcheck.values(snt)
        if not figs:
            print("no figure found in", raw)
            return 2
        v, r_, k, b = figs[0]
        f = factcheck_finder(cfg, [], None)
        print("names:", factsearch.entities(snt), "| query:", factsearch.query(snt, raw))
        hit = f(raw, v, k, b, snt) if f else None
        print("found:", json.dumps(hit) if hit else "no page with that figure near the name",
              f"({getattr(f, 'requests', 0)} requests)")
        return 0
    day = argv[0] if argv else sorted(p.stem for p in (ROOT / "briefings").glob("????-??-??.md"))[-1]
    md = (ROOT / "briefings" / f"{day}.md").read_text("utf-8")
    recs = [r for r in stages.read_jsonl(ROOT / "data" / "briefings.jsonl") if r.get("day") == day]
    rec = recs[-1] if recs else {}
    ids = rec.get("item_ids") or [i for s_ in rec.get("stories", []) for i in s_.get("ids", [])]
    f = factcheck_finder(cfg, ids, None)
    _md, fc = factcheck.check(md, factcheck.corpus(ROOT, ids), find=f)
    print(f"{day}: {fc['checked']} figures checked, {len(ids)} source items, {getattr(f, 'requests', 0)} requests")
    for c in fc["sourced"]:
        print(f"  FOUND  {c['figure']} via {c['how']}: {c['url']}  ({c['text']})")
    for c in fc["cut"]:
        print("  CUT   ", c)
    for c in fc["flagged"]:
        print("  FLAG  ", c)
    return 0


def cmd_reader(cfg: dict, argv: list) -> int:
    """./np reader check [DAYS]: try the article reader on the last DAYS' critiqued items (no model, no edits)"""
    from collections import Counter
    from urllib.parse import urlparse
    from pipeline import reader
    days = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 5
    files = sorted((ROOT / "data" / "summaries").glob("????-??-??.jsonl"))[-days:]
    ids, verdict = [], {}
    for f in files:
        for r in stages.read_jsonl(f):
            if isinstance(r.get("critique_detail"), dict):
                ids.append(r["id"])
                verdict[r["id"]] = r["critique_detail"].get("verdict", "")
    raw = stages.raw_items(ROOT, list(dict.fromkeys(ids)))
    items = [dict(it) for it in raw.values()]
    old = reader.MAX_FETCH
    reader.MAX_FETCH = 200
    try:
        st = reader.read_thin(ROOT, items, cfg)
    finally:
        reader.MAX_FETCH = old
    print(f"{len(items)} critiqued item(s) over {len(files)} day(s): {st['thin']} headline-only; "
          f"{st['read']} article(s) read, {st['unreadable']} unreadable -> Unverified, "
          f"{st['no_link']} posts with no link (judged as posts) ({st['fetched']} fetched)")
    was = Counter(verdict.get(it["id"], "") for it in items if it.get("thin") or it.get("read_text"))
    print("their old verdicts:", dict(was))
    print("still unreadable, by site:", dict(Counter(urlparse((reader.candidates(it) or [it.get("url", "")])[0]).netloc
                                                     for it in items if it.get("thin")).most_common(8)))
    return 0


def cmd_quality(cfg: dict, argv: list) -> int:
    """./np quality [DAY | all] | rate DAY SCORE [note] | pull: the daily scorecard (data/quality/), ratings"""
    from pipeline import quality
    if argv and argv[0] == "pull":
        print(f"{quality.pull_stars(ROOT, cfg)} star rating(s) pulled (email.ratings must be true)")
        argv = argv[1:]
    elif not argv or argv[0] == "all":
        try:
            quality.pull_stars(ROOT, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"(star ratings not pulled: {e})")
    if argv and argv[0] == "rate":
        if len(argv) < 3:
            print(cmd_quality.__doc__)
            return 1
        quality.add_rating(ROOT, argv[1], int(argv[2]), "steven", " ".join(argv[3:]))
        quality.score_day(ROOT, cfg, argv[1])
        print(f"{argv[1]} rated {argv[2]}/5")
        return 0
    bdir = ROOT / cfg["paths"]["briefings"]
    days = sorted(f.stem for f in bdir.glob("????-??-??.md"))
    if argv and argv[0] != "all":
        days = [argv[0]]
    elif not argv:
        days = days[-7:]
    rows = [r for r in (quality.score_day(ROOT, cfg, d) for d in days) if r]
    for r in rows:
        bad = [f"{c['label']} {quality.fmt(c['value'])} (target {c['target']})" for c in r["checks"] if not c["ok"]]
        rate = f" · you {r['rating_steven']}/5" if r["rating_steven"] else ""
        rate += f" · readers {r['rating_readers']}/5 ({r['n_reader_ratings']})" if r["rating_readers"] else ""
        rate += f" · site {r['rating_web']}/5 ({r['n_web_ratings']})" if r.get("rating_web") else ""
        print(f"{r['day']}  {r['passed']}/{r['total']} checks{rate}")
        for b in bad:
            print(f"      ✗ {b}")
        for d in r["privacy_details"]:
            print(f"      privacy: {d}")
    return 0


def cmd_profiles(cfg: dict, argv: list) -> int:
    """./np profiles [DAYS]: sites and sources seen recently with no entry in source_profiles.yaml"""
    from pipeline import profiles
    days = int(argv[0]) if argv else 14
    u = profiles.unprofiled(ROOT, days)
    t = profiles.table()
    print(f"source_profiles.yaml: {len(t['outlets'])} sites, {len(t['sources'])} sources profiled")
    print(f"Sites cited in the last {days} days with no profile (add under outlets:):")
    for h, n in u["sites"][:30]:
        print(f"  {n:4}  {h}")
    print("Sources with no profile of their own (they get the default for their kind; add under sources:):")
    for p, n in u["sources"][:30]:
        print(f"  {n:4}  {p}")
    return 0


def cmd_relink(cfg: dict, day: str) -> int:
    """./np relink DAY: fix an already-written briefing's links and labels (no model, no audio); then ./np publish"""
    from pipeline import links
    p = ROOT / cfg["paths"]["briefings"] / f"{day}.md"
    if not p.is_file():
        print(f"no briefing for {day}")
        return 1
    md, rep = links.relink_markdown(ROOT, p.read_text("utf-8"), cfg)
    names = stages.private_names()
    md, hits = stages.scrub_private(md, names, stages.allowed_names(names, []))
    if hits:
        print(f"{day}: removed {len(hits)} private name(s) from the written edition")
    p.write_text(md, "utf-8")
    print(f"{day}: {rep['trackers']} tracker link(s), {rep['resolved']} resolved to the article, "
          f"{rep['removed']} personal link(s)/address(es) removed; labels and number style updated")
    left = [u for u in re.findall(r"\]\((https?://[^)]+)\)", md) if links.personal(u, cfg)]
    print("personal links left: " + (str(len(left)) if left else "none"))
    if cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"relink {day}: no personal links", paths=(str(p.relative_to(ROOT)),)))
    print("Next: ./np publish   (the site page updates; the episode and its audio are untouched)")
    return 0 if not left else 1


def cmd_feedback(cfg: dict, argv: list) -> int:
    """./np feedback [list|all] | fetch [DAYS] | triage | set ID STATUS [note] | todo ID: replies to the daily email"""
    from pipeline import feedback as fb
    sub = argv[0] if argv else "list"
    commit = lambda m: print("git:", Archive(ROOT, cfg["paths"]).git_commit(m, paths=(fb.STORE,))) \
        if cfg.get("archive", {}).get("git_commit", True) else None
    if sub == "fetch":
        try:
            r = fb.fetch(ROOT, cfg, print, int(argv[1]) if len(argv) > 1 else None)
        except Exception as e:  # noqa: BLE001
            print(f"Feedback fetch failed: {e}")
            return 1
        if r["added"]:
            commit(f"feedback: {r['added']} new repl(ies)")
        return 0
    if sub == "triage":
        try:
            r = fb.triage(ROOT, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"Feedback triage failed: {e}")
            return 1
        if r.get("triaged"):
            commit(f"feedback: triaged {r['triaged']}")
        return 0
    if sub in ("set", "todo"):
        if len(argv) < 2 + (sub == "set"):
            print(cmd_feedback.__doc__)
            return 1
        try:
            if sub == "set":
                it = fb.set_status(ROOT, argv[1], argv[2], " ".join(argv[3:]))
                print(f"{it['id']} -> {it['status']}")
            else:
                from pipeline import todos
                it = next(i for i in fb.load(ROOT)["items"] if i["id"] == argv[1])
                t = it.get("triage") or {}
                todos.add(ROOT, ("Feedback: " + (t.get("summary") or it["text"][:100]))[:160], "feedback", "claude",
                          detail=t.get("action", ""))
                fb.set_status(ROOT, it["id"], "acting", "to-do created")
                print(f"{it['id']} -> to-do created, status acting")
        except (KeyError, StopIteration, ValueError) as e:
            print(f"Feedback: {e}")
            return 1
        commit(f"feedback: {sub} {argv[1]}")
        return 0
    if sub in ("list", "all"):
        d = fb.load(ROOT)
        c = fb.counts(ROOT)
        print(f"Feedback: {c['total']} repl(ies), {c['open']} open, {c['new']} not triaged, {c['high']} high"
              + (f"  (triaged {d['triaged_at'][:16]})" if d["triaged_at"] else ""))
        rank = {"high": 0, "medium": 1, "low": 2}
        rows = d["items"] if sub == "all" else [i for i in d["items"] if i.get("status") in fb.OPEN]
        for it in sorted(rows, key=lambda i: (rank.get((i.get("triage") or {}).get("severity"), 3), i["received"])):
            t = it.get("triage") or {}
            print(f"  {it['id']}  {t.get('severity', '-'):6} {t.get('category', 'new'):17} {it['status']:8} "
                  f"{it.get('day') or it['received'][:10]}  {(t.get('summary') or it['text'])[:80]}")
            if t.get("action"):
                print(f"{'':14}-> {t['action'][:110]}")
        for th in d["themes"]:
            print(f"  theme ({th['count']}): {th['theme']} -> {th['suggestion'][:100]}")
        return 0
    print(cmd_feedback.__doc__)
    return 1


def cmd_linkedin(cfg: dict, argv: list) -> int:
    """./np linkedin import [PATH] | list [N]: Steven's own posts from LinkedIn's data export (data/inbox/)"""
    from pipeline import linkedin as li
    sub = argv[0] if argv else "list"
    if sub == "import":
        try:
            r = li.import_export(ROOT, Path(argv[1]).expanduser() if len(argv) > 1 else None)
        except (FileNotFoundError, OSError, ValueError) as e:
            print(f"LinkedIn import: {e}")
            return 1
        print(f"Read {r['file']}")
        print(f"  {r['posts']} post(s), {r['articles']} article(s), {r['from']} to {r['to']}")
        print(f"  {r['public']} public (only these feed the public record), {r['with_article']} shared an article")
        print(f"  {r['added']} new -> {li.STORE}")
        top = li.domains(li.load(ROOT))
        if top:
            print("  most-shared sites: " + ", ".join(f"{h} ({n})" for h, n in top))
        print("Next: ./np record words  (proposes 'In my own words' lines from these posts for author.md)")
        if r["added"] and cfg.get("archive", {}).get("git_commit", True):
            print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"public record: {r['added']} LinkedIn post(s)",
                                                                  paths=(li.STORE,)))
        return 0
    if sub == "list":
        n = int(argv[1]) if len(argv) > 1 else 15
        rows = sorted(li.load(ROOT), key=lambda p: p.get("date", ""), reverse=True)
        print(f"{len(rows)} LinkedIn post(s) stored ({sum(1 for p in rows if li._public(p['visibility']))} public)")
        for p in rows[:n]:
            txt = re.sub(r"\s+", " ", p.get("title") or p.get("text", ""))[:90]
            print(f"  {p.get('date', ''):10}  {p['kind']:7} {'pub ' if li._public(p['visibility']) else 'conn'}  {txt}")
        return 0
    print(cmd_linkedin.__doc__)
    return 1


def cmd_slack(cfg: dict, argv: list) -> int:
    """./np slack test | fetch [HOURS]: links Steven shares in an internal Slack channel (read-only)"""
    import httpx
    import logging
    from pipeline import slacksource as ss
    sub = argv[0] if argv else "test"
    s = ss.scfg(cfg)
    if sub == "test":
        with httpx.Client(timeout=20) as c:
            try:
                me = ss._call(c, "auth.test")
                print(f"Slack: signed in as {me.get('user')} in {me.get('team')}")
                ch = ss.find_channel(c, s["channel"])
                print(f"channel #{ch['name']} found ({'shared' if ch.get('is_shared') or ch.get('is_ext_shared') else 'not shared'})")
                d = ss._call(c, "conversations.history", channel=ch["id"], limit=100)
                posters = {}
                for m in d.get("messages", []):
                    if m.get("user"):
                        posters[m["user"]] = posters.get(m["user"], 0) + 1
                print("who posts there (put Steven's ID in config.yaml slack.authors):")
                for uid, n in sorted(posters.items(), key=lambda x: -x[1]):
                    try:
                        u = ss._call(c, "users.info", user=uid)["user"]
                        name = u.get("real_name") or u.get("name")
                    except ss.SlackError:
                        name = "?"
                    print(f"  {uid}  {name:28} {n} message(s)")
            except ss.SlackError as e:
                print(f"Slack: {e}")
                return 1
        return 0
    if sub == "fetch":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        hours = int(argv[1]) if len(argv) > 1 else None
        res = ss.fetch(ROOT, cfg, "manual", logging.getLogger("slack"), hours)
        archive = Archive(ROOT, cfg["paths"])
        added = archive.add_items(res["items"], dt.date.today().isoformat())
        print(f"{len(res['items'])} shared link(s), {added} new archived.")
        if added and cfg.get("archive", {}).get("git_commit", True):
            print("git:", archive.git_commit(f"archive: {added} link(s) Steven shared"))
        return 0
    print(cmd_slack.__doc__)
    return 2


def cmd_say(cfg: dict, text: str) -> int:
    """./np say "TEXT": hear how the voice says TEXT with the pronunciation table -> briefings/voice-samples/say.mp3"""
    from pipeline import audio, speech
    said = speech.spoken(text, speech.load_table(ROOT))
    print("spoken as:", said)
    eng = audio.engine_from(cfg)
    eng.check()
    out = ROOT / "briefings" / "voice-samples" / "say.mp3"
    audio.render_mp3(eng, [("say", said)], out, "say")
    print(f"-> {out.relative_to(ROOT)}  (open it: open {out})")
    return 0


def cmd_voices(cfg: dict) -> int:
    """Make the same ~60-second sample in each candidate voice: briefings/voice-samples/."""
    from pipeline import audio
    a = cfg.get("audio", {})
    text = a.get("sample_text") or (
        "Good morning. This is your AI briefing for Monday, October 5th. Three threads matter today. "
        "First, agent security has moved from theory to real incidents: OpenAI paused training after its agents "
        "reached data beyond their scope. Second, Reuters puts Anthropic's non-cancelable compute obligations at "
        "252 billion dollars. Our critical read: the Reuters figure is solid, the loss estimates are not. "
        "The editor's view: ask every AI-native company what happens to gross margin if model prices rise 30 percent.")
    out = ROOT / "briefings" / "voice-samples"
    out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for v in a.get("sample_voices", []):
        if isinstance(v, dict):                      # YAML reads a bare `say:` as a mapping
            v = next(iter(v)) + ":"
        eng_name, _, voice = str(v).partition(":")
        voice = "" if voice == "default" else voice
        eng = audio.MacSay(voice, a.get("speed", 1.0)) if eng_name == "say" else audio.Kokoro(voice, a.get("speed", 1.0))
        try:
            eng.check()
            mins = audio.render_mp3(eng, [("sample", text)], out / f"{eng_name}-{voice or 'default'}.mp3", f"Sample {v}")
            print(f"  OK   {v}  ({mins * 60:.0f}s)")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {v}: {e}")
    print(f"{ok} samples in briefings/voice-samples/. Listen: http://127.0.0.1:8765/voices")
    return 0 if ok else 1


def pending_items(cfg: dict, archive: Archive, day: str, reprocess_day=None, limit=None) -> list:
    """Items that still need LLM processing (or every item first seen on reprocess_day)."""
    paths = cfg["paths"]
    archive_index = stages.read_jsonl(archive.index_path)
    rows = archive_index
    if reprocess_day:
        rows = [r for r in archive_index if r.get("first_seen") == reprocess_day]
    else:
        done = stages.latest_summaries(ROOT / paths["summaries"])
        days = cfg.get("analysis", {}).get("process_days", 3)
        cutoff = (dt.date.fromisoformat(day) - dt.timedelta(days=days - 1)).isoformat()
        rows = [r for r in archive_index if r["id"] not in done and r.get("first_seen", "") >= cutoff]
    by_file = {}
    for r in rows:
        by_file.setdefault(r["raw"], set()).add(r["id"])
    items = []
    for raw, ids in by_file.items():
        items += [it for it in stages.read_jsonl(ROOT / raw) if it["id"] in ids]
    items.sort(key=lambda it: it.get("published") or "", reverse=True)
    return items[:limit] if limit else items


def llm_stage_names(acfg: dict, rebrief: bool = False) -> list:
    """The model-backed stages a run needs. A rebrief reuses the filter and rank results but still needs the
    critique model: the v2 verify stage (evidence check on every Must read) calls it (fixed in v0.1.5)."""
    names = ["filter", "rank", "critique", "write"]
    if acfg.get("briefing_format", "v2") == "v2":
        names[3:3] = ["cluster", "merge", "editorial"]
    if rebrief:
        names = [s for s in names if s not in ("filter", "rank")]
    return names


def run_llm_stages(run: Run, cfg: dict, archive: Archive, reprocess_day=None, limit=None, rebrief_day=None,
                   experiment=None) -> str:
    """filter → summarize → critique → write. Returns 'ok', 'partial' or 'error'."""
    paths = cfg["paths"]
    acfg = cfg.get("analysis", {})
    summaries_dir = ROOT / paths["summaries"]
    briefings_log = ROOT / paths.get("briefings_log", "data/briefings.jsonl")
    persp = perspective.load(ROOT / paths["perspective"])
    system, sys_v = stages.system_prompt(persp.raw)
    llm_stages = llm_stage_names(acfg, bool(rebrief_day))
    backends = {s: llm.for_stage(cfg, s) for s in llm_stages}
    status = "ok"

    # Pre-flight: one check per distinct backend, with a clear message.
    checked = {}
    for s, b in backends.items():
        key = (b.name, b.model)
        if key not in checked:
            try:
                checked[key] = b.check()
            except llm.LLMError as e:
                checked[key] = str(e)
        if checked[key] != "ok":
            run.record["stages"][s] = {"status": "error", "error": f"{b.label}: {checked[key]}"}
            run.log.error("stage %s: %s unavailable: %s", s, b.label, checked[key])
    if any(run.record["stages"].get(s, {}).get("status") == "error" for s in backends):
        for s in backends:
            if run.record["stages"].get(s, {}).get("status") != "error":
                run.skip(s, "LLM backend unavailable")
        return "error"

    items = [] if rebrief_day else pending_items(cfg, archive, run.day, reprocess_day, limit)
    labels_by_host = {}
    src_file = ROOT / paths["sources"]
    if src_file.exists():
        for row in (yaml.safe_load(src_file.read_text("utf-8")) or {}).get("sources") or []:
            if row.get("label"):
                labels_by_host[stages._host(row["url"])] = row["label"]
    stages.apply_labels(items, labels_by_host)
    meta = {"run_id": run.run_id, "day": run.day,
            "models": {k: backends[s].label for k, s in (("filter", "filter"), ("summarize", "rank"),
                                                       ("critique", "critique")) if s in backends},
            "prompt_versions": {"system": sys_v}}

    if rebrief_day:
        for s in ("filter", "rank", "critique"):
            run.skip(s, f"rebrief {rebrief_day}: reusing existing analyses")
        decisions, summaries, critiques = {}, {}, {}
    if not rebrief_day:
        with run.stage("filter") as st:
            known_urls = {row["url"] for row in stages.read_jsonl(archive.index_path)}
            excl = sorted({x for row in (yaml.safe_load((ROOT / paths["sources"]).read_text("utf-8")) or {}).get("sources", [])
                           if row.get("kind") == "pages" for x in (row.get("exclude") or [])
                           if not stages._LOCALE_RE.match(x)}) \
                if (ROOT / paths["sources"]).exists() else []
            from pipeline.slacksource import PRIVATE_HOSTS
            excl = excl + [h for h in PRIVATE_HOSTS if h != "slack.com"]   # private documents never reach a model
            to_llm, pre = stages.prefilter(items, known_urls, acfg.get("min_content_chars", 25), exclude=excl)
            from pipeline import linkedin               # Steven's own LinkedIn posts: public record, never news
            own = [it for it in items if linkedin.is_own_post(it, cfg)]
            if own:
                linkedin.add_posts(ROOT, [linkedin.from_item(it) for it in own])
                for it in own:
                    pre[it["id"]] = {"keep": False, "rule": True, "reason": "Steven's own LinkedIn post (public record)"}
                to_llm = [it for it in to_llm if it["id"] not in pre]
            decisions, v, errs = stages.run_filter(backends["filter"], to_llm, system, acfg, run.log)
            decisions.update(pre)
            meta["prompt_versions"]["filter"] = v
            kept = [it for it in items if decisions[it["id"]]["keep"]]
            st.update({"items_in": len(items), "kept": len(kept), "dropped": len(items) - len(kept),
                       "dropped_by_rule": len(pre),
                       "model": backends["filter"].label, "errors": errs[:10]})
            if errs:
                st["status"] = "partial"
            run.log.info("filter: %d in, %d kept", len(items), len(kept))

        with run.stage("rank") as st:
            summaries, v, errs = stages.run_summarize(backends["rank"], kept, system, acfg, run.log)
            meta["prompt_versions"]["summarize"] = v
            tags = [s["tag"] for s in summaries.values()]
            st.update({"items_in": len(kept), "summarized": len(summaries), "failed": len(errs),
                       "full_read": tags.count("FULL READ"), "model": backends["rank"].label,
                       "errors": errs[:10]})
            if errs:
                st["status"] = "partial"

        with run.stage("critique") as st:
            targets = [it for it in kept if it["id"] in summaries and stages.needs_critique(it, summaries[it["id"]])]
            if acfg.get("read_thin", True):            # read the article behind headline-only posts first
                try:
                    from pipeline import reader
                    st["reader"] = reader.read_thin(ROOT, targets, cfg, run.log)
                except Exception as e:  # noqa: BLE001 - never blocks the critique
                    run.log.warning("reader skipped: %s", e)
            critiques, v, errs = stages.run_critique(backends["critique"], targets, summaries, system, acfg, run.log)
            meta["prompt_versions"]["critique"] = v
            verdicts = [c["verdict"] for c in critiques.values()]
            st.update({"items_in": len(targets), "critiqued": len(critiques),
                       "verdicts": {x: verdicts.count(x) for x in stages.VERDICTS if x in verdicts},
                       "model": backends["critique"].label, "errors": errs[:10]})
            if errs:
                st["status"] = "partial"

    recs = stages.build_records(items, decisions, summaries, critiques, meta)
    if recs:
        stages.append_records(summaries_dir, run.day, recs)

    latest = stages.latest_summaries(summaries_dir)
    this_run = {r["id"] for r in recs if r.get("keep")}
    if rebrief_day:
        day_ids = {row["id"] for row in stages.read_jsonl(archive.index_path) if row.get("first_seen") == rebrief_day}
        entries = [latest[i] for i in day_ids if i in latest and latest[i].get("keep") and latest[i].get("claim")]
    elif reprocess_day:
        entries = [latest[i] for i in this_run]
    else:
        already = stages.briefed_ids(briefings_log)
        entries = [r for r in latest.values() if r.get("keep") and r.get("claim")
                   and (r["id"] in this_run or r["id"] not in already)
                   and r.get("day", "") >= (dt.date.fromisoformat(run.day)
                                            - dt.timedelta(days=acfg.get("process_days", 3) - 1)).isoformat()]
    stages.apply_labels(entries, labels_by_host)
    entries = [r for r in entries if (r.get("importance") or 0) > 1 or r.get("tag") == "FULL READ"]
    # Translated copies of the same post (e.g. example.ai/de/... and /fr/...) never both reach a briefing,
    # even when they were analyzed before the translation rule existed.
    seen_canon, deduped = {}, []
    for r in sorted(entries, key=lambda r: (stages.canonical_url(r["url"]) != r["url"], -(r.get("importance") or 0))):
        c = stages.canonical_url(r["url"])
        if c not in seen_canon:
            seen_canon[c] = r["id"]
            deduped.append(r)
    entries = deduped
    day = rebrief_day or reprocess_day or run.day
    dropped = sum(1 for r in recs if not r.get("keep"))
    if rebrief_day:
        day_ids = {row["id"] for row in stages.read_jsonl(archive.index_path) if row.get("first_seen") == rebrief_day}
        dropped = sum(1 for i in day_ids if i in latest and not latest[i].get("keep"))
    v2 = acfg.get("briefing_format", "v2") == "v2"
    if not entries:
        for s in ("cluster", "editorial", "write"):
            run.skip(s, "nothing new to brief")
    elif v2:
        write_v2(run, cfg, backends, system, entries, day, dropped, meta, briefings_log, experiment)
    else:
        run.skip("cluster", "briefing_format v1")
        run.skip("editorial", "briefing_format v1")
        with run.stage("write") as st:
            md0, order = stages.render_briefing(day, entries, [], {}, 0, acfg.get("max_full_read", 6),
                                                acfg.get("max_worth_knowing", 12))
            numbered = {i: n for n, i in enumerate(order, 1)}
            top = sorted((r for r in entries if r["id"] in numbered),
                         key=lambda r: numbered[r["id"]])[:acfg.get("topline_items", 8)]
            bullets, tv = stages.topline(backends["write"], [(numbered[r["id"]], r) for r in top], system, run.log)
            models = sorted({b.label for b in backends.values()})
            md, order = stages.render_briefing(day, entries, bullets, {
                "models": ", ".join(models),
                "generated": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")}, dropped,
                acfg.get("max_full_read", 6), acfg.get("max_worth_knowing", 12))
            st.update(save_briefing(run, cfg, day, md, order, entries, models,
                                    {**meta["prompt_versions"], "topline": tv}, briefings_log))
            st["topline_bullets"] = len(bullets)
    for s in ("filter", "rank", "critique", "cluster", "editorial", "write"):
        if run.record["stages"].get(s, {}).get("status") in ("partial", "error"):
            status = "partial"
    return status


def cmd_run(cfg: dict, lookback_hours=None, commit=True, no_llm=False, stages_only=False,
            reprocess_day=None, limit=None, rebrief_day=None, experiment=None) -> int:
    paths = cfg["paths"]
    src_file = ROOT / paths["sources"]
    if not src_file.exists() and not (stages_only or reprocess_day or rebrief_day):
        print("No sources.yaml yet. Run: python run.py --verify-sources")
        return 1
    rows = (yaml.safe_load(src_file.read_text("utf-8")) or {}).get("sources") or [] if src_file.exists() else []
    archive = Archive(ROOT, paths)
    run = Run(archive, ROOT / paths["logs"], cfg)
    run.record["profile"] = cfg.get("tuning_profile") or {}
    if experiment:
        run.record["experiment"] = experiment
    status = "ok"
    try:
        if stages_only or reprocess_day or rebrief_day:
            run.skip("fetch", "stages-only run" if stages_only else f"reprocess {reprocess_day or rebrief_day}")
        else:
            with run.stage("fetch") as st:
                run.log.info("fetching %d sources", len(rows))
                res = fetch.fetch_all(rows, cfg, archive, run.run_id, run.log, lookback_hours)
                if (cfg.get("email_sources") or {}).get("enabled"):
                    from pipeline import mailsource
                    try:
                        mres = mailsource.fetch(ROOT, cfg, run.run_id, run.log)
                        res["items"] += mres["items"]
                        res["sources"] += mres["sources"]
                        st["newsletters"] = {"new": len(mres["items"]), "unlisted": len(mres["unlisted"])}
                        run.log.info("  gmail newsletters: %d new item(s), %d unlisted sender(s)",
                                     len(mres["items"]), len(mres["unlisted"]))
                    except mailsource.MailError as e:
                        run.log.warning("  FAIL gmail newsletters: %s", e)
                        res["sources"].append({"person": "Gmail newsletters", "kind": "email", "url": "gmail",
                                               "status": "error", "error": str(e)[:300]})
                if (cfg.get("bluesky") or {}).get("lists") or (cfg.get("bluesky") or {}).get("own"):
                    from pipeline import bluesky
                    bres = bluesky.fetch(cfg, run.run_id, run.log, lookback_hours)
                    res["items"] += bres["items"]
                    res["sources"] += bres["sources"]
                    st["bluesky_lists"] = {"new": len(bres["items"])}
                if (cfg.get("slack") or {}).get("enabled"):
                    from pipeline import slacksource
                    sres = slacksource.fetch(ROOT, cfg, run.run_id, run.log, lookback_hours)
                    res["items"] += sres["items"]
                    res["sources"] += sres["sources"]
                    st["shared_links"] = {"new": len(sres["items"])}
                if (ROOT / "x.yaml").exists() and (cfg.get("x") or {}).get("enabled", True):
                    from pipeline import xsource
                    xres = xsource.fetch(ROOT, cfg, run.run_id, run.log, lookback_hours)
                    res["items"] += xres["items"]
                    res["sources"] += xres["sources"]
                    st["x"] = {"new": len(xres["items"]), "mirror": xres["instance"]}
                before = archive.known_ids()
                added = archive.add_items(res["items"], run.day)
                try:                            # public record: who/what of Steven's world is mentioned
                    from pipeline import record
                    fresh = [it for it in res["items"] if it.get("id") not in before]
                    st["mentions"] = record.log_mentions(ROOT, run.day, run.run_id, record.scan(fresh, cfg), cfg)
                except Exception as e:  # noqa: BLE001 - never blocks the briefing
                    run.log.warning("mention scan failed: %s", e)
                failed = [s for s in res["sources"] if s["status"] != "ok"]
                st.update({"sources_total": len(rows), "sources_failed": len(failed),
                           "items_new": added, "window_since": res["since"],
                           "raw_file": str(archive.raw_file(run.day).relative_to(ROOT)) if added else "",
                           "per_source": res["sources"]})
                if failed:
                    st["status"] = "partial"
                    status = "partial"
        if no_llm:
            for s in ("filter", "rank", "critique", "cluster", "editorial", "write", "audio"):
                run.skip(s, "--no-llm")
        else:
            s2 = run_llm_stages(run, cfg, archive, reprocess_day, limit, rebrief_day, experiment)
            if s2 == "error":
                status = "partial" if run.record["stages"]["fetch"].get("status") in ("ok", "partial") else "error"
            elif s2 == "partial":
                status = "partial"
            if run.record["stages"].get("write", {}).get("status") == "ok":
                if not (experiment or rebrief_day or reprocess_day) and (cfg.get("deepdive") or {}).get("enabled"):
                    try:                         # write and check today's deep dive now: the briefing hands off
                        from pipeline import deepdive   # to it only if its script passed the checks
                        if deepdive.plan_today(ROOT, cfg, run.day, log=run.log.info):
                            deepdive.run(ROOT, cfg, run.day, log=run.log.info, tts=False)
                    except Exception as e:  # noqa: BLE001
                        run.log.warning("deep dive skipped: %s", e)
                    _align_with_deepdive(run, cfg, run.day)
                make_audio(run, cfg, rebrief_day or reprocess_day or run.day, experiment)
    except Exception as e:  # noqa: BLE001
        import traceback
        run.log.error("run failed: %s\n%s", e, traceback.format_exc())
        status = "error"
    finally:
        run.finish(status)
        if commit and cfg.get("archive", {}).get("git_commit", True):
            fs = run.record["stages"]["fetch"]
            ws = run.record["stages"]["write"]
            msg = (f"archive: run {run.run_id} ({status}), {fs.get('items_new', 0)} new items"
                   + (f", briefing {ws['file']}" if ws.get("file") else ""))
            if experiment:
                msg = f"experiment: {experiment} on {rebrief_day} ({status}), {ws.get('file', '')}"
            run.log.info("git: %s", archive.git_commit(msg))
            if cfg.get("archive", {}).get("push"):
                from pipeline import publish
                try:
                    run.log.info("backup: %s", publish.backup_push(ROOT))
                except RuntimeError as e:
                    run.log.warning("backup push failed: %s", e)
    st = run.record["stages"]
    print(f"\nRun {run.run_id}: {status}.")
    for name, s in st.items():
        extra = s.get("error") or s.get("reason") or ""
        print(f"  {name:9} {s.get('status', ''):8} {extra}")
    if st["write"].get("file"):
        print(f"Briefing: {st['write']['file']}")
    print(f"Log: {run.record['log']}")
    return 0 if status in ("ok", "partial") else 1


def cmd_doctor(cfg: dict) -> int:
    """Environment check: Python, packages, LLM backends, sources, git, archive size."""
    import importlib
    import platform
    import subprocess
    ok = True

    def line(status, what, detail=""):
        nonlocal ok
        ok = ok and status != "FAIL"
        print(f"  {status:4} {what}" + (f": {detail}" if detail else ""))

    print("news-pipeline doctor")
    v = sys.version_info
    line("OK" if v >= (3, 9) else "FAIL", "python", f"{platform.python_version()} at {sys.executable}")
    for mod in ("feedparser", "httpx", "yaml", "flask", "markdown", "dotenv"):
        try:
            m = importlib.import_module(mod)
            line("OK", f"package {mod}", getattr(m, "__version__", ""))
        except ImportError:
            line("FAIL", f"package {mod}", "missing: run ./np setup")
    seen = set()
    for stage in ("filter", "rank", "critique", "write"):
        b = llm.for_stage(cfg, stage)
        if b.label in seen:
            continue
        seen.add(b.label)
        try:
            b.check()
            line("OK", f"llm {b.label}", f"used for {stage}" + ("" if stage == "filter" else "+"))
        except llm.LLMError as e:
            line("FAIL", f"llm {b.label}", str(e))
    src = ROOT / cfg["paths"]["sources"]
    n = len((yaml.safe_load(src.read_text("utf-8")) or {}).get("sources") or []) if src.exists() else 0
    line("OK" if n else "FAIL", "sources.yaml", f"{n} verified sources")
    g = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    line("OK" if g.returncode == 0 else "FAIL", "git", f"{len(g.stdout.splitlines())} uncommitted change(s)")
    size = sum(f.stat().st_size for f in (ROOT / "data").rglob("*") if f.is_file()) if (ROOT / "data").exists() else 0
    line("OK", "archive size", f"{size / 1e6:.1f} MB in data/")
    print("All good." if ok else "Some checks failed (see FAIL lines).")
    return 0 if ok else 1


def wait_for_network(minutes: int = 10, host: str = "bsky.app") -> bool:
    """True once DNS resolves (the 2026-10-10 runs fired while the Mac had no network)."""
    import socket
    import time
    deadline = time.monotonic() + minutes * 60
    while True:
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(30)


def _owner() -> dict:
    from pipeline.owner import get
    return get(ROOT)


def _notify(title: str, msg: str) -> None:
    import subprocess
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification "{msg.replace(chr(34), chr(39))[:220]}" '
                        f'with title "{title}"'], capture_output=True)


def _next_try(cfg: dict) -> str:
    """The next scheduled daily time today ("" if this was the last one)."""
    now = dt.datetime.now().strftime("%H:%M")
    later = [t for t in sorted(str(x) for x in (cfg.get("schedule") or {}).get("times", [])) if t > now]
    return later[0] if later else ""


def _wait_live(cfg: dict, day: str) -> None:
    """Hold the email until GitHub Pages serves today's pages (up to publish.wait_live_seconds, default 300)."""
    try:
        from pipeline import publish
        publish.wait_live(cfg, day, timeout=int((cfg.get("publish") or {}).get("wait_live_seconds", 300)))
    except Exception as e:  # noqa: BLE001 - never blocks the email
        print(f"site check skipped: {e}")


def _publish_and_verify(cfg: dict, today: str, alert: bool = True) -> bool:
    """Publish, wait until live, then check that readers' pages, feeds and audio answer. False = don't email:
    if the live check fails the previous site is put back first (shipped editions never break)."""
    if cmd_publish(cfg):
        if alert:
            _alert(cfg, "publish", detail="See logs/last-command.txt for the error. The live site was not changed.",
                   next_try=_next_try(cfg))
        return False
    _wait_live(cfg, today)
    from pipeline import publish, shipped
    bad = shipped.verify_live(ROOT, (cfg.get("publish") or {}).get("site_url", ""))
    if not bad:
        return True
    try:
        msg = publish.restore(ROOT, cfg)
    except Exception as e:  # noqa: BLE001
        msg = f"restore failed: {e}"
    print(f"After-publish check failed ({'; '.join(bad[:4])}); {msg}")
    _alert(cfg, "publish", detail=f"After publishing, these didn't answer: {'; '.join(bad[:6])}. {msg}. "
                                  "The email is held until a publish passes.", next_try=_next_try(cfg))
    return False


def _alert(cfg: dict, kind: str, **kw) -> None:
    try:
        from pipeline import alerts
        alerts.send(ROOT, cfg, kind, **kw)
    except Exception as e:  # noqa: BLE001 - an alert never breaks the run
        print(f"alert skipped: {e}")


def _gate_alert(cfg: dict, err: str, when: str = "morning") -> None:
    from pipeline import release
    if "approval" in err:
        _alert(cfg, "approval", detail=err, files=release.changed_sensitive(ROOT), when=when,
               next_try=_next_try(cfg) if when == "morning" else "")
    else:
        _alert(cfg, "gate", detail=err, when=when, next_try=_next_try(cfg) if when == "morning" else "")


def _make_podcast(cfg: dict, today: str):
    """One podcast episode: briefing (with any takes), hand-off, deep dive."""
    try:
        from pipeline import deepdive
        if (deepdive.latest(ROOT, today) or {}).get("status") == "published":
            deepdive.make_podcast(ROOT, cfg, today)
            if cfg.get("archive", {}).get("git_commit", True):
                Archive(ROOT, cfg["paths"]).git_commit(f"deep dive {today}: recorded",
                                                       paths=(deepdive.DIR, deepdive.LOG, "data/episodes.json"))
    except Exception as e:  # noqa: BLE001
        print(f"podcast episode skipped: {e}")


def _takes_step(cfg: dict, today: str) -> dict:
    """Steven's takes (pipeline/takes.py): the private email, the hold until takes.cutoff or "done", the privacy
    hold, the takes in the site, email and audio. Never fails the edition: on any error it ships as before."""
    from pipeline import takes
    if not takes.tcfg(cfg)["enabled"]:
        return {}
    import os
    try:
        print(takes.send_email(ROOT, cfg, today))
        takes.mark_pending(ROOT, today, os.getpid())
        print(f"Holding the edition for your takes until {takes.tcfg(cfg)['cutoff']} (or a \"done\" reply)...")
        st = takes.wait(ROOT, cfg, today, log=print)
        if st.get("held") or st.get("unknown"):
            print(takes.report_email(ROOT, cfg, today, st))
        print(takes.revoice(ROOT, cfg, today, st, log=print))
        if cfg.get("archive", {}).get("git_commit", True):
            print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"takes {today}: {len(st.get('published', []))} published",
                                                                paths=(takes.DIR, "data/commentary")))
        return st
    except Exception as e:  # noqa: BLE001
        print(f"takes skipped, the edition ships without them: {e}")
        return {}
    finally:
        takes.mark_released(ROOT, today)


def _retry_outbound(cfg: dict, today: str) -> int:
    """A later scheduled run: if today's edition was built but never emailed (the release gate blocked it, say),
    send what was held back once the gate passes. Nothing is sent twice: email and labels skip what is done."""
    from pipeline import mailer, release
    if not (cfg.get("email") or {}).get("enabled") or today in mailer.sent_days(ROOT):
        print("Nothing to do.")
        return 0
    from pipeline import takes
    if takes.waiting(ROOT, today):                # the morning run is holding the edition for Steven's takes
        print(f"Held for your takes until {takes.tcfg(cfg)['cutoff']}: the morning run is waiting; nothing to do.")
        return 0
    try:
        release.require(ROOT, cfg, "held-back publish and email")
    except Exception as e:  # noqa: BLE001
        print(f"Still held back: {e}")
        _notify("News pipeline: approval needed", "Today's edition is built but not sent. ./np release-check approve")
        _gate_alert(cfg, str(e))
        return 0
    if takes.tcfg(cfg)["enabled"] and not takes.state(ROOT, today).get("released_at"):
        _takes_step(cfg, today)                  # the morning run stopped before the takes step finished
        _make_podcast(cfg, today)
    print("Sending what the release gate held back...")
    if cfg.get("publish", {}).get("auto") and not _publish_and_verify(cfg, today):
        print("Email held: the site isn't safely published.")
        return 0
    if cmd_email(cfg, ["send", today]):
        _alert(cfg, "email", detail="See the latest logs/cmd-daily-*.txt for the error.")
    if (cfg.get("email") or {}).get("editor_note", True):
        try:
            from pipeline import editor_note
            r = editor_note.send(ROOT, cfg, today)
            print(f"Editor's note: {r.get('subject') or r.get('skipped') or r.get('error')}")
        except Exception as e:  # noqa: BLE001
            print(f"editor's note skipped: {e}")
    if (cfg.get("email_sources") or {}).get("enabled") and (cfg.get("email_sources") or {}).get("day_labels", True):
        cmd_newsletters(cfg, ["label", today])
    _notify("News pipeline", "Today's edition sent (it had been held back by the release gate).")
    return 0


def cmd_review(cfg: dict, argv: list) -> int:
    """./np review weekly [DAY]: the weekly quality review from local files (docs/reviews/<DAY>-weekly-review.md)"""
    from pipeline import review
    if not argv or argv[0] != "weekly":
        print(cmd_review.__doc__)
        return 1
    day = argv[1] if len(argv) > 1 else dt.date.today().isoformat()
    out = review.run(ROOT, cfg, day)
    if cfg.get("archive", {}).get("git_commit", True):
        print("git:", Archive(ROOT, cfg["paths"]).git_commit(f"weekly quality review {day}",
                                                            paths=(str(out.relative_to(ROOT)),)))
    return 0


def cmd_preflight(cfg: dict) -> int:
    """./np preflight: the evening check: would tomorrow's run be allowed to publish and email? (notifies if not)"""
    from pipeline import release
    ok, why = release.check_approval(ROOT)
    if ok:
        fp, sfp = release.fingerprint(release.CODE, ROOT), release.fingerprint(release.SENSITIVE, ROOT)
        if not release.passed_before(ROOT, fp, sfp):     # test it tonight, not at 05:00 during the run
            print("Preflight: this code hasn't passed the full gate yet; running it now...")
            rec = release.run(ROOT, cfg)
            if not rec["passed"]:
                bad = "; ".join(f"{k}: {v['detail']}" for k, v in rec["checks"].items() if not v["ok"])
                _notify("News pipeline: fix before morning", "The release gate fails tonight: " + bad[:150])
                _alert(cfg, "gate", day=(dt.date.today() + dt.timedelta(days=1)).isoformat(), detail=bad,
                       when="evening")
                return 1
        print("Preflight: approved and tested; tomorrow's run can publish and email without re-testing.")
        return 0
    changed = release.changed_sensitive(ROOT) if hasattr(release, "changed_sensitive") else []
    print("Preflight: APPROVAL NEEDED before tomorrow's run. " + why)
    for f in changed:
        print(f"  changed: {f}")
    _notify("News pipeline: approve before morning",
            "Security-sensitive files changed" + (f" ({', '.join(changed[:3])})" if changed else "")
            + ". Run ./np release-check approve tonight or the briefing won't send.")
    _alert(cfg, "approval-evening", day=(dt.date.today() + dt.timedelta(days=1)).isoformat(), detail=why,
           files=changed, when="evening")
    return 1


def cmd_daily(cfg: dict) -> int:
    """Scheduled entry point: run once per day, skip if today's briefing already came from a good run."""
    import subprocess
    from pipeline.archive import read_jsonl
    today = dt.date.today().isoformat()
    runs = read_jsonl(ROOT / cfg["paths"]["runs"])
    done = [r for r in runs if r.get("day") == today and not r.get("experiment")
            and r["stages"].get("fetch", {}).get("status") in ("ok", "partial")
            and r["stages"].get("write", {}).get("status") == "ok"]
    if done:
        print(f"Today's briefing already produced by run {done[-1]['run_id']}.")
        return _retry_outbound(cfg, today)
    if not wait_for_network(minutes=int((cfg.get("schedule") or {}).get("wait_for_network_minutes", 10))):
        msg = "News run skipped: no network (Mac offline?). The next scheduled retry will try again."
        print(msg)
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "News pipeline"'], capture_output=True)
        return 0
    try:                                         # Steven's clicks on the email queue page, before today's pick
        from pipeline import deepdive
        if (cfg.get("email") or {}).get("queue_page", True):
            deepdive.apply_remote(ROOT, cfg)
    except Exception as e:  # noqa: BLE001
        print(f"deep-dive queue page skipped: {e}")
    code = cmd_run(cfg)
    runs = read_jsonl(ROOT / cfg["paths"]["runs"])
    last = runs[-1] if runs else {}
    w = last.get("stages", {}).get("write", {})
    if w.get("status") == "ok":
        au = last.get("stages", {}).get("audio", {})
        msg = f"Briefing ready: {w.get('items', 0)} items" + (f", {au['minutes']} min audio" if au.get("minutes") else ", no audio")
    else:
        bad = [f"{k}: {v.get('error') or v.get('reason') or v.get('status')}" for k, v in last.get("stages", {}).items()
               if v.get("status") in ("error", "skipped", "partial")]
        msg = "News run problem: " + ("; ".join(bad)[:150] or last.get("status", "unknown"))
        nt = _next_try(cfg)
        _alert(cfg, "run", detail="; ".join(bad)[:800] or str(last.get("status", "unknown")), next_try=nt)
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification "{msg.replace(chr(34), chr(39))}" '
                        f'with title "News pipeline"'], capture_output=True)
    print(msg)
    gate_blocked = False
    try:                                         # release gate: nothing outbound unless this code passed it
        from pipeline import release
        release.require(ROOT, cfg, "today's publish and email")
    except Exception as e:  # noqa: BLE001
        gate_blocked = True
        gate_msg = f"News pipeline: outbound blocked by the release gate. {e}"[:220]
        print(gate_msg)
        if w.get("status") == "ok":
            _gate_alert(cfg, str(e))
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f'display notification "{gate_msg.replace(chr(34), chr(39))}" '
                            f'with title "News pipeline: release gate"'], capture_output=True)
    if w.get("status") == "ok" and (cfg.get("deepdive") or {}).get("enabled"):
        try:                                     # the deep dive planned before the briefing audio: write and voice it now
            print("Deep dive...")
            from pipeline import deepdive
            if (deepdive.latest(ROOT, today) or {}).get("status") == "written":
                deepdive.voice(ROOT, cfg, today)        # written + checked before the briefing audio; record it
        except Exception as e:  # noqa: BLE001
            print(f"deep dive skipped: {e}")
    if w.get("status") == "ok" and not gate_blocked:
        _takes_step(cfg, today)                  # Steven's takes: email him, hold until the cutoff, splice them in
    if w.get("status") == "ok" and (cfg.get("deepdive") or {}).get("enabled"):
        _make_podcast(cfg, today)
    published = True
    if w.get("status") == "ok" and cfg.get("publish", {}).get("auto"):
        published = _publish_and_verify(cfg, today, alert=not gate_blocked)
    if w.get("status") == "ok" and (cfg.get("email") or {}).get("enabled") and not published:
        print("Email held: the site isn't safely published (it goes out once a publish passes).")
    elif w.get("status") == "ok" and (cfg.get("email") or {}).get("enabled"):
        print("Emailing subscribers...")
        if cmd_email(cfg, ["send", today]) and not gate_blocked:
            _alert(cfg, "email", detail="See logs/last-command.txt for the error.", next_try=_next_try(cfg))
    try:
        from pipeline import record
        if record.search_due(ROOT, cfg):
            print("Weekly public-record search...")
            cmd_record(cfg, ["search"])
    except Exception as e:  # noqa: BLE001
        print(f"public-record search skipped: {e}")
    try:                                         # company watchlist: today's mentions + news search; weekly web search
        from pipeline import watchlist as wl
        if wl.load(ROOT):
            cmd_watchlist(cfg, ["fetch"])
            if wl.weekly_due(ROOT):
                cmd_watchlist(cfg, ["weekly"])
    except Exception as e:  # noqa: BLE001
        print(f"watchlist skipped: {e}")
    if (cfg.get("email") or {}).get("enabled") and (cfg.get("email") or {}).get("editor_note", True):
        try:                                     # Steven only: tomorrow's deep dive, suggestions, watchlist
            from pipeline import editor_note
            r = editor_note.send(ROOT, cfg, today)
            print(f"Editor's note: {r.get('subject') or r.get('skipped') or r.get('error')}")
        except Exception as e:  # noqa: BLE001
            print(f"editor's note skipped: {e}")
    try:
        from pipeline import quality
        try:                                     # yesterday's stars arrive after its scorecard: rescore the week
            n = quality.pull_stars(ROOT, cfg)
            if n:
                for d in sorted(f.stem for f in (ROOT / cfg["paths"]["briefings"]).glob("????-??-??.md"))[-8:-1]:
                    quality.score_day(ROOT, cfg, d)
                print(f"Ratings: {n} star rating(s) pulled")
        except Exception as e:  # noqa: BLE001
            print(f"star ratings skipped: {e}")
        q = quality.score_day(ROOT, cfg, today)
        if q:
            print(f"Quality: {q['passed']}/{q['total']} checks · privacy {q['values']['privacy']}")
    except Exception as e:  # noqa: BLE001
        print(f"quality scorecard skipped: {e}")
    if w.get("status") == "ok" and (cfg.get("email_sources") or {}).get("enabled") \
            and (cfg.get("email_sources") or {}).get("day_labels", True):
        cmd_newsletters(cfg, ["label", today])          # Gmail: which source emails fed today's briefing
    try:                                         # Fridays: the weekly quality review, on this Mac, from local files
        from pipeline import review
        if review.due(ROOT, cfg, today):
            cmd_review(cfg, ["weekly", today])
    except Exception as e:  # noqa: BLE001
        print(f"weekly review skipped: {e}")
    if (cfg.get("feedback") or {}).get("enabled", True) and (cfg.get("email_sources") or {}).get("enabled"):
        try:                                   # readers' replies to the email: collect + triage every day
            if cmd_feedback(cfg, ["fetch"]) == 0:
                cmd_feedback(cfg, ["triage"])
        except Exception as e:  # noqa: BLE001
            print(f"feedback skipped: {e}")
    try:
        from pipeline import xdigest
        if (cfg.get("x") or {}).get("enabled") and xdigest.due(ROOT):
            print("Weekly X digest (Claude web search)...")
            cmd_x(cfg, ["digest"])
    except Exception as e:  # noqa: BLE001
        print(f"X digest skipped: {e}")
    return code


def cmd_service(cfg: dict, sub: str, kind: str = "") -> int:
    """./np service install|remove|status|restart|run|pause|resume [daily|dashboard|preflight]  (+ ollama restart)."""
    from pipeline import service
    kinds = [kind] if kind in service.LABELS else list(service.LABELS)
    if sub == "status":
        s = service.all_status(ROOT, cfg)
        for k in service.LABELS:
            v = s[k]
            state = v.get("state", "loaded" if v["loaded"] else ("installed, not loaded" if v["installed"] else "not installed"))
            extra = f" · times {', '.join(v['times'])}" if v.get("times") else ""
            extra += f" · last exit {v['last_exit']}" if v.get("last_exit") else ""
            print(f"  {k:9} {state}{extra}")
        o = s["ollama"]
        print(f"  ollama    {'up' if o['reachable'] else 'DOWN'} at {o['url']} · models: {', '.join(o['models']) or '-'}")
        c = s["claude"]
        print(f"  claude    {c.get('version', 'not installed')}")
        return 0
    if kind == "ollama" and sub == "restart":
        print(service.restart_ollama())
        return 0
    actions = {"install": lambda k: service.install(k, ROOT, cfg), "remove": service.remove,
               "pause": service.pause, "resume": service.resume,
               "restart": lambda k: service.kick(k, kill=True), "run": lambda k: service.kick(k)}
    if sub not in actions:
        print(f"unknown: {sub}. Use install | remove | status | restart | run | pause | resume")
        return 1
    if sub == "run":
        kinds = [kind or "daily"]
    if sub == "install":
        home = Path.home()
        protected = [home / d for d in ("Documents", "Desktop", "Downloads")] + [home / "Library" / "Mobile Documents"]
        if any(ROOT == d or d in ROOT.parents for d in protected):
            print(f"WARNING: {ROOT} is inside a macOS-protected folder. Background jobs (launchd) are blocked there\n"
                  "         ('Operation not permitted') unless /bin/bash has Full Disk Access.\n"
                  "         Recommended: move the project, e.g. mkdir -p ~/Developer && mv ~/Documents/news-pipeline ~/Developer/,\n"
                  "         then ./np setup --rebuild and ./np service install. See docs/OPERATIONS.md.")
    for k in kinds:
        print(actions[sub](k))
    return 0


def cmd_backup(cfg: dict, sub: str = "push") -> int:
    from pipeline import publish
    repo = cfg.get("archive", {}).get("remote_repo", "")
    if not repo:
        print("Set archive.remote_repo in config.yaml (a PRIVATE repo, e.g. sgwoods/news-pipeline).")
        return 1
    try:
        print(publish.backup_setup(ROOT, repo) if sub == "setup" else publish.backup_push(ROOT))
    except RuntimeError as e:
        print(f"Backup failed: {e}")
        return 1
    return 0


def cmd_site(cfg: dict) -> int:
    from pipeline import site
    pc = cfg.get("publish", {})
    res = site.build(ROOT, cfg, base_url=pc.get("site_url", ""), audio_days=pc.get("audio_days", 14))
    print(f"Built {res['out']}: {res['days']} briefings, {res['audio']} MP3s. Preview: open site/index.html")
    return 0


def cmd_publish(cfg: dict, sub: str = "run") -> int:
    from pipeline import publish, site
    pc = cfg.get("publish", {})
    repo = pc.get("repo", "")
    if not repo:
        print("Set publish.repo in config.yaml (e.g. sgwoods/ai-briefing).")
        return 1
    try:
        if sub == "setup":
            print(publish.setup(ROOT, repo))
        if sub == "restore":                     # put the previous live site back
            print(publish.restore(ROOT, cfg))
            return 0
        res = site.build(ROOT, cfg, base_url=pc.get("site_url", ""), audio_days=pc.get("audio_days", 30))
        url = publish.push(ROOT, ROOT / "site", repo, f"Publish {dt.datetime.now():%Y-%m-%d %H:%M}", cfg)
        try:                                     # after a publication: the public hub's status (pipeline/hub.py)
            from pipeline import hub
            hub.push(ROOT, cfg)
        except Exception as e:  # noqa: BLE001 - the hub status never blocks a publish
            print(f"hub export skipped: {e}"[:400])
        from pipeline import episodes as eps
        eps.mark_published(ROOT, res.get("episode_keys") or [])
    except RuntimeError as e:
        print(f"Publish failed: {e}")
        return 1
    print(f"Published {res['days']} briefings ({res['audio']} MP3s) to {repo}.\nSite: {url}  "
          "(first publish: Pages can take a minute or two)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify-sources", action="store_true",
                    help="resolve + verify feeds, write sources.yaml and a report in logs/")
    ap.add_argument("--lookback-hours", type=int, default=None,
                    help="override fetch window (e.g. 168 to back-fill a week)")
    ap.add_argument("--no-commit", action="store_true", help="don't git-commit the archive")
    ap.add_argument("--no-llm", action="store_true", help="fetch + archive only")
    ap.add_argument("--stages-only", action="store_true", help="skip fetch; run LLM stages on pending items")
    ap.add_argument("--reprocess", metavar="YYYY-MM-DD", help="re-run LLM stages for items first seen that day "
                    "(appends new versions; nothing is overwritten)")
    ap.add_argument("--correct", metavar="NOTE", help="with --rebrief/--reprocess/--remaster on a shipped day: what the "
                                                    "correction changes (shown on the page)")
    ap.add_argument("--rebrief", metavar="YYYY-MM-DD", help="rebuild only the briefing for a day (cluster, merge, "
                    "editorial, write) from existing analyses; fast, for tuning")
    ap.add_argument("--limit", type=int, help="process at most N items (for testing)")
    ap.add_argument("--force", action="store_true", help="with --verify-sources: overwrite even if far fewer feeds verify")
    ap.add_argument("--dashboard", action="store_true", help="start the local dashboard (127.0.0.1)")
    ap.add_argument("--service", nargs="+", metavar="ARG", help="install|remove|status|restart|run|pause|resume [daily|dashboard|ollama]")
    ap.add_argument("--backup", nargs="?", const="push", choices=["push", "setup"], help="push this repo to its private GitHub remote")
    ap.add_argument("--site", action="store_true", help="build the static public site into site/")
    ap.add_argument("--publish", nargs="?", const="run", choices=["run", "setup", "restore"],
                    help="build + push the site to the public GitHub repo (setup: create the repo first)")
    ap.add_argument("--audio", nargs="?", const="", metavar="YYYY-MM-DD", help="(re)build only the spoken MP3 for a day")
    ap.add_argument("--script-preview", nargs="*", metavar="ARG", help="DAY [tts]: write DAY's audio script (and MP3) "
                    "to briefings/experiments/DAY/ without touching the real episode")
    ap.add_argument("--say", metavar="TEXT", help="hear TEXT with the pronunciation table")
    ap.add_argument("--release-check", nargs="*", metavar="ARG", help='[live] | approve "note" | install-hooks')
    ap.add_argument("--secrets", nargs="*", metavar="ARG", help="status | migrate (Keychain)")
    ap.add_argument("--note", nargs="*", metavar="ARG", help="preview | send [DAY]: Steven's private evening note")
    ap.add_argument("--watchlist", nargs="*", metavar="ARG", help="list | fetch | weekly | backfill [DAYS] | add NAME | remove NAME | test")
    ap.add_argument("--deepdive", nargs="*", metavar="ARG", help='[DAY] [--topic "..."] [--force] [--no-audio]: topical deep-dive episode')
    ap.add_argument("--review", nargs="*", metavar="ARG", help="weekly [DAY]: the weekly quality review")
    ap.add_argument("--due", metavar="KIND", help="daily|preflight: exit 0 if a scheduled time just passed (local clock)")
    ap.add_argument("--preflight", action="store_true", help="evening check: is the release gate approval current?")
    ap.add_argument("--runner", nargs="*", metavar="ARG", help="status | tick | approve ID | reject ID | install | remove")
    ap.add_argument("--critic", nargs="*", metavar="ARG", help="preview | email | list [DATE]: the weekly critic")
    ap.add_argument("--takes", nargs="*", metavar="ARG", help="status | email | preview | done [DAY]: Steven's takes")
    ap.add_argument("--consistency", nargs="*", metavar="ARG", help="[DAY|all]: first-lines and cross-day checks, dry run")
    ap.add_argument("--hub", nargs="*", metavar="ARG", help="status | push: status on the public project hub")
    ap.add_argument("--dev", nargs="*", metavar="ARG", help="setup: create the development checkout")
    ap.add_argument("--staging", nargs="*", metavar="ARG", help="sync | run [DAY] [--email] | reset | status (dev checkout)")
    ap.add_argument("--release", nargs="*", metavar="ARG", help='VERSION "reviewed: ...": promote dev to production')
    ap.add_argument("--rollback", nargs="*", metavar="ARG", help='"reviewed: ...": back to the previous release')
    ap.add_argument("--correct-day", nargs="*", metavar="ARG", help='DAY "what changed": record a hand edit to a shipped edition')
    ap.add_argument("--remaster", metavar="DAY", help="rebuild DAY's podcast in the current style and publish")
    ap.add_argument("--factcheck", nargs="*", metavar="ARG", help="[DAY] | probe SENTENCE FIGURE: fact-check dry run")
    ap.add_argument("--reader", nargs="*", metavar="ARG", help="check [DAYS]: try the article reader on past items")
    ap.add_argument("--quality", nargs="*", metavar="ARG", help="[DAY|all] | rate DAY SCORE: daily quality scorecard")
    ap.add_argument("--profiles", nargs="*", metavar="DAYS", help="sites/sources with no profile in source_profiles.yaml")
    ap.add_argument("--relink", metavar="YYYY-MM-DD", help="fix links + labels in an existing briefing (no model, no audio)")
    ap.add_argument("--feedback", nargs="*", metavar="ARG", help="list | fetch [DAYS] | triage | set ID STATUS | todo ID")
    ap.add_argument("--linkedin", nargs="*", metavar="ARG", help="import [PATH] | list [N]  (Steven's LinkedIn export)")
    ap.add_argument("--slack", nargs="*", metavar="ARG", help="test | fetch [HOURS]  (links Steven shares in Slack)")
    ap.add_argument("--profile", metavar="NAME", help="use this tuning profile instead of the active one")
    ap.add_argument("--preview", metavar="YYYY-MM-DD", help="rebuild DAY's briefing + audio with --profile into "
                    "briefings/experiments/DAY/ (the real briefing is untouched)")
    ap.add_argument("--x", nargs="*", metavar="ARG", help="status | fetch [HOURS]  (X accounts via Nitter mirrors)")
    ap.add_argument("--todo", nargs="*", metavar="ARG", help="list | seed | done ID | reopen ID | add TITLE [GROUP]")
    ap.add_argument("--bluesky", nargs="*", metavar="ARG", help="status | fetch [HOURS]  (Bluesky lists + own posts)")
    ap.add_argument("--newsletters", nargs="*", metavar="ARG", help="status | test | fetch [DAYS]  (Gmail label as a source)")
    ap.add_argument("--email", nargs="*", metavar="ARG", help="status | list | add EMAIL | remove EMAIL | test [EMAIL] [DAY] | send [DAY]")
    ap.add_argument("--rebuild-history", nargs="*", metavar="DAY", help="rebuild every briefing + audio with the current "
                    "profile (optionally FROM [TO]); older versions are kept")
    ap.add_argument("--record", nargs="*", metavar="ARG", help="public record: list | search | words | apply-words | accept ID | deny ID | export")
    ap.add_argument("--dive", nargs=2, metavar=("DAY", "STORY"), help="deep dive on one story of a briefing")
    ap.add_argument("--sources", nargs="*", metavar="ARG",
                    help="list | suggest [N] | find NAME [NOTE] | accept ID | deny ID | remove URL | ...")
    ap.add_argument("--voices", action="store_true", help="make a sample clip in each candidate voice")
    ap.add_argument("--daily", action="store_true", help="scheduled run: once per day, then notify")
    ap.add_argument("--doctor", action="store_true", help="check environment, packages, LLM, sources, git")
    ap.add_argument("--report", action="store_true", help="write + print logs/last-report.md")
    ap.add_argument("--cmd", default="", help=argparse.SUPPRESS)
    ap.add_argument("--exit-code", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--output-file", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()
    cfg = load_config(args.profile)
    if args.report:
        from pipeline import report
        out = report.write(ROOT, cfg, cmd=args.cmd, exit_code=args.exit_code, output_file=args.output_file)
        print("\n===== REPORT (also saved to " + str(out.relative_to(ROOT)) + ") =====")
        print(out.read_text("utf-8"), end="")
        print("===== END REPORT =====")
        return 0
    if args.doctor:
        return cmd_doctor(cfg)
    if args.due:                                 # ./np scheduled: quiet, fast; launchd ticks every half hour
        from pipeline.schedule import due
        return 0 if due(cfg, args.due) else 1
    if args.daily:
        return cmd_daily(cfg)
    if args.audio is not None:
        return cmd_audio(cfg, args.audio or None)
    if args.script_preview is not None:
        return cmd_script_preview(cfg, args.script_preview)
    if args.say:
        return cmd_say(cfg, args.say)
    if args.slack is not None:
        return cmd_slack(cfg, args.slack)
    if args.release_check is not None:
        return cmd_release_check(cfg, args.release_check)
    if args.secrets is not None:
        return cmd_secrets(cfg, args.secrets)
    if args.note is not None:
        return cmd_note(cfg, args.note)
    if args.watchlist is not None:
        return cmd_watchlist(cfg, args.watchlist)
    if args.deepdive is not None:
        return cmd_deepdive(cfg, args.deepdive)
    if args.quality is not None:
        return cmd_quality(cfg, args.quality)
    if args.consistency is not None:
        return cmd_consistency(cfg, args.consistency)
    if args.takes is not None:
        return cmd_takes(cfg, args.takes)
    if args.critic is not None:
        return cmd_critic(cfg, args.critic)
    if args.runner is not None:
        return cmd_runner(cfg, args.runner)
    if args.preflight:
        return cmd_preflight(cfg)
    if args.review is not None:
        return cmd_review(cfg, args.review)
    if args.hub is not None:
        return cmd_hub(cfg, args.hub)
    if args.dev is not None:
        return cmd_dev(cfg, args.dev)
    if args.staging is not None:
        return cmd_staging(cfg, args.staging)
    if args.release is not None:
        return cmd_release(cfg, args.release)
    if args.rollback is not None:
        return cmd_release(cfg, args.rollback, rollback=True)
    if args.correct_day is not None:
        return cmd_correct(cfg, args.correct_day)
    changed_day = args.remaster or args.rebrief or args.reprocess
    if changed_day:                              # a shipped edition changes only as a visible correction
        from pipeline import env, shipped
        if not env.staging(ROOT) and shipped.is_shipped(ROOT, changed_day):
            if not (args.correct or "").strip():
                print(f"{changed_day} has shipped (its email went out). Change it only as a correction, shown on the "
                      f"page:\n  add --correct \"what this changes\"")
                return 1
            before = shipped._sha(ROOT / "briefings" / f"{changed_day}.md")
            code = cmd_remaster(cfg, args.remaster) if args.remaster else cmd_run(
                cfg, args.lookback_hours, commit=not args.no_commit, reprocess_day=args.reprocess,
                rebrief_day=args.rebrief)
            if code == 0:
                print("correction recorded:", shipped.correct(ROOT, changed_day, args.correct, before)["note"])
            return code
    if args.remaster:
        return cmd_remaster(cfg, args.remaster)
    if args.factcheck is not None:
        return cmd_factcheck(cfg, args.factcheck)
    if args.reader is not None:
        return cmd_reader(cfg, args.reader or ["check"])
    if args.profiles is not None:
        return cmd_profiles(cfg, args.profiles)
    if args.relink:
        return cmd_relink(cfg, args.relink)
    if args.feedback is not None:
        return cmd_feedback(cfg, args.feedback)
    if args.linkedin is not None:
        return cmd_linkedin(cfg, args.linkedin)
    if args.voices:
        return cmd_voices(cfg)
    if args.sources is not None:
        return cmd_sources(cfg, args.sources)
    if args.service:
        return cmd_service(cfg, args.service[0], args.service[1] if len(args.service) > 1 else "")
    if args.backup:
        return cmd_backup(cfg, args.backup)
    if args.site:
        return cmd_site(cfg)
    if args.publish:
        return cmd_publish(cfg, args.publish)
    if args.dashboard:
        from dashboard.app import main as dash
        dash(port=int(cfg.get("dashboard", {}).get("port", 8765)))
        return 0
    if args.verify_sources:
        return cmd_verify_sources(cfg, args.force)
    if args.preview:
        from pipeline import tuning
        name = args.profile or tuning.active_name(cfg)
        return cmd_run(cfg, rebrief_day=args.preview, experiment=name)
    if args.dive:
        return cmd_dive(cfg, *args.dive)
    if args.email is not None:
        return cmd_email(cfg, (args.email) + (["--force"] if args.force else []))
    if args.newsletters is not None:
        return cmd_newsletters(cfg, args.newsletters)
    if args.bluesky is not None:
        return cmd_bluesky(cfg, args.bluesky)
    if args.x is not None:
        return cmd_x(cfg, args.x)
    if args.todo is not None:
        return cmd_todo(cfg, args.todo)
    if args.rebuild_history is not None:
        return cmd_rebuild_history(cfg, *(args.rebuild_history[:2]))
    if args.record is not None:
        return cmd_record(cfg, args.record)
    return cmd_run(cfg, args.lookback_hours, commit=not args.no_commit, no_llm=args.no_llm,
                   stages_only=args.stages_only, reprocess_day=args.reprocess, limit=args.limit,
                   rebrief_day=args.rebrief)


if __name__ == "__main__":
    sys.exit(main())
