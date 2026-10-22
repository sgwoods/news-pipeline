"""Dashboard pages for tuning and exploring: Tuning (profiles, prompts, previews), experiments + compare,
Threads (developing stories), Questions (open questions you track), Deep dives.

Registered from app.create_app(). Writes only profiles/, config.yaml tuning.profile and data/questions.json,
each committed to git; previews and dives run as background actions (python run.py ...).
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess

import yaml
from flask import abort, redirect, render_template, request, send_file, url_for

from pipeline import dive as divemod
from pipeline import editorial, questions, settings, stages, tuning
from pipeline.archive import Archive, read_jsonl

KEY_RE = re.compile(r"^[0-9a-f]{12}$")


def register(app, root, cfg, P, check_post, md_html, DAY_RE):
    paths = cfg.get("paths", {})

    def commit(msg, *files):
        if cfg.get("archive", {}).get("git_commit", True):
            Archive(root, paths).git_commit(msg, paths=files)

    def live_cfg():
        return yaml.safe_load((root / "config.yaml").read_text("utf-8")) or {}

    def experiments():
        return list(reversed(read_jsonl(root / "data" / "experiments.jsonl")))

    def latest_day():
        days = sorted(f.stem for f in P["briefings"].glob("????-??-??.md"))
        return days[-1] if days else ""

    def prompt_text(prof, stage):
        if stage in prof["prompts"]:
            return prof["prompts"][stage], True
        f = stages.PROMPTS / f"{stage}.md"
        return (f.read_text("utf-8") if f.exists() else ""), False

    # ---------- Tuning ----------
    @app.route("/tuning")
    def tuning_page():
        names = tuning.names(root)
        active = tuning.active_name(live_cfg())
        name = request.args.get("profile") or active
        if name not in names:
            abort(404)
        prof = tuning.load(root, name)
        groups = {}
        for g, key, typ, default, label, help_, extra in tuning.KNOBS:
            sec, k = key.split(".", 1)
            val = prof[sec][k]
            groups.setdefault(g, []).append({"key": key, "type": typ, "label": label, "help": help_, "extra": extra,
                                             "value": ", ".join(val) if typ == "list" else val,
                                             "changed": val != default})
        prompts = [{"stage": s, "text": prompt_text(prof, s)[0], "override": prompt_text(prof, s)[1]}
                   for s in tuning.PROMPT_STAGES]
        voices = sorted(f.stem.split("-", 1)[1] for f in (P["briefings"] / "voice-samples").glob("kokoro-*.mp3")) \
            if (P["briefings"] / "voice-samples").exists() else []
        return render_template("tuning.html", names=names, active=active, name=name, prof=prof, groups=groups,
                               prompts=prompts, exps=[e for e in experiments()][:30], day=latest_day(),
                               fingerprint=tuning.fingerprint(prof), voices=voices,
                               saved=request.args.get("saved"), errors=request.args.getlist("err"))

    @app.route("/api/tuning/<name>/save", methods=["POST"])
    def tuning_save(name):
        check_post()
        if name not in tuning.names(root):
            abort(404)
        prof, errors = tuning.coerce(request.form.to_dict(), tuning.load(root, name))
        if errors:
            return redirect(url_for("tuning_page", profile=name, err=errors))
        tuning.save(root, prof)
        commit(f"tuning: saved profile {name}", "profiles")
        return redirect(url_for("tuning_page", profile=name, saved=1))

    @app.route("/api/tuning/new", methods=["POST"])
    def tuning_new():
        check_post()
        src, new = request.form.get("from", "default"), request.form.get("name", "").strip().lower()
        if src not in tuning.names(root) or not tuning.NAME_RE.match(new) or new in tuning.names(root):
            return redirect(url_for("tuning_page", profile=src, err=["Name: lowercase letters, digits and dashes, not in use"]))
        prof = tuning.load(root, src)
        prof["name"] = new
        prof["description"] = f"Copy of {src}"
        tuning.save(root, prof)
        commit(f"tuning: new profile {new} (from {src})", "profiles")
        return redirect(url_for("tuning_page", profile=new))

    @app.route("/api/tuning/<name>/activate", methods=["POST"])
    def tuning_activate(name):
        check_post()
        if name not in tuning.names(root):
            abort(404)
        if not (root / "profiles" / f"{name}.yaml").exists():
            tuning.save(root, tuning.load(root, name))
        settings.set_value(root / "config.yaml", "tuning", "profile", name)
        commit(f"tuning: daily run now uses profile {name}", "config.yaml", "profiles")
        return redirect(url_for("tuning_page", profile=name, saved=1))

    @app.route("/api/tuning/<name>/prompt/<stage>", methods=["POST"])
    def tuning_prompt(name, stage):
        check_post()
        if name not in tuning.names(root) or stage not in tuning.PROMPT_STAGES:
            abort(404)
        prof = tuning.load(root, name)
        text = request.form.get("text", "").replace("\r\n", "\n")
        builtin = (stages.PROMPTS / f"{stage}.md").read_text("utf-8")
        if request.form.get("reset") or not text.strip() or text.strip() == builtin.strip():
            prof["prompts"].pop(stage, None)
        else:
            prof["prompts"][stage] = text[:20000]
        tuning.save(root, prof)
        commit(f"tuning: {name} prompt {stage} {'reset' if stage not in prof['prompts'] else 'edited'}", "profiles")
        return redirect(url_for("tuning_page", profile=name, saved=1) + f"#prompt-{stage}")

    # ---------- Lens: who Steven is (author.md, editable) + perspective.md (read-only) ----------
    def git_log(path, n=10):
        r = subprocess.run(["git", "log", f"-{n}", "--format=%h|%cd|%s", "--date=format:%Y-%m-%d %H:%M", "--", path],
                           cwd=root, capture_output=True, text=True)
        return [dict(zip(("h", "date", "msg"), ln.split("|", 2))) for ln in r.stdout.splitlines() if ln.count("|") >= 2]

    @app.route("/lens")
    def lens_page():
        author = root / "author.md"
        persp = root / paths.get("perspective", "perspective.md")
        prof = tuning.load(root, tuning.active_name(live_cfg()))
        ptext = persp.read_text("utf-8") if persp.exists() else ""
        return render_template("lens.html", author=author.read_text("utf-8") if author.exists() else "",
                               persp_html=md_html(ptext), persp_text=ptext, author_log=git_log("author.md"),
                               persp_log=git_log(paths.get("perspective", "perspective.md"), 5), prof=prof,
                               saved=request.args.get("saved"))

    @app.route("/api/lens/author", methods=["POST"])
    def lens_save():
        check_post()
        text = request.form.get("text", "").replace("\r\n", "\n")
        if len(text) > 30000:
            abort(400)
        (root / "author.md").write_text(text.rstrip() + "\n", "utf-8")
        commit("lens: author.md edited on the dashboard", "author.md")
        return redirect(url_for("lens_page", saved=1))

    # ---------- Record: Steven's public record ----------
    @app.route("/record")
    def record_page():
        from pipeline import record
        q = record.load_queue(root)
        own = root / record.DIR / "own-words.md"
        own_meta = {}
        try:
            own_meta = __import__("json").loads((root / record.DIR / "own-words.json").read_text("utf-8"))
        except (OSError, ValueError):
            pass
        last = {}
        try:
            last = __import__("json").loads((root / record.DIR / "last-search.json").read_text("utf-8"))
        except (OSError, ValueError):
            pass
        author = (root / "author.md").read_text("utf-8") if (root / "author.md").exists() else ""
        return render_template("record.html", pending=[c for c in q if c["status"] == "pending"],
                               accepted=[c for c in q if c["status"] == "accepted"],
                               denied=[c for c in q if c["status"] == "denied"],
                               mentions=record.recent_mentions(root), own_html=md_html(own.read_text("utf-8")) if own.exists() else "",
                               own_meta=own_meta, own_applied=record.OWN_START in author, last=last,
                               n_manifest=len(record.manifest(root, cfg, refresh=False).get("sources", [])),
                               watch=record.rcfg(live_cfg())["watch"])

    @app.route("/api/record/<cid>/<op>", methods=["POST"])
    def record_decide(cid, op):
        check_post()
        from pipeline import record
        if not re.match(r"^[0-9a-f]{10}$", cid) or op not in ("accept", "deny"):
            abort(404)
        try:
            c = record.decide(root, cid, "accepted" if op == "accept" else "denied", request.form.get("note", ""))
        except KeyError:
            abort(404)
        commit(f"record: {c['status']} {c['title'][:60]} (dashboard)", "data/public-record")
        return redirect(url_for("record_page"))

    @app.route("/api/record/apply-words", methods=["POST"])
    def record_apply_words():
        check_post()
        from pipeline import record
        if not record.apply_own_words(root):
            abort(400)
        commit("lens: 'In my own words' added to author.md (dashboard)", "author.md")
        return redirect(url_for("lens_page", saved=1))

    @app.route("/record/manifest-candidates.json")
    def record_export():
        from pipeline import record
        p = root / record.DIR / "manifest-candidates.json"
        if not p.exists():
            record.export(root)
        return send_file(p, mimetype="application/json", as_attachment=True, download_name="manifest-candidates.json")

    # ---------- Email subscribers (list lives in Steven's Google Sheet via Apps Script) ----------
    @app.route("/subscribers")
    def subscribers_page():
        from pipeline import mailer
        c = live_cfg()
        miss, data, err = mailer.ready(c), {}, ""
        if not miss:
            try:
                data = mailer.subscribers(c)
            except mailer.MailError as ex:
                err = str(ex)
        subs = data.get("subscribers", [])
        log = list(reversed(read_jsonl(root / mailer.LOG)))[:20]
        return render_template("subscribers.html", missing=miss, err=err, subs=subs, quota=data.get("quota"),
                               counts={st: sum(1 for x in subs if x["status"] == st) for st in ("active", "pending", "unsubscribed")},
                               log=log, enabled=mailer.ecfg(c)["enabled"], day=latest_day(), msg=request.args.get("msg", ""))

    @app.route("/api/subscribers/<op>", methods=["POST"])
    def subscribers_op(op):
        check_post()
        from pipeline import mailer
        email = request.form.get("email", "").strip()
        if op not in ("add", "remove") or not re.match(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]{2,}$", email) or len(email) > 200:
            return redirect(url_for("subscribers_page", msg="That doesn't look like an email address."))
        try:
            if op == "add":
                note = "added on the dashboard; consent confirmed by Steven" if request.form.get("confirmed") else ""
                res = mailer.add(live_cfg(), email, note)
                msg = (f"{email} added and active." if res.get("status") == "active"
                       else f"Confirmation email sent to {email}; they become active when they click it.")
            else:
                mailer.remove(live_cfg(), email)
                msg = f"{email} unsubscribed."
        except mailer.MailError as ex:
            msg = f"Failed: {ex}"
        return redirect(url_for("subscribers_page", msg=msg))

    @app.route("/email/preview/<day>")
    def email_preview(day):
        from pipeline import mailer
        f = P["briefings"] / f"{day}.md"
        if not DAY_RE.match(day) or not f.is_file():
            abort(404)
        m = mailer.render(day, f.read_text("utf-8"), live_cfg(), (P["briefings"] / f"{day}.mp3").is_file())
        return m["html"].replace("{{UNSUBSCRIBE}}", "#")

    # ---------- To do (shared list) ----------
    @app.route("/todo")
    def todo_page():
        from pipeline import todos
        if not todos.load(root):
            todos.seed(root, todos.STARTER)
        g = todos.grouped(root)
        n_open = sum(1 for rows in g.values() for r in rows if r["status"] != "done")
        return render_template("todo.html", groups=g, n_open=n_open, show=request.args.get("show", "open"))


    # ---------- Company watchlist ----------
    @app.route("/watchlist")
    def watchlist_page():
        from pipeline import watchlist as wl
        days = int(request.args.get("days", "30") or 30)
        ms = wl.mentions(root, days)
        cos = wl.load(root)
        by = {c["name"]: [m for m in ms if m["company"] == c["name"]] for c in cos}
        return render_template("watchlist.html", companies=cos, by=by, days=days, relations=wl.RELATIONS,
                               query_of=wl.query_of, people_text=wl.people_text)

    @app.route("/api/watchlist/add", methods=["POST"])
    def watchlist_add():
        check_post()
        from pipeline import watchlist as wl
        f = request.form
        try:
            wl.add(root, f.get("name", ""), f.get("relation", "other"), (f.get("aliases") or "").split(","),
                   f.get("query", ""), f.get("site", ""))
        except ValueError:
            pass
        commit("watchlist: add (dashboard)", wl.FILE)
        return redirect(url_for("watchlist_page"))

    @app.route("/api/watchlist/update", methods=["POST"])
    def watchlist_update():
        check_post()
        from pipeline import watchlist as wl
        f = request.form
        split = lambda s: [x.strip() for x in re.split(r"[,\n]", s or "") if x.strip()]
        try:
            wl.update(root, f.get("name", ""), relation=f.get("relation", ""), aliases=split(f.get("aliases")),
                      query=f.get("query", ""), site=f.get("site", ""), people=wl.parse_people(f.get("people", "")),
                      competitors=split(f.get("competitors")))
        except KeyError:
            abort(404)
        commit(f"watchlist: edit {f.get('name', '')} (dashboard)", wl.FILE)
        return redirect(url_for("watchlist_page") + "#c-" + re.sub(r"\W+", "-", f.get("name", "")))

    @app.route("/api/watchlist/remove", methods=["POST"])
    def watchlist_remove():
        check_post()
        from pipeline import watchlist as wl
        wl.remove(root, request.form.get("name", ""))
        commit("watchlist: remove (dashboard)", wl.FILE)
        return redirect(url_for("watchlist_page"))

    # ---------- Deep-dive queue ----------
    @app.route("/deep-dives")
    def deepdive_page():
        from pipeline import deepdive
        items = deepdive.load_queue(root)
        recs = {r["day"]: r for r in deepdive.records(root) if r.get("status") == "published"}
        groups = {
            "scheduled": [x for x in items if x["status"] == "scheduled"],
            "queued": deepdive.queued(root),
            "suggested": sorted([x for x in items if x["status"] == "suggested"],
                                key=lambda x: (x.get("source_day", ""), x.get("strength") or 0), reverse=True),
            "done": sorted([x for x in items if x["status"] in ("done", "failed")], key=lambda x: x.get("status_at", ""), reverse=True)[:15],
            "dismissed": sorted([x for x in items if x["status"] == "dismissed"], key=lambda x: x.get("status_at", ""), reverse=True)[:15],
        }
        c = deepdive.dcfg(live_cfg())
        return render_template("deepdives.html", g=groups, recs=recs, cap=c["max_per_week"],
                               week=deepdive._week_count(root, dt.date.today().isoformat()))

    @app.route("/api/deep-dives/<qid>/<op>", methods=["POST"])
    def deepdive_op(qid, op):
        check_post()
        from pipeline import deepdive
        try:
            if op in ("up", "down"):
                deepdive.move(root, qid, -1 if op == "up" else 1)
            elif op in ("top", "bottom", "position"):
                pos = 1 if op == "top" else 10_000 if op == "bottom" else int(request.form.get("pos", "1") or 1)
                deepdive.move_to(root, qid, pos)
            elif op in ("queued", "dismissed", "suggested"):
                deepdive.set_status(root, qid, op)
            else:
                abort(404)
        except (KeyError, ValueError):
            abort(404)
        commit(f"deep dives: {op} {qid} (dashboard)", deepdive.QUEUE)
        return redirect(url_for("deepdive_page"))

    @app.route("/api/deep-dives/add", methods=["POST"])
    def deepdive_add():
        check_post()
        from pipeline import deepdive
        topic = (request.form.get("topic") or "").strip()[:120]
        if topic:
            deepdive.add_manual(root, topic, (request.form.get("angle") or "").strip()[:500])
            commit("deep dives: add (dashboard)", deepdive.QUEUE)
        return redirect(url_for("deepdive_page"))

    # ---------- Quality scorecard ----------
    @app.route("/quality")
    def quality_page():
        from pipeline import quality
        days = sorted((f.stem for f in P["briefings"].glob("????-??-??.md")), reverse=True)[:21]
        have = {r["day"]: r for r in quality.load_all(root)}
        rows = [have.get(d) or quality.score_day(root, live_cfg(), d) for d in days]
        rows = [r for r in rows if r]
        keys = [(k, lab, tgt) for k, lab, tgt, _ in quality.TARGETS]
        return render_template("quality.html", rows=rows, keys=keys, fmt=quality.fmt)

    @app.route("/api/quality/<day>/rate", methods=["POST"])
    def quality_rate(day):
        check_post()
        from pipeline import quality
        if not DAY_RE.match(day):
            abort(404)
        try:
            quality.add_rating(root, day, int(request.form.get("score", "0")), "steven", request.form.get("note", ""))
        except ValueError:
            abort(400)
        quality.score_day(root, live_cfg(), day)
        commit(f"quality: rated {day} (dashboard)", quality.RATINGS, quality.DIR)
        return redirect(url_for("quality_page") + f"#q-{day}")

    # ---------- Feedback (replies to the daily email) ----------
    @app.route("/feedback")
    def feedback_page():
        from pipeline import feedback as fb
        d = fb.load(root)
        show = request.args.get("show", "open")
        rank = {"high": 0, "medium": 1, "low": 2}
        rows = d["items"] if show == "all" else [i for i in d["items"] if i.get("status") in fb.OPEN]
        rows = sorted(rows, key=lambda i: (rank.get((i.get("triage") or {}).get("severity"), 3),
                                           "" if i.get("status") == "new" else "z", i.get("received", "")))
        cats = {}
        for i in d["items"]:
            c = (i.get("triage") or {}).get("category", "untriaged")
            cats[c] = cats.get(c, 0) + 1
        return render_template("feedback.html", rows=rows, themes=d["themes"], triaged_at=d["triaged_at"],
                               c=fb.counts(root), cats=sorted(cats.items(), key=lambda x: -x[1]), show=show,
                               statuses=fb.STATUSES)

    @app.route("/api/feedback/<fid>/<op>", methods=["POST"])
    def feedback_op(fid, op):
        check_post()
        from pipeline import feedback as fb
        if not re.match(r"^[0-9a-f]{10}$", fid):
            abort(404)
        try:
            if op == "todo":
                from pipeline import todos
                it = next(i for i in fb.load(root)["items"] if i["id"] == fid)
                t = it.get("triage") or {}
                todos.add(root, ("Feedback: " + (t.get("summary") or it["text"][:100]))[:160], "feedback", "claude",
                          detail=t.get("action", ""))
                fb.set_status(root, fid, "acting", "to-do created")
                commit(f"feedback: to-do from {fid} (dashboard)", fb.STORE, "data/todos.json")
            elif op in fb.STATUSES:
                fb.set_status(root, fid, op, request.form.get("note", ""))
                commit(f"feedback: {fid} -> {op} (dashboard)", fb.STORE)
            else:
                abort(404)
        except (KeyError, StopIteration):
            abort(404)
        return redirect(url_for("feedback_page", show=request.form.get("show", "open")) + f"#f-{fid}")

    @app.route("/api/todo/<tid>/<op>", methods=["POST"])
    def todo_op(tid, op):
        check_post()
        from pipeline import todos
        if not re.match(r"^[0-9a-f]{8}$", tid) or op not in ("done", "reopen"):
            abort(404)
        try:
            todos.set_status(root, tid, "done" if op == "done" else "open", request.form.get("note", ""))
        except KeyError:
            abort(404)
        commit(f"todo: {op} {tid} (dashboard)", "data/todos.json")
        return redirect(url_for("todo_page", show=request.form.get("show", "open")) + f"#t-{tid}")

    @app.route("/api/todo/add", methods=["POST"])
    def todo_add():
        check_post()
        from pipeline import todos
        title = " ".join(request.form.get("title", "").split())[:160]
        if not title:
            return redirect(url_for("todo_page"))
        todos.add(root, title, request.form.get("group", "setup"), request.form.get("owner", "steven"))
        commit("todo: add (dashboard)", "data/todos.json")
        return redirect(url_for("todo_page"))

    # ---------- experiments ----------
    def exp_file(day, profile, ext):
        if not DAY_RE.match(day) or not tuning.NAME_RE.match(profile):
            abort(404)
        return P["briefings"] / "experiments" / day / f"{profile}{ext}"

    def side(day, which):
        """'live' or a profile name → dict for the compare/experiment templates."""
        if which == "live":
            f = P["briefings"] / f"{day}.md"
            mp3 = (P["briefings"] / f"{day}.mp3")
            script = P["briefings"] / f"{day}.script.md"
            audio_url = f"/briefings/{day}.mp3"
            rows = [b for b in read_jsonl(root / paths.get("briefings_log", "data/briefings.jsonl")) if b.get("day") == day]
            label = f"Live briefing (profile {(rows[-1].get('profile') if rows else '') or 'pre-tuning'})"
        else:
            f, mp3, script = exp_file(day, which, ".md"), exp_file(day, which, ".mp3"), exp_file(day, which, ".script.md")
            audio_url = f"/experiments/{day}/{which}.mp3"
            label = f"Profile {which}"
        if not f.is_file():
            return None
        text = f.read_text("utf-8")
        return {"which": which, "label": label, "html": md_html(text), "words": len(text.split()),
                "sections": re.findall(r"(?m)^## (.+)$", text), "audio": audio_url if mp3.is_file() else "",
                "script": script.read_text("utf-8") if script.is_file() else "",
                "script_words": len(script.read_text("utf-8").split()) if script.is_file() else 0}

    @app.route("/experiments/<day>/<profile>")
    def experiment_page(day, profile):
        s = side(day, profile)
        if not s:
            abort(404)
        rec = next((e for e in experiments() if e["day"] == day and e["profile"] == profile), {})
        return render_template("experiment.html", day=day, s=s, rec=rec)

    @app.route("/experiments/<day>/<profile>.mp3")
    def experiment_mp3(day, profile):
        f = exp_file(day, profile, ".mp3")
        if not f.is_file():
            abort(404)
        return send_file(f, mimetype="audio/mpeg")

    @app.route("/compare")
    def compare():
        day = request.args.get("day", "")
        a, b = request.args.get("a", "live"), request.args.get("b", "")
        if not DAY_RE.match(day):
            abort(404)
        options = ["live"] + sorted({e["profile"] for e in experiments() if e["day"] == day})
        return render_template("compare.html", day=day, a=side(day, a) if a in options else None,
                               b=side(day, b) if b in options else None, options=options, an=a, bn=b)

    # ---------- threads ----------
    @app.route("/threads")
    def threads_page():
        idx = editorial.thread_index(root / "data" / "stories")
        rows = []
        for t, xs in idx.items():
            days = sorted({x["day"] for x in xs})
            if len(days) >= 2 or request.args.get("all"):
                rows.append({"id": t, "days": days, "headline": xs[-1]["headline"], "first": xs[0]["headline"],
                             "n": len(days), "last": days[-1]})
        rows.sort(key=lambda r: (r["last"], r["n"]), reverse=True)
        return render_template("threads.html", rows=rows, all=bool(request.args.get("all")))

    @app.route("/threads/<tid>")
    def thread_page(tid):
        if not KEY_RE.match(tid):
            abort(404)
        xs = editorial.thread_index(root / "data" / "stories").get(tid)
        if not xs:
            abort(404)
        dives = divemod.dives_for(root)
        full = []
        for x in xs:
            try:
                full.append({**x, **divemod.find_story(root, x["day"], x["key"]), "dive": dives.get((x["day"], x["key"]))})
            except KeyError:
                full.append(x)
        return render_template("thread.html", tid=tid, xs=full)

    # ---------- questions ----------
    @app.route("/questions")
    def questions_page():
        show = request.args.get("show", "open")
        qs = questions.all_questions(root)
        counts = {s: sum(1 for q in qs if q["status"] == s) for s in questions.STATUSES}
        if show != "all":
            qs = [q for q in qs if q["status"] == show]
        return render_template("questions.html", qs=qs, show=show, counts=counts)

    @app.route("/api/questions/<qid>", methods=["POST"])
    def question_set(qid):
        check_post()
        if not re.match(r"^[0-9a-f]{10}$", qid):
            abort(404)
        try:
            questions.set_status(root, qid, request.form.get("status", "open"), request.form.get("note", ""))
        except ValueError:
            abort(400)
        commit("questions: status update", "data/questions.json")
        return redirect(url_for("questions_page", show=request.form.get("show", "open")) + f"#q-{qid}")

    # ---------- deep dives ----------
    @app.route("/dives")
    def dives_page():
        return render_template("dives.html", rows=sorted(divemod.dives_for(root).values(),
                                                         key=lambda r: r["created"], reverse=True))

    @app.route("/dives/<day>/<key>")
    def dive_page(day, key):
        if not DAY_RE.match(day) or not KEY_RE.match(key):
            abort(404)
        f = P["briefings"] / "dives" / f"{day}-{key}.md"
        if not f.is_file():
            abort(404)
        rec = divemod.dives_for(root, day).get((day, key), {})
        text = f.read_text("utf-8")
        if request.args.get("raw"):
            return text, 200, {"Content-Type": "text/plain; charset=utf-8"}
        return render_template("dive.html", day=day, key=key, html=md_html(text), text=text, rec=rec)

    # stories panel for the briefing page
    def stories_panel(day):
        rows = read_jsonl(root / "data" / "stories" / f"{day}.jsonl")
        if not rows:
            return []
        dives = divemod.dives_for(root, day)
        return [{**s, "dive": dives.get((day, s["key"]))} for s in rows[-1].get("stories", [])
                if s.get("section") in ("must", "worth")]

    app.jinja_env.globals["stories_panel"] = stories_panel
