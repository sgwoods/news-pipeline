"""Phase 2: spoken briefing.

script  the day's briefing -> the written audio script (Claude, whole episode), checked section by section;
        the script is the source of truth for what is said (briefings/<day>.script.md)
speech  script -> spoken text by code: figures expanded, names respelled (speech.py, pronunciations.yaml)
tts     Kokoro (local, open-source) or macOS `say` -> WAV per section -> one MP3 via ffmpeg
deliver copy the MP3 to an iCloud Drive folder so it is on the phone for the drive

Outputs: briefings/<day>.script.md (committed), briefings/<day>.mp3 (not committed: large; on disk + iCloud).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from .stages import _ask, prompt

WPM = 130          # fallback; real planning uses voice_wpm() (measured per voice from recent episodes)
DEFAULT_WPM = {"am_michael": 130, "af_bella": 157}   # measured 10-13..18: script words / real MP3 minutes


def voice_wpm(voice: str, root=None) -> int:
    """Words per minute for a Kokoro voice: the median of its last 8 episodes (script words / real MP3 minutes),
    so the length targets track how fast each voice actually speaks."""
    import json as _json
    import statistics
    from pathlib import Path as _P
    voice = (voice or "am_michael").split(":")[-1]
    root = _P(root) if root else _P(__file__).resolve().parent.parent
    seen = []
    try:
        for ln in (root / "data" / "runs.jsonl").read_text("utf-8").splitlines():
            a = ((_json.loads(ln).get("stages") or {}).get("audio") or {})
            if a.get("minutes") and a.get("words") and str(a.get("voice", "")).endswith(voice):
                seen.append(a["words"] / a["minutes"])
    except (OSError, ValueError):
        pass
    try:
        for ln in (root / "data" / "deepdives.jsonl").read_text("utf-8").splitlines():
            r = _json.loads(ln)
            if r.get("minutes") and r.get("words") and str(r.get("voice", "")).endswith(voice):
                seen.append(r["words"] / r["minutes"])
    except (OSError, ValueError):
        pass
    seen = [x for x in seen if 80 <= x <= 220][-8:]
    return int(statistics.median(seen)) if len(seen) >= 3 else DEFAULT_WPM.get(voice, WPM)


_TRAILING_LINKS = re.compile(r"\s*\((?:\[[^\]]+\]\(https?://[^)]+\)(?:,\s*)?)+\)\s*$")


def _strip_links(s: str) -> str:
    s = _TRAILING_LINKS.sub("", s)                                   # "(…source links…)" at the end
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", s)       # inline links -> their label
    return s.replace("**", "").replace("*", "").strip()


def parse_briefing(md: str) -> dict:
    """Pull the spoken parts out of a v2 briefing (works on v1 too, more coarsely)."""
    title = md.splitlines()[0].lstrip("# ").strip() if md.startswith("# ") else "AI Briefing"
    brief = re.search(r"\*\*The day in brief\.\*\* (.+)", md)
    sections = {m.group(1).strip(): m.group(2) for m in re.finditer(r"(?ms)^## (.+?)\n(.*?)(?=^## |\Z)", md)}
    stories = []
    for block in re.split(r"(?m)^### ", sections.get("Must read", sections.get("Full read", "")))[1:]:
        lines = block.strip().splitlines()
        head = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
        who = re.sub(r"\[[^\]]*\]\([^)]*\)", "", lines[1] if len(lines) > 1 else "").replace("**", "").strip(" ·")
        fields = {}
        for ln in lines[2:]:
            if ln.startswith("*Developing story"):
                fields["Developing"] = ln.strip("* ")
                continue
            m = re.match(r"- \*\*(.+?):\*\* (.+)", ln)
            if m and m.group(1) != "Sources":
                key = "Critical pass" if m.group(1) == "Evidence check" else m.group(1)   # one internal name
                val = re.sub(r"\s*\*\(House view: [^)]*\)\*\s*$", "", m.group(2))   # the tag is for readers
                fields[key] = _strip_links(val)
        stories.append({"headline": head, "who": who, **fields})
    worth = [_strip_links(re.sub(r"^- \*\*\d+\.\s*", "- **", ln)[2:])
             for ln in sections.get("Worth knowing", "").splitlines() if ln.startswith("- ")]
    top = [_strip_links(ln[2:]) for ln in sections.get("Top of mind", "").splitlines() if ln.startswith("- ")]
    questions = [_strip_links(ln[2:]) for ln in sections.get("Open questions", "").splitlines() if ln.startswith("- ")]
    return {"title": title, "day_in_brief": brief.group(1).strip() if brief else "", "stories": stories,
            "worth": worth, "top": top, "questions": questions}


def cold_open(md: str) -> str:
    """The first thing heard (critic 2026-10-24): the lead story's sharpest line, before the show's own opening.
    Our read on the first Must read, else its first sentence of what happened. One sentence, at most 35 words."""
    b = parse_briefing(md)
    st = (b["stories"] or [{}])[0]
    for key in ("Our read", "What happened"):
        s = (st.get(key) or "").strip()
        if s:
            first = re.split(r"(?<=[.!?])\s+", s)[0].strip()
            if 6 <= len(first.split()) <= 35:
                return first
    return ""


def opener(title: str, acfg: dict | None = None) -> str:
    """The fixed first line: which episode, who is speaking (Steven, 2026-10-19: the host introduces themselves by
    name), and the AI disclosure. Never left to a model."""
    day = title.split("·", 1)[1].strip() if "·" in title else ""
    day = re.sub(r",\s*\d{4}$", "", day)
    host = ((acfg or {}).get("host_name") or "").strip()
    first = f"This is the AI Briefing for {day}. " if day else "This is the AI Briefing. "
    if host:
        return first + f"I'm {host}. Like everything here, this briefing is written and read by AI, from public sources."
    return first + "It is written and read by AI, from public sources."


OUTRO = ("That's the briefing. The written edition, with every source linked, is on the AI Briefing web page, along "
         "with all past episodes and deep dives; the link is in the show notes. Until tomorrow.")


def diligence_question(day_in_brief: str) -> str:
    """The day in brief ends with one diligence question; return it (or '')."""
    t = re.sub(r"\*+", "", day_in_brief or "")
    m = re.search(r"(?:^|(?<=[.?!])\s+)([^.?!]*\bdiligence\b.*)$", t, re.I | re.S)
    if m:
        return m.group(1).strip()
    qs = re.findall(r"[^.?!]*\?", t)
    return qs[-1].strip() if qs else ""


def _plan_spec(b: dict, cfg: dict) -> list:
    """The podcast format (docs/reviews/2026-10-13-format-review.md): a piece of radio, not the briefing read
    aloud. Today in brief -> up to 4 main stories -> up to 3 quick hits -> a close that repeats the diligence
    question and names one open question -> fixed sign-off. In brief is never read."""
    acfg = cfg.get("audio", {})
    stories = b["stories"][: int(acfg.get("max_stories", 4))]
    hits = b["worth"][: int(acfg.get("max_quick_hits", 3))]
    n, h = len(stories), len(hits)
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    heads = "\n".join(f"- {st['headline']}" for st in stories)
    plan = [("Intro", f"The day in brief: {b['day_in_brief']}\nThe main stories, in order:\n{heads}",
             "At most 140 words.",
             f"Today in brief, spoken right after the host has introduced themselves: an overview of the specific "
             f"stories this episode covers, at the level of what they add up to. For the two or three biggest, say in "
             f"a sentence or two what happened and why it might matter, leading with the most interesting point of "
             f"each (the surprise, the stake, the number that changes the picture), not the background. Lead each one "
             f"with the story itself in plain words (who did what), like a presenter would: no talk about sources, "
             f"evidence quality, self-reporting or the briefing's own process here (those caveats belong in the "
             f"story segments), and do not call them 'threads'. No diligence question here (it comes in the close). Then tell the listener the shape of the episode in one short "
             f"sentence: the main stories, then {'a few quick hits' if h else 'the close'} (no count).")]
    # length from the target (about 10 minutes, decided 2026-10-18) at this voice's measured speed
    budget = int(float(acfg.get("minutes", 10)) * voice_wpm(acfg.get("voice", "am_michael")))
    hit_words = 45
    per = int(acfg.get("story_words") or max(150, min(320, (budget - 140 - (hit_words * h + 15) - 60) // max(1, n))))
    ordinal = ["First", "Second", "Third", "Fourth", "Fifth"]
    for i, st in enumerate(stories, 1):
        fields = {k: v for k, v in st.items() if k not in ("headline", "who")}
        body = "\n".join([f"Headline: {st['headline']}", f"Sources: {st.get('who', '')}"] +
                          [f"{k}: {v}" for k, v in fields.items()])
        last = " This is the last of the main stories; say so." if i == n and n > 1 else ""
        dev = re.search(r"day (\d+)", st.get("Developing", ""))
        if st.get("Today's deep dive"):          # the deep dive tells it: no story twice in one episode
            plan.append((f"Story {i}", body, "About 50 words, never more than 70.",
                         f"Main story {i}, briefly. Open with a spoken signpost ({ordinal[i - 1].lower()} story), say "
                         f"in one or two sentences what happened, then that today's deep dive, right after the "
                         f"briefing, covers it in full.{last}"))
            continue
        if dev and int(dev.group(1)) >= 2:       # covered on earlier days: what's new only (critic 2026-10-24)
            plan.append((f"Story {i}", body, "About 120 words, never more than 140.",
                         f"Main story {i}, a developing story we have covered before. Open with a spoken signpost "
                         f"({ordinal[i - 1].lower()} story) and say it's an update, then only what is new since our "
                         f"earlier coverage and whether it changes our read. No background recap.{last}"))
            continue
        plan.append((f"Story {i}", body, f"About {per} words, never more than {per + 30}.",
                     f"Main story {i}. Open with a spoken signpost ({ordinal[i - 1].lower()} story, without the "
                     f"word 'next'), then: setup with at most two outlets named and a relative date, what is new, how "
                     f"well it holds up, and what we would look at or want to know, as a suggestion. Weave the evidence "
                     f"check, our read and the early-stage point in; do not read their labels.{last}"))
    if hits:
        plan.append(("Quick hits", "\n".join(hits), f"At most {hit_words * h + 15} words.",
                     f"{words.get(h, h).capitalize()} quick hits. Introduce them once in a few words, then each in at "
                     f"most {hit_words} words ending with why it matters. Name at most one outlet each."))
    q = diligence_question(b["day_in_brief"])
    oq = (b["questions"] or [""])[0]
    if q or oq:
        plan.append(("Close", f"The diligence question: {q}\nOne open question to watch: {oq}", "At most 60 words.",
                     "The close: offer the diligence question again in one sentence, as a suggestion, then the one open question to watch "
                     "and what would settle it. No sign-off: that is added separately."))
    plan.append(("Outro", None, "", ""))
    return plan


def _trim_to_cap(out: list, cap_words: int, log) -> tuple:
    """Hard cap: drop the quick hits, then the last main story, until the episode fits. -> (out, dropped)."""
    dropped = []
    total = lambda: sum(len(t.split()) for _, t in out)
    while total() > cap_words:
        names = [n for n, _ in out]
        victim = "Quick hits" if "Quick hits" in names else next((n for n in reversed(names) if n.startswith("Story ")
                                                                 and n != "Story 1"), None)
        if not victim:
            break
        out = [(n, t) for n, t in out if n != victim]
        dropped.append(victim)
    if dropped:
        log.warning("script over the %d-word cap: left out %s", cap_words, ", ".join(dropped))
    return out, dropped


def outro_for(acfg: dict) -> str:
    """The fixed sign-off; on a deep-dive day it hands over to the deep-dive host by name."""
    topic = (acfg.get("_handoff") or "").strip().rstrip(".")
    if not topic:
        return OUTRO
    host = acfg.get("deepdive_host") or "my colleague"
    return (f"That's the briefing. Stay with me: right after this, {host} takes you through today's deep dive, on "
            f"{topic}. You can also read it or listen to it on its own on the AI Briefing web page, where you'll find "
            f"the written edition and every past episode; the link is in the show notes.")


def _plan(b: dict, cfg: dict) -> list:
    """[(name, source_text, length, role)] for the sections the tuning profile asks for."""
    from .tuning import DEPTHS
    acfg = cfg.get("audio", {})
    if acfg.get("format") == "spec":
        return _plan_spec(b, cfg)
    target = int(acfg.get("minutes", 15) * voice_wpm(acfg.get("voice", "")))
    order = acfg.get("sections") or ["intro", "must", "worth", "outro"]
    depth = DEPTHS.get(acfg.get("depth", "analysis"), DEPTHS["analysis"])
    must_share = max(0.2, min(0.95, float(acfg.get("must_share", 65)) / 100))
    speak_crit, speak_ed = acfg.get("speak_critical", True), acfg.get("speak_editor", True)
    n = max(1, len(b["stories"]))
    per_story = depth["words"] or max(110, min(260, int(target * must_share / n)))
    rest = max(80, int(target * (1 - must_share)))
    plan = []
    for sec in order:
        if sec == "intro":
            heads = "\n".join(f"- {st['headline']}" for st in b["stories"])
            plan.append(("Intro", f"The day in brief: {b['day_in_brief']}\nToday's stories, in order:\n{heads}",
                         "At most 110 words.",
                         "The episode's opening summary, spoken right after the fixed first line. Say what matters "
                         "today and why, in the order the stories will come."))
        elif sec == "top_of_mind" and b["top"]:
            plan.append(("Top of mind", "\n".join(b["top"]), f"About {min(160, max(60, rest // 3))} words.",
                         "The day's key takeaways, said once each, before the stories."))
        elif sec == "must":
            for i, st in enumerate(b["stories"], 1):
                fields = {k: v for k, v in st.items() if k not in ("headline", "who")}
                if depth["fields"]:
                    fields = {k: v for k, v in fields.items() if k in depth["fields"]}
                if not speak_crit:
                    fields.pop("Critical pass", None)
                if not speak_ed:
                    for k in ("Editor's view", "Our read"):
                        fields.pop(k, None)
                body = "\n".join([f"Headline: {st['headline']}", f"Sources: {st.get('who', '')}"] +
                                 [f"{k}: {v}" for k, v in fields.items()])
                plan.append((f"Story {i}", body, f"About {per_story} words.",
                             f"Story {i} of {n} in the main section. Open with a transition from what came before."))
        elif sec == "worth" and b["worth"]:
            plan.append(("Worth knowing", "\n".join(b["worth"]), f"About {max(150, int(rest * 0.7))} words.",
                         "A quick round-up of shorter items: one or two sentences each, with a clear turn between them."))
        elif sec == "questions" and b["questions"]:
            plan.append(("Open questions", "\n".join(b["questions"]), f"About {min(140, max(60, rest // 3))} words.",
                         "Open questions to watch: each question and what would settle it."))
        elif sec == "outro":
            plan.append(("Outro", None, "", ""))
    return plan


_BANNED = re.compile(r"\b(?i:Steven)\b(?!\s+Woods)|(?i:\bgood morning\b|\bwelcome back\b|critical pass was|the item does not say|"
                     r"link shortener|\bquote\b.*\bunquote\b)|[·@*]|#(?!\d)|\bSCRUTINY\b")


def banned(text: str) -> str:
    """Greetings, the reader's name, markup and pipeline vocabulary have no place in what is spoken."""
    hits = sorted({m.group(0) for m in _BANNED.finditer(text)})
    return ("banned in audio: " + ", ".join(hits[:4])) if hits else ""


