"""Tuning profiles: the knobs that shape the briefing and the audio, as named, versioned presets.

profiles/<name>.yaml   committed; edited on the dashboard Tuning page (or by hand)
config.yaml            tuning.profile = the active one (used by the daily run)

A profile overlays config.yaml at load time:
  briefing.*  -> cfg["analysis"]   (section sizes, top-of-mind count, open questions, threads)
  editorial.* -> cfg["editorial"]  (audience, focus, tone: filled into the editorial prompt)
  audio.*     -> cfg["audio"]      (length, persona, depth, sections, voice, speed)
  prompts.*   -> full-text overrides of pipeline/prompts/<stage>.md (versioned by hash like the files)

perspective.md stays the lens and is never written; profiles only change how it is applied.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

DIR = "profiles"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

PERSONAS = {
    "plain": "",
    "anchor": "Speak as a crisp news anchor: brisk and neutral; every sentence carries a fact.",
    "analyst": "Speak as a conversational analyst briefing a colleague: relaxed, connects the dots, still precise.",
    "skeptic": "Speak as a skeptical investor: direct, presses on numbers and incentives, never hypes.",
    "custom": None,          # use audio.persona_custom
}
DEPTHS = {
    # words per story (None = share of the target length), what is spoken
    "headline": {"words": 45, "fields": ["What happened"]},
    "summary": {"words": 110, "fields": ["What happened", "Critical pass"]},
    "analysis": {"words": None, "fields": None},     # everything in the written story
}
AUDIO_SECTIONS = ["intro", "top_of_mind", "must", "worth", "questions", "outro"]
PROMPT_STAGES = ["editorial", "script", "critique", "cluster", "merge", "summarize", "filter", "system", "dive"]

# The knob registry: drives defaults, validation and the dashboard form.
KNOBS = [
    # group, key, type, default, label, help, extra
    ("Briefing structure", "briefing.max_must_read", "int", 6, "Must read stories", "Full write-ups at the top.", (0, 12)),
    ("Briefing structure", "briefing.max_worth_knowing", "int", 8, "Worth knowing", "One-paragraph items.", (0, 20)),
    ("Briefing structure", "briefing.max_in_brief", "int", 8, "In brief", "One-line items; the rest stay in the dashboard.", (0, 30)),
    ("Briefing structure", "briefing.max_items_per_source", "int", 3, "Max items per source per day",
     "Across all sections, so one outlet cannot fill the edition.", (1, 10)),
    ("Briefing structure", "briefing.max_words", "int", 1500, "Word cap for the written edition",
     "Lowest In brief, then Worth knowing items are left out to fit. Target 900-1,300.", (400, 4000)),
    ("Briefing structure", "briefing.max_stories_per_source", "int", 2, "Max top stories per source",
     "Keeps one prolific source from dominating.", (1, 6)),
    ("Briefing structure", "briefing.top_of_mind", "int", 4, "Top of mind bullets", "", (0, 6)),
    ("Briefing structure", "briefing.accuracy_audit", "bool", True, "Accuracy audit after the email",
     "About five claims re-checked against their sources; one alert if any is partly right or contradicted.", None),
    ("Briefing structure", "briefing.top_format", "choice", "separate", "Top of the edition",
     "separate: the day in brief, then Top of mind. merged: one 5-bullet \"Today in 30 seconds\" with the diligence "
     "question under it (critic 10-24, #7A).", ["separate", "merged"]),
    ("Briefing structure", "briefing.open_questions", "int", 3, "Open questions",
     "Follow-up questions saved with the briefing, tracked on the Questions page.", (0, 6)),
    ("Briefing structure", "briefing.threads", "bool", True, "Link developing stories",
     "Marks stories that continue an earlier one (\"day 3\") and groups them on the Threads page.", None),
    ("Briefing structure", "briefing.thread_days", "int", 7, "Look back for threads (days)", "", (1, 30)),
    ("Editorial lens", "editorial.audience", "text", "an early-stage (seed to Series A) AI investor",
     "Written for", "Who the editor writes for.", None),
    ("Editorial lens", "editorial.focus", "text",
     "what it means for an early-stage AI investor, a question worth exploring in diligence, or where we read the source differently",
     "Our read should give", "At most two sentences per Must read story, editorial \"we\".", None),
    ("Editorial lens", "editorial.tone", "text", "Your own judgement, plain and direct.", "Editorial tone", "", None),
    ("Editorial lens", "editorial.house_views", "bool", True, "Take positions under the house views",
     "Each Our read names its view (house_views.md); the lead gets the case for and against, the deciding question "
     "and our lean; positions are logged for scoring.", None),
    ("Audio", "audio.minutes", "int", 15, "Target length (minutes)", "Not padded if there is less to say.", (2, 40)),
    ("Audio", "audio.format", "choice", "classic", "Episode format",
     "spec: 4 main stories, 3 quick hits, a close with the diligence question (format review 10-13). "
     "classic: the sections below.", ["spec", "classic"]),
    ("Audio", "audio.max_minutes", "int", 10, "Hard cap (minutes)", "spec format: quick hits, then the last story, are left out to fit.", (3, 30)),
    ("Audio", "audio.max_stories", "int", 4, "Main stories (spec)", "", (1, 6)),
    ("Audio", "audio.max_quick_hits", "int", 3, "Quick hits (spec)", "", (0, 5)),
    ("Audio", "audio.persona", "choice", "plain", "Persona", "How the script is written to be spoken.", list(PERSONAS)),
    ("Audio", "audio.persona_custom", "text", "", "Custom persona", "Used when Persona is 'custom'.", None),
    ("Audio", "audio.depth", "choice", "analysis", "Depth per story",
     "headline ≈ 20 s each · summary ≈ 45 s with the verdict · analysis = full story, critical read and editor's view.",
     list(DEPTHS)),
    ("Audio", "audio.speak_critical", "bool", True, "Speak the evidence check", "", None),
    ("Audio", "audio.speak_editor", "bool", True, "Speak our read", "", None),
    ("Audio", "audio.sections", "list", ["intro", "must", "worth", "outro"], "Spoken sections, in order",
     "Any of: " + ", ".join(AUDIO_SECTIONS), AUDIO_SECTIONS),
    ("Audio", "audio.must_share", "int", 65, "Share of time for Must read (%)", "The rest goes to the other sections.", (20, 95)),
    ("Audio", "audio.voice", "text", "am_michael", "Voice", "Kokoro voice; listen at /voices.", None),
    ("Audio", "audio.host_name", "text", "Michael", "Briefing host's name", "Used only in the hand-off to the deep dive.", None),
    ("Audio", "audio.deepdive_voice", "text", "af_bella", "Deep-dive voice", "Kokoro voice for the deep-dive episode; listen at /voices.", None),
    ("Audio", "audio.deepdive_host", "text", "Bella", "Deep-dive host's name", "Named in the briefing's hand-off and the deep dive's opening.", None),
    ("Audio", "audio.speed", "float", 1.0, "Speaking speed", "", (0.7, 1.4)),
]
SECTION_FOR = {"briefing": "analysis", "editorial": "editorial", "audio": "audio"}


def defaults() -> dict:
    out: dict = {}
    for _, key, _, default, *_ in KNOBS:
        sec, k = key.split(".", 1)
        out.setdefault(sec, {})[k] = copy.deepcopy(default)
    return out


def path(root: Path, name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise ValueError(f"bad profile name {name!r} (lowercase letters, digits, dashes)")
    return root / DIR / f"{name}.yaml"


def names(root: Path) -> list[str]:
    d = root / DIR
    found = sorted(p.stem for p in d.glob("*.yaml")) if d.exists() else []
    return found if "default" in found else ["default"] + found


def load(root: Path, name: str) -> dict:
    """Defaults, overlaid with the profile file if it exists."""
    import yaml
    p = path(root, name)
    data = (yaml.safe_load(p.read_text("utf-8")) if p.exists() else None) or {}
    prof = defaults()
    for sec in ("briefing", "editorial", "audio"):
        prof[sec].update({k: v for k, v in (data.get(sec) or {}).items() if k in prof[sec]})
    prof["prompts"] = {k: v for k, v in (data.get("prompts") or {}).items() if k in PROMPT_STAGES and v}
    prof["name"] = name
    prof["description"] = data.get("description", "")
    return prof


def save(root: Path, prof: dict) -> Path:
    import yaml
    p = path(root, prof["name"])
    p.parent.mkdir(exist_ok=True)
    body = {"description": prof.get("description", ""),
            **{sec: prof[sec] for sec in ("briefing", "editorial", "audio")}}
    if prof.get("prompts"):
        body["prompts"] = prof["prompts"]
    header = (f"# Tuning profile '{prof['name']}'. Edited on the dashboard Tuning page; safe to hand-edit.\n"
              "# Activate with config.yaml tuning.profile, or 'Make active' on the Tuning page.\n")
    p.write_text(header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=110), "utf-8")
    return p


def fingerprint(prof: dict) -> str:
    body = {k: prof[k] for k in ("briefing", "editorial", "audio", "prompts") if k in prof}
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:8]


def active_name(cfg: dict) -> str:
    return (cfg.get("tuning") or {}).get("profile") or "default"


def apply(cfg: dict, root: Path, name: str | None = None) -> dict:
    """cfg with the profile overlaid. Also installs the profile's prompt overrides."""
    from . import stages
    name = name or active_name(cfg)
    prof = load(root, name)
    out = copy.deepcopy(cfg)
    for sec, target in SECTION_FOR.items():
        out.setdefault(target, {}).update(copy.deepcopy(prof[sec]))
    out["tuning_profile"] = {"name": name, "fingerprint": fingerprint(prof)}
    stages.PROMPT_OVERRIDES.clear()
    stages.PROMPT_OVERRIDES.update(prof["prompts"])
    return out


