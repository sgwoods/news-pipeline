"""Builder dashboard: a local, read-mostly view of the pipeline and its archive.

Run:  python run.py --dashboard      (http://127.0.0.1:8765)

- Binds to 127.0.0.1 only.
- Never modifies data/, briefings/ or perspective.md. The only writes happen through the
  action buttons, which run the same commands you would type (python run.py ...).
- Fetched content is rendered as escaped text, never as HTML.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.archive import read_jsonl  # noqa: E402
from dashboard import notes as notesmod  # noqa: E402

PAGE_SIZE = 50
ACTIONS = {
    "run": [sys.executable, "run.py"],
    "verify": [sys.executable, "run.py", "--verify-sources"],
    "stages": [sys.executable, "run.py", "--stages-only"],
    "reprocess": [sys.executable, "run.py", "--reprocess"],   # + day (validated)
    "rebrief": [sys.executable, "run.py", "--rebrief"],       # + day
    "audio": [sys.executable, "run.py", "--audio"],           # + day
    "voices": [sys.executable, "run.py", "--voices"],
    "publish": [sys.executable, "run.py", "--publish"],
    "backup": [sys.executable, "run.py", "--backup"],
    "doctor": [sys.executable, "run.py", "--doctor"],
    "service-install": [sys.executable, "run.py", "--service", "install"],
    "run-daily-job": [sys.executable, "run.py", "--service", "run", "daily"],
    "pause-daily": [sys.executable, "run.py", "--service", "pause", "daily"],
    "resume-daily": [sys.executable, "run.py", "--service", "resume", "daily"],
    "restart-ollama": [sys.executable, "run.py", "--service", "restart", "ollama"],
    "suggest": [sys.executable, "run.py", "--sources", "suggest"],
    "find-source": [sys.executable, "run.py", "--sources", "find"],         # + name [note]
    "recheck-source": [sys.executable, "run.py", "--sources", "recheck"],   # + id
    "preview": [sys.executable, "run.py", "--preview"],                     # + day --profile name
    "dive": [sys.executable, "run.py", "--dive"],                           # + day key
    "record-search": [sys.executable, "run.py", "--record", "search"],
    "record-words": [sys.executable, "run.py", "--record", "words"],
    "rebuild-history": [sys.executable, "run.py", "--rebuild-history"],
    "email-test": [sys.executable, "run.py", "--email", "test"],           # + day
    "email-send": [sys.executable, "run.py", "--email", "send"],           # + day
}
SID_RE = __import__("re").compile(r"^[0-9a-f]{8}$")
DAY_ACTIONS = {"reprocess", "rebrief", "audio", "email-test", "email-send"}
DAY_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def render_markdown_safely(text: str):
    """Briefings are derived from fetched content, so: no raw HTML, only http(s)/relative links."""
    try:
        import markdown
    except ImportError:
        return None
    import re
    html = markdown.markdown(text.replace("&", "&amp;").replace("<", "&lt;"), extensions=["tables"])
    html = re.sub(r'href="(?!https?://|/|#)[^"]*"', 'href="#"', html)
    html = re.sub(r'src="[^"]*"', 'src=""', html)
    return html


def create_app(root: Path = ROOT) -> Flask:
    app = Flask(__name__)
    cfg = yaml.safe_load((root / "config.yaml").read_text("utf-8")) or {}
    paths = cfg.get("paths", {})
    P = {
        "index": root / paths.get("index", "data/index.jsonl"),
        "runs": root / paths.get("runs", "data/runs.jsonl"),
        "current": root / paths.get("run_current", "data/run_current.json"),
        "raw": root / paths.get("raw", "data/raw"),
        "sources": root / paths.get("sources", "sources.yaml"),
        "logs": root / paths.get("logs", "logs"),
        "briefings": root / paths.get("briefings", "briefings"),
        "summaries": root / paths.get("summaries", "data/summaries"),
    }
    app.config["CSRF"] = secrets.token_urlsafe(16)

    @app.before_request
    def localhost_only():
        """DNS-rebinding guard: a web page can point its own hostname at 127.0.0.1, but it cannot fake the Host
        header, so only requests addressed to localhost are served."""
        host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            abort(403)
    state = {"proc": None, "action": None, "started": None, "log": None}

    # ---------- data helpers (all read-only) ----------
    def runs():
        return list(reversed(read_jsonl(P["runs"])))

    def current():
        try:
            return json.loads(P["current"].read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def index():
        return read_jsonl(P["index"])

    def sources():
        if not P["sources"].exists():
            return {}, []
        d = yaml.safe_load(P["sources"].read_text("utf-8")) or {}
        return d, d.get("sources") or []

    def raw_items(day: str):
        return read_jsonl(P["raw"] / day / "items.jsonl")

    def find_item(item_id: str):
        for row in index():
            if row.get("id") == item_id:
                for it in read_jsonl(root / row["raw"]):
                    if it.get("id") == item_id:
                        return it, row
                return None, row
        return None, None

    def latest_summaries():
        out = {}
        if P["summaries"].exists():
            for f in sorted(P["summaries"].glob("*.jsonl")):
                for s in read_jsonl(f):
                    out[s.get("id")] = s
        return out

    def summaries_for(item_id: str):
        out = []
        if P["summaries"].exists():
            for f in sorted(P["summaries"].glob("*.jsonl")):
                out += [s for s in read_jsonl(f) if s.get("id") == item_id]
        return out

    def briefings_list():
        if not P["briefings"].exists():
            return []
        return sorted((f.stem for f in P["briefings"].glob("*.md") if DAY_RE.match(f.stem)), reverse=True)

    def action_status():
        p = state["proc"]
        if p is None:
            return None
        code = p.poll()
        return {"action": state["action"], "started": state["started"], "log": state["log"],
                "running": code is None, "exit_code": code}

    def git_head():
        try:
            r = subprocess.run(["git", "log", "-1", "--format=%h %cd %s", "--date=format:%Y-%m-%d %H:%M"],
                               cwd=root, capture_output=True, text=True, timeout=5)
            return r.stdout.strip()
        except Exception:
            return ""

    def _version():
        from pipeline.version import full
        return full(root)

    @app.context_processor
    def inject():
        try:
            from pipeline import feedback as fb
            fbc = fb.counts(root)
        except Exception:  # noqa: BLE001
            fbc = {}
        return {"csrf": app.config["CSRF"], "now": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "action": action_status(), "fb_counts": fbc, "version": _version()}

    @app.template_filter("safe_href")
    def safe_href(u):
        return u if isinstance(u, str) and u.startswith(("http://", "https://")) else "#"

    @app.template_filter("short")
    def short(s, n=90):
        s = (s or "").replace("\n", " ")
        return s if len(s) <= n else s[: n - 1] + "…"

    # ---------- pages ----------
    @app.route("/")
    def status():
        all_runs = runs()
        idx = index()
        per_day = Counter(r.get("first_seen", "") for r in idx)
        days = sorted(per_day)[-14:]
        per_person = Counter(r.get("person", "") for r in idx)
        last = all_runs[0] if all_runs else None
        failing = []
        if last:
            failing = [s for s in last["stages"].get("fetch", {}).get("per_source", [])
                       if s.get("status") != "ok"]
        cur = current()
        live = cur if cur and cur.get("status") == "running" else None
        return render_template("status.html", last=last, live=live, runs=all_runs[:5],
                               total=len(idx), per_day=[(d, per_day[d]) for d in days],
                               max_day=max(per_day.values()) if per_day else 1,
                               per_person=per_person.most_common(), failing=failing,
                               git=git_head(), n_sources=len(sources()[1]),
                               briefings=briefings_list()[:5])

    @app.route("/partials/live")
    def live_partial():
        cur = current()
        return render_template("_live.html", live=cur if cur and cur.get("status") == "running" else None)

    @app.route("/sources")
    def sources_page():
        meta, rows = sources()
        idx = index()
        counts, latest = Counter(), {}
        for r in idx:
            key = (r.get("person"), r.get("source_kind"))
            counts[key] += 1
            latest[key] = max(latest.get(key, ""), r.get("published", "") or r.get("first_seen", ""))
        last_status = {}
        for run in reversed(runs()):  # oldest → newest so newest wins
            for s in run["stages"].get("fetch", {}).get("per_source", []):
                last_status[(s["person"], s["url"])] = {**s, "run_id": run["run_id"]}
        enriched = []
        for s in rows:
            st = last_status.get((s["person"], s["url"]), {})
            k = (s["person"], s["kind"])
            enriched.append({**s, "last": st, "archived": counts.get(k, 0),
                             "newest": (latest.get(k) or "")[:10]})
        reports = sorted(P["logs"].glob("source-verification-*.md"), reverse=True) if P["logs"].exists() else []
        report = reports[0].read_text("utf-8") if reports else ""
        failed_section = report.split("## Failed", 1)[1] if "## Failed" in report else ""
        from pipeline import suggest
        q = suggest.summary(suggest.load_store(root))
        managed = suggest.load_managed(root)
        added = set(managed["people"])
        for e in enriched:
            e["added"] = e["person"] in added
        days = suggest.stale_days(cfg)
        for x in q["pending"]:
            for v in x.get("verified") or []:
                v["stale"] = suggest.is_stale(v, days)
        from pipeline import mailsource
        live = yaml.safe_load((root / "config.yaml").read_text("utf-8")) or {}
        news = mailsource.status(root, live)
        from pipeline import xsource
        xs = xsource.status(root)
        bl = (live.get("bluesky") or {})
        bl_counts = Counter(r.get("person") for r in idx if r.get("source_kind") == "bluesky" and r.get("person") not in {s["person"] for s in rows})
        return render_template("sources.html", rows=enriched, verified_at=meta.get("verified_at", ""),
                               q=q, removed=managed["removed"], news=news, bluesky=bl, bl_counts=bl_counts, xs=xs,
                               last_status=last_status, busy_suggest=bool((action_status() or {}).get("running")),
                               report_name=reports[0].name if reports else "",
                               failed_section=("## Failed" + failed_section) if failed_section else "")

    @app.route("/items")
    def items_page():
        q = (request.args.get("q") or "").strip().lower()
        person = request.args.get("person") or ""
        kind = request.args.get("kind") or ""
        tag = request.args.get("tag") or ""
        day = request.args.get("day") or ""
        page = max(1, int(request.args.get("page", 1) or 1))
        idx = index()
        people = sorted({r.get("person", "") for r in idx})
        kinds = sorted({r.get("source_kind", "") for r in idx})
        days = sorted({r.get("first_seen", "") for r in idx}, reverse=True)
        summ = latest_summaries()

        def tag_of(r):
            s = summ.get(r["id"])
            if not s:
                return "pending"
            return s.get("tag", "") if s.get("keep") else "filtered out"
        rows = [r for r in idx if (not tag or tag_of(r) == tag)
                and (not person or r.get("person") == person)
                and (not kind or r.get("source_kind") == kind)
                and (not day or r.get("first_seen") == day)]
        if q:  # full-text search over raw files for the candidate rows' days
            texts = {}
            for d in {r.get("first_seen") for r in rows}:
                for it in raw_items(d):
                    texts[it["id"]] = (it.get("title", "") + " " + it.get("text", "")).lower()
            rows = [r for r in rows if q in texts.get(r["id"], r.get("title", "").lower())]
        rows.sort(key=lambda r: (r.get("published") or r.get("first_seen") or ""), reverse=True)
        total = len(rows)
        rows = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        for r in rows:
            s = summ.get(r["id"]) or {}
            r.update({"_tag": tag_of(r), "_imp": s.get("importance"), "_verdict": (s.get("critique_detail") or {}).get("verdict")})
        return render_template("items.html", rows=rows, total=total, page=page, tag=tag,
                               tags=["FULL READ", "SUMMARY ONLY", "filtered out", "pending"],
                               pages=(total + PAGE_SIZE - 1) // PAGE_SIZE, q=q, person=person,
                               kind=kind, day=day, people=people, kinds=kinds, days=days)

    @app.route("/items/<item_id>")
    def item_page(item_id):
        it, row = find_item(item_id)
        if not row:
            abort(404)
        used_in = [b for b in briefings_list()
                   if item_id in (P["briefings"] / f"{b}.md").read_text("utf-8")
                   or (it and it.get("url", "") in (P["briefings"] / f"{b}.md").read_text("utf-8"))]
        return render_template("item.html", it=it, row=row, summaries=summaries_for(item_id),
                               used_in=used_in)

    @app.route("/runs")
    def runs_page():
        return render_template("runs.html", runs=runs())

    @app.route("/runs/<run_id>")
    def run_page(run_id):
        run = next((r for r in runs() if r["run_id"] == run_id), None)
        cur = current()
        if run is None and cur and cur.get("run_id") == run_id:
            run = cur
        if run is None:
            abort(404)
        log_path = root / run.get("log", "")
        log = log_path.read_text("utf-8", errors="replace") if log_path.is_file() else "(log file not found — logs/ is not committed)"
        return render_template("run.html", run=run, log=log)

    def briefing_meta():
        """day -> {latest log row, all versions, audio/script flags, top-of-mind preview}."""
        log = read_jsonl(root / paths.get("briefings_log", "data/briefings.jsonl"))
        out = {}
        for day in briefings_list():
            rows = [b for b in log if b.get("day") == day]
            md = (P["briefings"] / f"{day}.md").read_text("utf-8")
            tom = md.split("## Top of mind", 1)[1].split("\n## ", 1)[0] if "## Top of mind" in md else ""
            bullets = [__import__("re").sub(r"\s*\[\d+\]\(https?://[^)]+\)", "", ln[2:]).strip()
                       for ln in tom.splitlines() if ln.startswith("- ")]
            versions = sorted((P["briefings"] / "versions").glob(f"{day}-*.md"), reverse=True) \
                if (P["briefings"] / "versions").exists() else []
            out[day] = {"day": day, "latest": rows[-1] if rows else {}, "n_versions": len(versions),
                        "versions": [v.stem[len(day) + 1:] for v in versions],
                        "items": len(rows[-1].get("item_ids", [])) if rows else md.count("\n### "),
                        "audio": (P["briefings"] / f"{day}.mp3").is_file(),
                        "script": (P["briefings"] / f"{day}.script.md").is_file(),
                        "bullets": bullets}
        return out

    @app.route("/briefings")
    def briefings_page():
        from pipeline import episodes, tuning
        meta = briefing_meta()
        hidden = episodes.hidden_days(root)
        rows = [{**meta[d], "hidden": d in hidden} for d in sorted(meta, reverse=True)]
        live = yaml.safe_load((root / "config.yaml").read_text("utf-8")) or {}
        msg = request.args.get("msg", "")
        return render_template("briefings.html", rows=rows, msg=msg, profile=tuning.active_name(live),
                               publish_btn=bool(msg) and not (live.get("publish") or {}).get("auto"))

    @app.route("/api/episodes/<day>/<op>", methods=["POST"])
    def episode_op(day, op):
        _check_post()
        from pipeline import episodes
        from pipeline.archive import Archive
        if not DAY_RE.match(day) or op not in ("hide", "show", "delete-audio"):
            abort(404)
        live = yaml.safe_load((root / "config.yaml").read_text("utf-8")) or {}
        if op == "delete-audio":
            gone = episodes.delete_audio(root, live, day, icloud=bool(request.form.get("icloud")))
            msg = f"Deleted {', '.join(gone) or 'nothing'}. Rebuild with ./np audio {day}."
        else:
            episodes.set_hidden(root, day, op == "hide")
            Archive(root, paths).git_commit(f"episodes: {op} {day} on the public site", paths=("data/episodes.json",))
            msg = f"{day} is now {'hidden from' if op == 'hide' else 'shown on'} the public site and podcast feed."
        if (live.get("publish") or {}).get("auto") and not (action_status() or {}).get("running"):
            P["logs"].mkdir(exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
            log = P["logs"] / f"action-publish-{stamp}.log"
            state.update(proc=subprocess.Popen(list(ACTIONS["publish"]), cwd=root, stdout=log.open("w", encoding="utf-8"),
                                               stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"}),
                         action="publish", started=stamp, log=str(log.relative_to(root)))
            msg += " Publishing now."
        return redirect(url_for("briefings_page", msg=msg))

    @app.route("/briefings/latest")
    def briefing_latest():
        days = briefings_list()
        return redirect(url_for("briefing_page", day=days[0])) if days else redirect(url_for("briefings_page"))

    @app.route("/briefings/<day>")
    def briefing_page(day):
        if not DAY_RE.match(day):
            abort(404)
        f = P["briefings"] / f"{day}.md"
        if not f.is_file():
            abort(404)
        meta = briefing_meta()
        info = meta.get(day, {})
        v = request.args.get("v", "")
        if v:
            if v not in info.get("versions", []):
                abort(404)
            f = P["briefings"] / "versions" / f"{day}-{v}.md"
        text = f.read_text("utf-8")
        if request.args.get("raw"):
            return text, 200, {"Content-Type": "text/plain; charset=utf-8"}
        script = (P["briefings"] / f"{day}.script.md")
        days = sorted(meta)
        i = days.index(day)
        notes = notesmod.load(root, day)["notes"]
        page_html = render_markdown_safely(text)
        if page_html and not v:          # commentary is on the latest version
            page_html = notesmod.inject(page_html, notes)
        return render_template("briefing.html", day=day, text=text, html=page_html,
                               run_id=(info.get("latest") or {}).get("run_id", ""), n_notes=sum(
                                   1 for n in notes.values() if n.get("text", "").strip()),
                               info=info, v=v, audio=info.get("audio"),
                               script=script.read_text("utf-8") if script.is_file() else "",
                               prev_day=days[i - 1] if i > 0 else None,
                               next_day=days[i + 1] if i + 1 < len(days) else None)

    def _check_post():
        tok = request.headers.get("X-CSRF") or request.form.get("csrf") or (request.get_json(silent=True) or {}).get("csrf")
        if tok != app.config["CSRF"]:
            abort(403)
        origin = request.headers.get("Origin", "")
        if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
            abort(403)

    @app.route("/api/commentary/<day>", methods=["POST"])
    def save_commentary(day):
        _check_post()
        if not DAY_RE.match(day) or not (P["briefings"] / f"{day}.md").is_file():
            abort(404)
        body = request.get_json(silent=True) or {}
        key, text = str(body.get("key", "")), str(body.get("text", ""))
        if not notesmod.KEY_RE.match(key) or len(text) > 20000:
            abort(400)
        n = notesmod.save(root, day, key, text, str(body.get("run_id", ""))[:40], str(body.get("title", "")))
        return jsonify({"ok": True, "updated": n["updated"]})

    @app.route("/briefings/<day>/mailout")
    def mailout(day):
        if not DAY_RE.match(day) or not (P["briefings"] / f"{day}.md").is_file():
            abort(404)
        md = notesmod.mailout((P["briefings"] / f"{day}.md").read_text("utf-8"), notesmod.load(root, day)["notes"], day)
        if request.args.get("raw"):
            return md, 200, {"Content-Type": "text/plain; charset=utf-8"}
        return render_template("mailout.html", day=day, md=md, html=render_markdown_safely(md))

    @app.route("/voices")
    def voices_page():
        vdir = P["briefings"] / "voice-samples"
        files = sorted(f.name for f in vdir.glob("*.mp3")) if vdir.exists() else []
        cfg_voice = (cfg.get("audio") or {})
        return render_template("voices.html", files=files, current=f"{cfg_voice.get('engine', '')}:{cfg_voice.get('voice', '')}")

    @app.route("/api/voice", methods=["POST"])
    def set_voice():
        _check_post()
        from pipeline import settings
        choice = (request.get_json(silent=True) or {}).get("voice", "") or request.form.get("voice", "")
        engine, _, voice = choice.partition(":")
        sample = P["briefings"] / "voice-samples" / f"{engine}-{voice or 'default'}.mp3"
        if engine not in ("kokoro", "say") or not sample.is_file():
            abort(400)
        cpath = root / "config.yaml"
        settings.set_value(cpath, "audio", "engine", engine)
        if engine == "kokoro":
            settings.set_value(cpath, "audio", "voice", voice)
            from pipeline import tuning               # the active profile's voice is what the run uses
            live = yaml.safe_load(cpath.read_text("utf-8")) or {}
            prof = tuning.load(root, tuning.active_name(live))
            prof["audio"]["voice"] = voice
            tuning.save(root, prof)
            subprocess.run(["git", "add", "profiles"], cwd=root, capture_output=True)
        else:
            settings.set_value(cpath, "audio", "say_voice", "" if voice == "default" else voice)
        cfg.setdefault("audio", {}).update({"engine": engine, "voice": voice} if engine == "kokoro" else {"engine": engine})
        subprocess.run(["git", "commit", "-q", "-m", f"config: voice {choice} (chosen in dashboard)", "--", "config.yaml", "profiles"],
                       cwd=root, capture_output=True)
        return redirect(url_for("voices_page"))

    @app.route("/voices/<name>")
    def voice_file(name):
        from flask import send_file
        f = P["briefings"] / "voice-samples" / name
        if "/" in name or ".." in name or not name.endswith(".mp3") or not f.is_file():
            abort(404)
        return send_file(f, mimetype="audio/mpeg")

    @app.route("/briefings/<day>.mp3")
    def briefing_audio(day):
        from flask import send_file
        f = P["briefings"] / f"{day}.mp3"
        if not DAY_RE.match(day) or not f.is_file():
            abort(404)
        return send_file(f, mimetype="audio/mpeg")

    # ---------- sources queue ----------
    def _sources_commit(msg):
        from pipeline.archive import Archive
        if cfg.get("archive", {}).get("git_commit", True):
            Archive(root, paths).git_commit(msg, paths=("data/sources", "sources_managed.yaml",
                                                        paths.get("sources", "sources.yaml")))

    @app.route("/api/sources/<sid>/<op>", methods=["POST"])
    def source_decision(sid, op):
        _check_post()
        from pipeline import suggest
        if not SID_RE.match(sid) or op not in ("accept", "deny", "reconsider"):
            abort(404)
        run_cfg = yaml.safe_load((root / "config.yaml").read_text("utf-8")) or {}
        try:
            if op == "accept":
                urls = request.form.getlist("url") if request.form.get("picked") else None
                s = suggest.accept(root, run_cfg, sid, log=lambda *a: None, urls=urls)
            elif op == "deny":
                s = suggest.deny(root, sid, request.form.get("reason", "")[:200])
            else:
                s = suggest.reconsider(root, sid)
        except KeyError:
            abort(404)
        _sources_commit(f"sources: {op} {s['name']} ({s['status']}, dashboard)")
        return redirect(url_for("sources_page") + "#queue")

    @app.route("/api/sources/remove", methods=["POST"])
    def source_remove():
        _check_post()
        from pipeline import suggest
        url = request.form.get("url", "")
        try:
            suggest.remove_source(root, cfg, url, request.form.get("reason", "")[:200])
        except KeyError:
            abort(404)
        _sources_commit(f"sources: removed {url} (dashboard)")
        return redirect(url_for("sources_page"))

    @app.route("/api/sources/restore", methods=["POST"])
    def source_restore():
        _check_post()
        from pipeline import suggest
        suggest.restore_source(root, request.form.get("url", ""))
        _sources_commit("sources: restored a removed URL (dashboard)")
        return redirect(url_for("sources_page") + "#removed")

    # ---------- actions ----------
    @app.route("/actions/<name>", methods=["POST"])
    def do_action(name):
        if request.form.get("csrf") != app.config["CSRF"]:
            abort(403)
        origin = request.headers.get("Origin", "")
        if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
            abort(403)
        if name not in ACTIONS and name != "restart-dashboard":
            abort(404)
        back_ok = ("/control", "/", "/sources", "/tuning", "/record", "/briefings", "/subscribers")
        back = request.form.get("back", "")
        back = back if back in back_ok or __import__("re").match(r"^/briefings/\d{4}-\d{2}-\d{2}$", back) or \
            back.startswith("/tuning?profile=") else "/"
        if name == "restart-dashboard":
            from pipeline import service
            ok = service.restart_dashboard_detached()
            return render_template("restarting.html", ok=ok)
        cmd = list(ACTIONS[name])
        if name in DAY_ACTIONS:
            day = request.form.get("day", "")
            if not DAY_RE.match(day):
                abort(400)
            cmd.append(day)
        if name == "find-source":
            who = " ".join(request.form.get("name", "").split())[:80]
            note = " ".join(request.form.get("note", "").split())[:300]
            if not who or who.startswith("-"):
                abort(400)
            cmd += [who] + ([note] if note and not note.startswith("-") else [])
        if name == "preview":
            from pipeline import tuning
            day, prof = request.form.get("day", ""), request.form.get("profile", "")
            if not DAY_RE.match(day) or prof not in tuning.names(root):
                abort(400)
            cmd += [day, "--profile", prof]
        if name == "dive":
            day, key = request.form.get("day", ""), request.form.get("key", "")
            if not DAY_RE.match(day) or not __import__("re").match(r"^[0-9a-f]{12}$", key):
                abort(400)
            cmd += [day, key]
        if name == "recheck-source":
            sid = request.form.get("id", "")
            if not SID_RE.match(sid):
                abort(400)
            cmd.append(sid)
        st = action_status()
        if st and st["running"]:
            return redirect(back)
        P["logs"].mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        log = P["logs"] / f"action-{name}-{stamp}.log"
        fh = log.open("w", encoding="utf-8")
        state.update(proc=subprocess.Popen(cmd, cwd=root, stdout=fh, stderr=subprocess.STDOUT,
                                           env={**os.environ, "PYTHONUNBUFFERED": "1"}),
                     action=name, started=stamp, log=str(log.relative_to(root)))
        return redirect(back)

    @app.route("/control")
    def control():
        from pipeline import service
        s = service.all_status(root, cfg)
        last = runs()[0] if runs() else None
        days = briefings_list()
        size = sum(f.stat().st_size for f in (root / "data").rglob("*") if f.is_file()) if (root / "data").exists() else 0
        remotes = subprocess.run(["git", "remote", "-v"], cwd=root, capture_output=True, text=True).stdout
        pc = cfg.get("publish", {})
        return render_template("control.html", s=s, last=last, latest_day=days[0] if days else "",
                               archive_mb=round(size / 1e6, 1), git=git_head(), backup_remote=("origin" in remotes),
                               cfg_archive=cfg.get("archive", {}), publish=pc,
                               podcast_url=(pc.get("site_url", "").rstrip("/") + "/podcast.xml") if pc.get("site_url") else "",
                               voice=(cfg.get("audio") or {}).get("voice", ""))

    @app.route("/actions/output")
    def action_output():
        st = action_status()
        text = ""
        if st and st["log"]:
            p = root / st["log"]
            text = p.read_text("utf-8", errors="replace")[-6000:] if p.exists() else ""
        return render_template("_action.html", st=st, text=text)

    from dashboard import explore
    explore.register(app, root, cfg, P, _check_post, render_markdown_safely, DAY_RE)
    return app


def main(port: int = 8765):
    import socket
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Port {port} is already in use: the dashboard is probably already running "
                  f"(as a service, or in another Terminal). Open http://127.0.0.1:{port}")
            sys.exit(0)
    app = create_app()
    print(f"Dashboard: http://127.0.0.1:{port}  (Ctrl-C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