_FIGURE = re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d+)?\s?(?:thousand|million|billion|trillion|bn|mn|[kKmMbBtT])?\b|"
                     r"\d[\d,]*(?:\.\d+)?\s?(?:%|percent\b|x\b|MW\b|GW\b)")


def _fig_norm(f: str) -> str:
    f = f.replace(",", "").replace(" ", "").lower().replace("percent", "%")
    return (f.replace("billion", "b").replace("million", "m").replace("trillion", "t").replace("thousand", "k")
             .replace("bn", "b").replace("mn", "m"))


def figure_mismatch(section: str, text: str) -> str:
    """Money, percentages and units must appear in the story's own section exactly ($20B, not $2B)."""
    have = {_fig_norm(f) for f in _FIGURE.findall(section)}
    bad = [f for f in _FIGURE.findall(text) if _fig_norm(f) not in have]
    return ("figure not in section: " + ", ".join(bad[:3])) if bad else ""


def _section_problem(source: str, text: str, context: str = "") -> str:
    """Names and plain numbers may come from anywhere in today's briefing (transitions link stories);
    figures with units and quotations must come from the story's own section."""
    return ", ".join(x for x in (invented(source + "\n" + context, text), figure_mismatch(source, text),
                                  spelled_figures(text), unquoted(source, text), banned(text)) if x)[:240]