def coerce(form: dict, prof: dict) -> tuple[dict, list[str]]:
    """Form strings → a validated profile. Returns (profile, errors)."""
    prof = copy.deepcopy(prof)
    errors = []
    for _, key, typ, default, label, _, extra in KNOBS:
        sec, k = key.split(".", 1)
        raw = form.get(key)
        if typ == "bool":
            prof[sec][k] = raw in ("1", "on", "true", True)
            continue
        if raw is None:
            continue
        raw = str(raw).strip()
        try:
            if typ == "int":
                v = int(raw)
                if extra and not extra[0] <= v <= extra[1]:
                    raise ValueError(f"between {extra[0]} and {extra[1]}")
            elif typ == "float":
                v = round(float(raw), 2)
                if extra and not extra[0] <= v <= extra[1]:
                    raise ValueError(f"between {extra[0]} and {extra[1]}")
            elif typ == "choice":
                if raw not in extra:
                    raise ValueError("one of " + ", ".join(extra))
                v = raw
            elif typ == "list":
                v = [x for x in re.split(r"[,\s]+", raw.lower()) if x]
                bad = [x for x in v if x not in extra]
                if bad or not v:
                    raise ValueError("pick from " + ", ".join(extra))
                v = list(dict.fromkeys(v))
            else:
                v = raw[:400]
        except ValueError as e:
            errors.append(f"{label}: {e}")
            continue
        prof[sec][k] = v
    if "description" in form:
        prof["description"] = str(form["description"]).strip()[:200]
    return prof, errors


def persona_text(acfg: dict) -> str:
    p = acfg.get("persona", "plain")
    if p == "custom":
        return (acfg.get("persona_custom") or "").strip()
    return PERSONAS.get(p, "") or ""