def build_script(llm, md: str, system: str, cfg: dict, log) -> tuple:
    """-> (list of (section_name, text), prompt_version, errors).

    audio.script_mode "episode" (default): one call writes the whole episode, so it reads as one linear piece
    with real transitions; every section is then checked against its own source (names, figures, quotes),
    a failing section is rewritten alone once, and only then falls back to a plain reading of its source.
    "sections": the older one-call-per-section path. The first and last lines are fixed text."""
    from .tuning import persona_text
    acfg = cfg.get("audio", {})
    mode = acfg.get("script_mode", "episode")
    b = parse_briefing(md)
    plan = _plan(b, cfg)
    style = persona_text(acfg)
    tmpl_s, version_s = prompt("script")
    errors = []
    drafts = {}
    version = version_s
    if mode == "episode":
        tmpl_e, version = prompt("script_episode")
        blocks = []
        for i, (name, source, length, role) in enumerate(plan):
            if source is None:
                continue
            blocks.append(f'<section id="s{i}" name="{name}" length="{length}">\nRole: {role}\n{source}\n</section>')
        t0 = time.monotonic()
        try:
            res = _ask(llm, system, tmpl_e.replace("{{sections}}", "\n\n".join(blocks))
                       .replace("{{style}}", ("Voice: " + style) if style else ""), 8000)
            for s in res.get("sections") or []:
                if isinstance(s, dict) and str(s.get("id", "")).startswith("s"):
                    drafts[str(s["id"])] = re.sub(r"https?://\S+", "", str(s.get("text", ""))).replace("*", "").strip()
            log.info("  script episode: %d section(s) in %.1fs", len(drafts), time.monotonic() - t0)
        except Exception as e:  # noqa: BLE001
            log.warning("script episode call failed: %s; writing section by section", e)
            errors.append(f"script episode: {type(e).__name__}: {e}"[:200])
    heads = "\n".join(f"Elsewhere today: {st['headline']}" for st in b["stories"])
    everything = "\n".join(src for _, src, _, _ in plan if src)
    out = []
    for i, (name, source, length, role) in enumerate(plan):
        if source is None:
            out.append((name, outro_for(acfg)))
            continue
        check = source + "\n" + heads                    # a transition may name another of today's stories
        if name == "Intro":                               # the intro previews the stories: their figures count
            check = source + "\n" + everything
        text = drafts.get(f"s{i}", "")
        problem = _section_problem(check, text, everything) if text else "missing"
        if problem:
            if text:
                log.warning("script %s rejected: %s", name, problem)
            fix = ("" if not text else f" A previous draft was rejected for: {problem}. Use only what the section says, "
                   "keep figures exactly as written, and quote only words quoted in the section.")
            try:
                res = _ask(llm, system, tmpl_s.replace("{{section}}", source).replace("{{length}}", length)
                           .replace("{{role}}", ((style + " ") if style else "") + role + fix).replace("{{voices}}", ""), 1500)
                text = re.sub(r"https?://\S+", "", str(res.get("text", ""))).replace("*", "").strip()
                problem = _section_problem(check, text, everything) if text else "empty"
            except Exception as e:  # noqa: BLE001
                problem = f"{type(e).__name__}: {e}"[:200]
            if problem:
                log.warning("script %s rewrite rejected: %s", name, problem)
                if name != "Intro":
                    # never read a template aloud: the section is left out of the episode (the written edition has it)
                    errors.append(f"script {name}: left out of the episode ({problem})"[:300])
                    continue
                text = b["day_in_brief"]                    # the intro falls back to the day in brief as written
                errors.append(f"script {name}: used the day in brief as written ({problem})"[:300])
        if name == "Intro":
            text = opener(b["title"], acfg) + " " + text
        from .links import strip_disclosures
        text = strip_disclosures(text)[0]                   # board seats are private context, never spoken
        out.append((name, text))
    if acfg.get("format") == "spec":
        out, dropped = _trim_to_cap(out, int(float(acfg.get("max_minutes", 12)) * voice_wpm(acfg.get("voice", ""))), log)
        if dropped:
            errors.append(f"script: over the {acfg.get('max_minutes', 10)}-minute cap, left out {', '.join(dropped)}")
    return out, version, errors


_SPELLED = re.compile(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                      r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
                      r"hundred|thousand)(?:[\s-]+(?:point|and|[a-z]+ty|one|two|three|four|five|six|seven|eight|nine))*"
                      r"\s+(?:million|billion|trillion|percent|per cent|dollars|megawatts|gigawatts)\b", re.I)


def spelled_figures(text: str) -> str:
    """Figures written out in words: they cannot be checked against the source, so the script must keep digits."""
    hits = _SPELLED.findall(text)
    return ("spelled-out figure: " + "; ".join(hits[:3])) if hits else ""


_QUOTED = re.compile(r"[\"“]([^\"”]{3,300})[\"”]")


def _norm_q(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("‘", "'")).strip(" .,;:").lower()


def unquoted(source: str, text: str) -> str:
    """Quotations in the script whose words are not in the section."""
    src = _norm_q(source)
    bad = [q for q in _QUOTED.findall(text) if _norm_q(q) not in src]
    return ("quote not in section: " + "; ".join(f'"{q[:40]}"' for q in bad[:2])) if bad else ""


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CAP_RE = re.compile(r"\b[A-Z][a-zA-Z0-9&'’.-]{2,}\b")
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-zA-Z'’-]*)")
_WORDS_TO_NUM = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
                 "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30",
                 "forty": "40", "fifty": "50", "hundred": "100"}
# Generic technical terms and acronyms: a script may use them even when the section doesn't (they name no one).
GENERIC = {"GPU", "CPU", "TPU", "NPU", "AI", "AGI", "LLM", "API", "SDK", "CEO", "CFO", "CTO", "COO", "IPO", "ARR", "NRR",
           "ROI", "SaaS", "VC", "VCs", "US", "UK", "EU", "IP", "CVE", "GDP", "R&D", "PhD", "Wi-Fi", "Internet", "Silicon"}
ALLOWED = {"Good", "Morning", "This", "The", "Our", "First", "Next", "Then", "Finally", "Today", "Tomorrow", "Written", "Read",
           "According", "Here", "That", "There", "They", "These", "Those", "And", "But", "Also", "Second", "Third", "Fourth",
           "Fifth", "Sixth", "Last", "Lastly", "Meanwhile", "Steven", "Briefing", "Monday", "Tuesday", "Wednesday", "Thursday",
           "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December", "Critical", "Editor", "What", "Why", "How", "When", "Where", "Who",
           "Which", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "It", "In", "On", "For",
           "With", "Still", "Yet", "Now", "Some", "Most", "Many", "Both", "Each", "Every", "Nobody", "Nothing", "Until", "Ask",
           "Expect", "Watch", "Note", "Open", "Questions", "Question", "Worth", "Knowing", "Top", "Mind", "Story", "Stories",
           "Woods", "Substack", "Bluesky", "Elsewhere", "Before", "After", "Over", "Back", "Across", "Against", "Despite"}


def invented(section: str, text: str) -> str:
    """Names or numbers in the spoken text that the section never mentions ('' when clean)."""
    src = section.lower()
    src_digits = {re.sub(r"\D", "", n) for n in _NUM_RE.findall(section)}
    bad = []
    for n in _NUM_RE.findall(text):
        d = re.sub(r"\D", "", n)
        if d and d not in src_digits and d.lstrip("0") not in src_digits:
            bad.append(n)
    starts = set(_SENTENCE_START.findall(text))
    for w in _CAP_RE.findall(text):
        w = re.sub(r"['’]s$", "", w)                      # "Friday's" is "Friday"
        if len(w) < 3 or w in ALLOWED or w in starts:
            continue
        stem = w.lower().rstrip(".").replace("’", "'").split("'")[0]
        if w.rstrip("s") in GENERIC or w in GENERIC:
            continue                                      # common technical terms are not names
        if stem[:5] not in src and not (stem.endswith("s") and stem[:-1][:5] in src):
            bad.append(w)
    if "critical read" in text.lower() and "critical pass" not in src:
        bad.append("critical read (none in section)")
    t2, s2 = text.lower().replace("’", "'"), src.replace("’", "'")
    if ("editor's view" in t2 or "our read" in t2) and "editor's view" not in s2 and "our read" not in s2:
        bad.append("our read (none in section)")
    return ", ".join(dict.fromkeys(bad))[:200]


def plain_reading(name: str, section: str) -> str:
    """A model-free spoken version: the section's own sentences, labels turned into speech."""
    lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
    out = []
    for ln in lines:
        k, _, v = ln.partition(": ")
        if ln.startswith("Headline:"):
            out.append(("First, " if name == "Story 1" else "Next, ") + v.rstrip(".") + ".")
        elif ln.startswith("Sources:"):
            out.append(f"Reported by {v}." if v else "")
        elif ln.startswith("What happened:"):
            out.append(v)
        elif ln.startswith("Critical pass:"):
            out.append("Checking the evidence: " + v)
        elif ln.startswith(("Editor's view:", "Our read:")):
            out.append("Our read: " + v)
        elif ln.startswith(("Agenda:", "Developing")):
            out.append(v if ln.startswith("Agenda") else ln.strip("*"))
        elif ln.startswith("The day in brief:"):
            out.append(v)
        elif ln.startswith("# ") or ln.startswith("AI Briefing"):
            out.append("This is the " + ln.lstrip("# ").replace("·", "for") + ". Written and read by AI from public sources.")
        else:
            out.append(ln.lstrip("- "))
    text = " ".join(x for x in out if x)
    return re.sub(r"\s+", " ", text).strip()


def script_markdown(title: str, parts: list, meta: dict) -> str:
    words = sum(len(t.split()) for _, t in parts)
    L = [f"# Spoken script · {title}", "",
         f"*~{words} words, about {words / WPM:.0f} minutes · script: {meta.get('script_model', '')} · "
         f"voice: {meta.get('voice', '')}*", ""]
    for name, text in parts:
        L += [f"## {name}", "", text, ""]
    return "\n".join(L)


# ---------- TTS ----------

def _write_wav(path: Path, samples, rate: int) -> None:
    import numpy as np
    a = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((a * 32767).astype("<i2").tobytes())


class Kokoro:
    name = "kokoro"
    rate = 24000

    def __init__(self, voice: str, speed: float = 1.0, lang: str = "a"):
        self.voice, self.speed, self.lang = voice, speed, lang
        self._pipe = None

    def check(self):
        try:
            import kokoro  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Kokoro not installed. Run: ./np setup (needs Python 3.10+; brew install python@3.12 espeak-ng)") from e

    def synth(self, text: str, out_wav: Path) -> None:
        import numpy as np
        if self._pipe is None:
            from kokoro import KPipeline
            self._pipe = KPipeline(lang_code=self.lang)
        chunks = []
        for _, _, audio in self._pipe(text, voice=self.voice, speed=self.speed, split_pattern=r"\n+"):
            a = audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)
            chunks += [a, np.zeros(int(self.rate * 0.25), dtype="float32")]
        _write_wav(out_wav, np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32"), self.rate)


class MacSay:
    name = "say"

    def __init__(self, voice: str, speed: float = 1.0):
        self.voice, self.wpm = voice, int(175 * speed)

    def check(self):
        if not shutil.which("say"):
            raise RuntimeError("macOS `say` not found (only available on a Mac)")

    def synth(self, text: str, out_wav: Path) -> None:
        aiff = out_wav.with_suffix(".aiff")
        args = ["say", "-r", str(self.wpm), "-o", str(aiff)] + (["-v", self.voice] if self.voice else [])
        subprocess.run(args, input=text, text=True, check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "24000", str(out_wav)],
                       check=True)
        aiff.unlink(missing_ok=True)


def engine_from(cfg: dict, voice: str = None):  # noqa: D103
    a = cfg.get("audio", {})
    eng = a.get("engine", "kokoro")
    if eng == "say":
        return MacSay(voice or a.get("say_voice", ""), a.get("speed", 1.0))
    return Kokoro(voice or a.get("voice", "af_heart"), a.get("speed", 1.0), a.get("lang", "a"))


def _silence(path: Path, seconds: float, rate: int = 24000):
    _write_wav(path, [0.0] * int(rate * seconds), rate)


def render_mp3(engine, parts: list, out_mp3: Path, title: str = "", bitrate: str = "64k") -> float:
    """TTS each section, join with short pauses, encode MP3. Returns duration in minutes."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Run: brew install ffmpeg")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        files = []
        pause = td / "pause.wav"
        _silence(pause, 0.9)
        for i, (_, text) in enumerate(parts):
            w = td / f"{i:02d}.wav"
            engine.synth(text, w)
            files += [w, pause]
        lst = td / "list.txt"
        lst.write_text("".join(f"file '{f}'\n" for f in files))
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        # loudness normalised to podcast level (-16 LUFS, true peak -1.5 dB): critic 2026-10-24, free and local
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "24000",
                        "-ac", "1", "-b:a", bitrate, "-metadata", f"title={title}", "-metadata", "artist=AI Briefing",
                        str(out_mp3)], check=True)
        frames = sum(wave.open(str(f)).getnframes() for f in files)
        try:                                     # per-section seconds and words: a section that came out silent or
            import json as _json                 # clipped shows (10-27: "the audio has no introduction")
            secs = [{"part": n, "words": len(t.split()),
                     "seconds": round(wave.open(str(td / f"{i:02d}.wav")).getnframes() / 24000, 1)}
                    for i, (n, t) in enumerate(parts)]
            for x in secs:
                x["short"] = x["words"] >= 20 and x["seconds"] < x["words"] / 4.5    # < ~40% of normal speed
            out_mp3.with_suffix(".sections.json").write_text(_json.dumps(secs, indent=1) + "\n", "utf-8")
        except Exception:  # noqa: BLE001 - a check, never a failure
            pass
    return frames / 24000 / 60


def combine(parts_mp3: list, out_mp3: Path, title: str = "", bitrate: str = "64k", gap: float = 1.2) -> float:
    """One podcast file: the briefing, a short pause, then the deep dive (Steven, 2026-10-19: in the podcast the deep
    dive follows directly, through the host's hand-off). -> minutes."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Run: brew install ffmpeg")
    n = len(parts_mp3)
    ins = [x for f in parts_mp3 for x in ("-i", str(f))]
    filt = "".join(f"[{i}:a]aresample=24000,aformat=channel_layouts=mono[a{i}];" for i in range(n))
    filt += "".join(f"anullsrc=r=24000:cl=mono,atrim=duration={gap}[g{i}];" for i in range(n - 1))
    seq = "".join(f"[a{i}]" + (f"[g{i}]" if i < n - 1 else "") for i in range(n))
    filt += seq + f"concat=n={2 * n - 1}:v=0:a=1[out]"
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *ins, "-filter_complex", filt, "-map", "[out]",
                    "-ac", "1", "-b:a", bitrate, "-metadata", f"title={title}", "-metadata", "artist=AI Briefing",
                    str(out_mp3)], check=True)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_mp3)],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()) / 60, 1)
    except ValueError:
        return 0.0


def deliver(cfg: dict, mp3: Path, log) -> str:
    from .env import staging
    if staging():                                       # never overwrite the owner's iCloud copy from a dev run
        return "staging: not delivered"
    target = os.path.expanduser(cfg.get("audio", {}).get("icloud_dir", ""))
    if not target:
        return "no delivery folder configured"
    if not Path(target).is_dir():
        log.warning("delivery folder missing: %s", target)
        return f"folder missing: {target}"
    shutil.copy2(mp3, Path(target) / mp3.name)
    return f"copied to {target}"
