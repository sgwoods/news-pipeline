"""Short texts readers see first must agree with the checked text and the sources (2026-10-23).

On 2026-10-23 the deep dive's body was right (a $21M figure was an investor's post about one legal-AI company;
another company did disclose ARR), but its summary and "Why today" lines said otherwise. The why-today line had
been written the day before, as a topic suggestion, and was never checked. And the previous day's briefing called
that investor the company's "founder" in an unsourced Agenda line. These checks catch those three patterns:

- check_header(text, body, corpus): for summaries and why-today lines. Each sentence is dropped if:
  - a figure in it isn't in the body;
  - the sentence names none of the companies or people the body ties that figure to;
  - it says something was not disclosed that the body or the sources say was.
- check_roles(text, source): for Agenda lines. A claim that someone is a founder, CEO, investor, board member or
  employee needs that role in the item's own source text; otherwise the line becomes neutral.
- check_briefing(md, corpus) (v0.1.14): the daily briefing's day in brief and Top of mind, checked like a deep dive's
  summary against the edition's own body (Must read, Worth knowing, In brief...). A figure the body doesn't carry
  may still stand if a source sentence ties it to the same names. A Top of mind bullet whose lead or every other
  sentence fails is dropped whole.
- cross_day(md, earlier): flags only. A "not disclosed" claim in today's edition when an earlier edition (14 days)
  gave that figure for the same company. Logged and shown in ./np consistency; a day can be right about its own
  sources and still contradict the record, so this is for review, not a cut.
- audit(root, days): all of the above over published editions, dry run (./np consistency all).
- align_deepdive(md, title, body, head) (v0.2.5, critic 2026-10-24): the briefing against the same day's deep dive.
  A Must read the deep dive covers shrinks to a pointer (no story told twice in one episode), a "not disclosed"
  line the deep dive answers is dropped from the day in brief and Top of mind, and lines that call something
  unverified when the deep dive names it are flagged for review.
"""
from __future__ import annotations

import re

_FIG = re.compile(r"(?:[$€£]\s?\d[\d,.]*(?:\s?(?:[BMKTbmkt]\b|bn\b|billion|million|trillion))?|\d[\d,.]*\s?%)")
_SENT = re.compile(r"(?<=[.!?])\s+")
_NAME = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]+(?:[-.][A-Za-z0-9]+)*|[A-Z]{2,})\b")
_COMMON = {"The", "A", "An", "On", "In", "At", "Of", "And", "But", "Or", "It", "Its", "This", "That", "These", "Those",
           "We", "Our", "Their", "They", "He", "She", "His", "Her", "Today", "Why", "What", "How", "Then", "So", "If",
           "AI", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
           "Here", "There", "When", "With", "For", "From", "Also", "Both", "Each", "One", "Two", "Three", "Start",
           "Fortune", "Series", "Inc", "US", "USD", "CAD", "ARR", "X"}
_NOT_DISCLOSED = re.compile(r"(?:\b(?:no|without)\s+(?:disclosed|published|reported|public|audited)\s+|\bundisclosed\s+|"
                            r"\b(?:no|without)\s+(?=(?:revenue|ARR|margin|margins|valuation|profit|retention)\b))"
                            r"((?:[A-Za-z][A-Za-z-]*)(?:\s*(?:,|and|or)\s*[A-Za-z][A-Za-z-]*){0,4})", re.I)
_ROLE = re.compile(r"\b(co-?founder|founder|founded|CEO|chief executive|CTO|COO|investor in|investors? (?:at|of)|"
                   r"backer of|board member|board seat|chair(?:man|woman)? of|employee of|works (?:at|for))\b", re.I)
_SYNONYMS = {"arr": ["ARR", "annual recurring revenue", "recurring revenue"],
             "revenue": ["revenue", "ARR", "annual recurring revenue", "sales"],
             "valuation": ["valuation", "valued at", "post-money", "pre-money"]}
NEUTRAL_AGENDA = "The author's role and any stake aren't stated in the source."


def _key(f: str) -> str:
    f = f.lower().replace(" ", "").replace(",", "")
    for a, b in (("billion", "b"), ("bn", "b"), ("million", "m"), ("trillion", "t")):
        f = f.replace(a, b)
    return f.rstrip(".")


_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_SCALE = {"thousand": "K", "million": "M", "billion": "B", "trillion": "T"}
_WORDNUM = re.compile(r"\b((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                      r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
                      r"ninety|hundred|point|and)[\s-]+)+)(thousand|million|billion|trillion)(?:\s+dollars)?\b", re.I)


def _words_value(words: str):
    total, cur, frac, in_frac = 0, 0, "", False
    for w in re.split(r"[\s-]+", words.lower().strip()):
        if not w or w == "and":
            continue
        if w == "point":
            in_frac = True
        elif in_frac and w in _ONES:
            frac += str(_ONES[w])
        elif w in _ONES:
            cur += _ONES[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur *= 100
        else:
            return None
    total += cur
    return f"{total}.{frac}" if frac else str(total)


def spoken_figures(text: str) -> str:
    """'twenty-one million dollars' -> '$21M', 'eight point eight billion' -> '$8.8B' (scripts spell figures out)."""
    def sub(m):
        v = _words_value(m.group(1))
        return f"${v}{_SCALE[m.group(2).lower()]}" if v else m.group(0)
    return _WORDNUM.sub(sub, text or "")


def _names(s: str) -> set:
    return {w for w in _NAME.findall(s) if w not in _COMMON and not w.isdigit()}


def _lines_sents(text: str) -> list:
    return [s for ln in (text or "").split("\n") for s in _SENT.split(ln) if s.strip()]


def _disclosed(term: str, names: set, hay: str) -> str:
    """A sentence in hay that gives a figure for this term about the same names (and isn't itself a 'not disclosed')."""
    forms = _SYNONYMS.get(term.lower(), [term])
    for s in _lines_sents(hay):
        if not _FIG.search(s) or _NOT_DISCLOSED.search(s) or re.search(r"\bnot (?:disclosed|stated|given)\b", s, re.I):
            continue
        if s.rstrip().endswith("?"):                      # a question asks for the figure; it doesn't give it
            continue
        if names and not (names & _names(s)):
            continue
        for f in forms:
            m = re.search(rf"\b{re.escape(f)}\b", s, re.I)
            if not m or re.search(rf"\b(?:no|not|lacks?|lacking|without|absent|missing)\b[^.]{{0,40}}\b{re.escape(f)}\b",
                                  s, re.I):
                continue
            if any(abs(fm.start() - m.start()) < 60 for fm in _FIG.finditer(s)):
                return s
    return ""


def check_header(text: str, body: str, corpus: str = "") -> tuple:
    """-> (kept text, notes). Sentences that contradict or misattribute against the checked body are dropped."""
    body = spoken_figures(body)
    body_sents = [s for s in _SENT.split(body or "") if s.strip()]
    hay = f"{body}\n{corpus}"
    keep, notes = [], []
    for sent in _SENT.split(text or ""):
        if not sent.strip():
            continue
        why = ""
        for f in _FIG.findall(sent):
            k = _key(f)
            tied = [b for b in body_sents if k in {_key(x) for x in _FIG.findall(b)}]
            if not tied:
                why = f"{f.strip()} isn't in the checked body"
                break
            who = set().union(*(_names(b) for b in tied))
            if who and not (who & _names(sent)):
                why = (f"{f.strip()} is tied in the body to {', '.join(sorted(who)[:3])}, which this sentence doesn't "
                       f"name")
                break
        if not why:
            for m in _NOT_DISCLOSED.finditer(sent):
                for term in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", m.group(1)):
                    term = term.strip()
                    if len(term) < 3:
                        continue
                    if _disclosed(term, _names(sent), hay):
                        why = f"says {term} wasn't disclosed, but the body or a source gives it"
                        break
                if why:
                    break
        if why:
            notes.append(f"header sentence dropped ({why}): {sent[:120]}")
        else:
            keep.append(sent)
    return " ".join(keep).strip(), notes


def check_roles(text: str, source: str) -> tuple:
    """-> (agenda text, note). A role claim needs the role in the item's own source text."""
    m = _ROLE.search(text or "")
    if not m:
        return text, ""
    if re.search(rf"\b{re.escape(m.group(1).lower().rstrip('s'))}", (source or "").lower()):
        return text, ""
    return NEUTRAL_AGENDA, f"unsourced role claim ({m.group(1)}) replaced: {text[:100]}"


_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BOLD_LEAD = re.compile(r"^\s*-\s*\*\*(.+?)\*\*\s*(.*)$")


def _plain(s: str) -> str:
    s = _LINK.sub(lambda m: "" if re.fullmatch(r"\d+|source", m.group(1)) else m.group(1), s or "")
    return re.sub(r"[*_`]", "", s).strip()


def _sentences(s: str) -> list:
    return [x for x in _SENT.split(s or "") if x.strip()]


def _split(md: str):
    """-> (before, day_in_brief_line_index, top_start, top_end, lines). Indexes into md's lines; -1 when absent."""
    lines = md.split("\n")
    from .textutil import QUESTION_LEAD, TOP_MERGED
    dib = next((i for i, x in enumerate(lines) if x.startswith(("**The day in brief.**", QUESTION_LEAD))), -1)
    top = next((i for i, x in enumerate(lines) if x.strip() in ("## Top of mind", f"## {TOP_MERGED}")), -1)
    end = next((i for i in range(top + 1, len(lines)) if lines[i].startswith("## ")), len(lines)) if top >= 0 else -1
    return lines, dib, top, end


def _body(lines: list, top: int, end: int) -> str:
    start = end if top >= 0 else next((i for i, x in enumerate(lines) if x.startswith("## ")), len(lines))
    keep = [x for x in lines[start:] if not x.startswith(("## Recommended", "## Open questions"))]
    return _plain("\n".join(keep))


def _units(body_md: str) -> list:
    """Story blocks (### sections) and stand-alone bullets, as plain text: a figure belongs to its whole story."""
    units, cur = [], []
    for ln in body_md.split("\n"):
        if ln.startswith(("### ", "## ")):
            if cur:
                units.append(" ".join(cur))
            cur = [ln] if ln.startswith("### ") else []
        elif ln.startswith("- ") and not cur:
            units.append(ln)
        elif cur:
            cur.append(ln)
    if cur:
        units.append(" ".join(cur))
    return [_plain(u) for u in units if u.strip()]


def _check_sentence(sent: str, units: list, corpus: str, context: str = "") -> str:
    """'' if the sentence stands, else why not. context: the text around it (the bullet's lead, the previous sentence)."""
    plain = _plain(sent)
    if not plain:
        return ""
    names = _names(plain) | _names(_plain(context))
    for f in _FIG.findall(spoken_figures(plain)):
        k = _key(f)
        tied = [u for u in units if k in {_key(x) for x in _FIG.findall(spoken_figures(u))}]
        if not tied:
            src = [s for s in _lines_sents(corpus) if k in {_key(x) for x in _FIG.findall(s)}]
            if not src:
                return f"{f.strip()} is in neither the body nor the sources"
            if names and not any(names & _names(s) for s in src):
                return f"{f.strip()} appears in the sources only about others"
            continue
        who = set().union(*(_names(u) for u in tied))
        if plain.rstrip().endswith("?"):                  # a question may use a figure as a hypothetical
            continue
        if names and who and not (names & who):
            return f"{f.strip()} belongs to a story about {', '.join(sorted(who)[:3])}, which isn't named here"
    for m in _NOT_DISCLOSED.finditer(plain):
        for term in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", m.group(1)):
            term = term.strip()
            if len(term) >= 3:
                hit = _disclosed(term, names, "\n".join(units) + "\n" + corpus)
                if hit:
                    return f"says {term} wasn't disclosed, but this gives it: {hit[:90]}"
    return ""


def check_briefing(md: str, corpus: str = "") -> tuple:
    """-> (md, notes). The day in brief and Top of mind must agree with the edition's body and its sources."""
    lines, dib, top, end = _split(md)
    start = end if top >= 0 else next((i for i, x in enumerate(lines) if x.startswith("## ")), len(lines))
    if top >= 0 and top < dib < end:                   # merged top: the question sits under its bullets
        end = dib
    units = _units("\n".join(x for x in lines[start:]))
    notes = []
    if dib >= 0:
        lead = "**The day in brief.**" if lines[dib].startswith("**The day in brief.**") else lines[dib].split(":**", 1)[0] + ":**"
        out, prev = [], ""
        for s in _sentences(lines[dib][len(lead):].strip()):
            why = _check_sentence(s, units, corpus, prev)
            if why:
                notes.append(f"day in brief: dropped ({why}): {_plain(s)[:160]}")
            else:
                out.append(s)
            prev = s
        lines[dib] = f"{lead} {' '.join(out)}".rstrip()
    if top >= 0:
        for i in range(top + 1, end):
            m = _BOLD_LEAD.match(lines[i])
            if not m:
                continue
            title, rest = m.group(1), m.group(2)
            links = " ".join(re.findall(r"\[\d+\]\([^)]*\)", rest))
            text = re.sub(r"\s*\[\d+\]\([^)]*\)", "", rest).strip()
            why = _check_sentence(title, units, corpus, text)
            if why:
                notes.append(f"Top of mind: bullet dropped ({why}): {_plain(title)[:160]}")
                lines[i] = None
                continue
            kept = []
            for s in _sentences(text):
                w = _check_sentence(s, units, corpus, title + " " + " ".join(kept))
                if w:
                    notes.append(f"Top of mind: dropped ({w}): {_plain(s)[:160]}")
                else:
                    kept.append(s)
            if text and not kept:
                notes.append(f"Top of mind: bullet dropped (nothing in it held up): {_plain(title)[:160]}")
                lines[i] = None
                continue
            lines[i] = f"- **{title}** {' '.join(kept)}" + (f" {links}" if links else "")
    return "\n".join(x for x in lines if x is not None), notes


def cross_day(md: str, earlier: dict) -> list:
    """{day: md} of earlier editions -> flags: today says X wasn't disclosed for a company an earlier day gave X for."""
    out, seen = [], set()
    for sent in _lines_sents(_plain(md)):
        names = _names(sent)
        if not names:
            continue
        for m in _NOT_DISCLOSED.finditer(sent):
            for term in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", m.group(1)):
                term = term.strip()
                if len(term) < 3 or (term, sent) in seen:
                    continue
                for day, old in sorted(earlier.items(), reverse=True):
                    hit = _disclosed(term, names, _plain(old))
                    if hit:
                        seen.add((term, sent))
                        out.append({"term": term, "sentence": sent[:200], "earlier_day": day, "earlier": hit[:200]})
                        break
    return out


def audit(root, days: list | None = None, log=print) -> dict:
    """Dry run over published editions: what check_briefing, check_roles and cross_day would change or flag."""
    import json
    from pathlib import Path
    from . import factcheck
    root = Path(root)
    files = sorted((root / "briefings").glob("????-??-??.md"))
    if days:
        files = [f for f in files if f.stem in days]
    texts = {f.stem: f.read_text("utf-8") for f in sorted((root / "briefings").glob("????-??-??.md"))}
    rep = {"days": [], "deepdives": []}
    for f in files:
        day = f.stem
        md = texts[day]
        try:
            rows = [json.loads(x) for x in (root / "data" / "stories" / f"{day}.jsonl").read_text("utf-8").splitlines() if x.strip()]
            stories = rows[-1]["stories"] if rows else []
        except (OSError, ValueError, KeyError):
            stories = []
        ids = [i for s in stories for i in s.get("ids", [])]
        try:
            corpus = " ".join(factcheck.corpus(root, ids)) if ids else ""
        except Exception:  # noqa: BLE001
            corpus = ""
        _, notes = check_briefing(md, corpus)
        roles = []
        for line in md.split("\n"):                       # Agenda lines in the published text
            if line.startswith("- **Agenda:**") and _ROLE.search(line):
                txt = line.split("**Agenda:**", 1)[1].strip()
                if not re.search(rf"\b{re.escape(_ROLE.search(txt).group(1).lower().rstrip('s'))}", corpus.lower()):
                    roles.append(txt[:160])
        d0 = __import__("datetime").date.fromisoformat(day)
        earlier = {k: v for k, v in texts.items()
                   if 0 < (d0 - __import__("datetime").date.fromisoformat(k)).days <= 14}
        flags = cross_day(md, earlier)
        rep["days"].append({"day": day, "header": notes, "roles": roles, "cross_day": flags})
    for f in sorted((root / "briefings" / "deepdives").glob("????-??-??.md")):
        if days and f.stem not in days:
            continue
        md = f.read_text("utf-8")
        scr = f.with_suffix(".script.md")
        body = scr.read_text("utf-8") if scr.exists() else ""
        lines = md.split("\n")
        summ = next((x for x in lines[3:8] if x.strip() and not x.startswith(("*", "#"))), "")
        why = next((x for x in lines if x.startswith("**Why today.**")), "").replace("**Why today.**", "").strip()
        srcs = md.split("## Sources", 1)[1] if "## Sources" in md else ""
        notes = []
        for label, txt in (("summary", summ), ("why today", why)):
            for s in _sentences(_plain(txt)):
                w = _check_sentence(s, [_plain(body)], _plain(srcs), txt)
                if w:
                    notes.append(f"{label}: ({w}): {s[:140]}")
        rep["deepdives"].append({"day": f.stem, "header": notes})
    return rep


_UNSETTLED = re.compile(r"\b(unverified|unconfirmed|remains? unclear|not (?:yet )?(?:named|identified|confirmed|"
                        r"disclosed)|unknown|undisclosed)\b", re.I)
_SETTLED = re.compile(r"\b(named|names|said it used|used|confirmed|identified|according to|says|said)\b", re.I)
_GENERIC = {"AI", "Today", "Deep", "Briefing", "Story", "Our", "Evidence", "What", "Who", "Why", "How", "The"}


def _distinct(s: str) -> set:
    return {n for n in _names(s) if n not in _GENERIC and len(n) > 2}


def _figs(s: str) -> set:
    return {_key(f) for f in _FIG.findall(spoken_figures(s))}


def covers(story: str, dd_head: str) -> bool:
    """Does the deep dive (title, why-today, summary) cover this Must-read story (headline + what happened)?"""
    shared = _distinct(story) & _distinct(dd_head)
    return len(shared) >= 2 or (len(shared) >= 1 and bool(_figs(story) & _figs(dd_head)))


def align_deepdive(md: str, title: str, body: str, head: str) -> tuple:
    """-> (md, notes, flags). See the module docstring."""
    body = spoken_figures(body or "")
    notes, flags = [], []
    covered = set()                                          # distinctive names of the stories the deep dive tells
    lines = md.split("\n")
    try:
        mi = lines.index("## Must read")
    except ValueError:
        mi = -1
    if mi >= 0 and title:
        end = next((i for i in range(mi + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        i = mi + 1
        while i < end:
            if lines[i].startswith("### "):
                j = next((k for k in range(i + 1, end) if lines[k].startswith("### ")), end)
                block = lines[i:j]
                what = next((ln for ln in block if ln.startswith("- **What happened:**")), "")
                if covers(block[0] + " " + what, f"{title}. {head}") and not any("Today's deep dive" in ln for ln in block):
                    first = _SENT.split(what.split(":**", 1)[1].strip())[0] if what else ""
                    keep = [ln for ln in block if not ln.startswith("- **") or ln.startswith("- **Sources:**")]
                    new = keep[:3] + ([f"- **What happened:** {first}"] if first else []) + \
                        [f"- **Today's deep dive:** \"{title}\" covers this story in full, right after the briefing."] + \
                        [ln for ln in keep[3:] if ln.strip()] + [""]
                    lines[i:j] = new
                    end += len(new) - len(block)
                    notes.append(f"Must read shortened to a pointer (the deep dive covers it): {block[0][4:120]}")
                    covered |= _distinct(block[0])
                    j = i + len(new)
                i = j
            else:
                i += 1
    md = "\n".join(lines)
    out_lines = md.split("\n")
    _, dib, top, tend = _split(md)
    header_idx = set(range(top + 1, tend)) if top >= 0 else set()
    if dib >= 0:
        header_idx.add(dib)
    for idx, ln in enumerate(out_lines):
        sents = _sentences(ln)
        kept = []
        for s in sents:
            plain = _plain(s)
            names = _distinct(plain)
            drop = False
            for m in _NOT_DISCLOSED.finditer(plain):
                for term in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", m.group(1)):
                    term = term.strip()
                    hit = _disclosed(term, names, body) if len(term) >= 3 and names else ""
                    if hit:
                        if idx in header_idx:
                            drop = True
                            notes.append(f"dropped: says {term} wasn't disclosed; the deep dive gives it: {plain[:120]}")
                        else:
                            flags.append(f"says {term} wasn't disclosed; the deep dive gives it: {plain[:120]}")
                        break
                if drop:
                    break
            q_idx = idx > tend and out_lines[idx].startswith("- **") and "Open questions" in "\n".join(out_lines[:idx])
            if not drop and _UNSETTLED.search(plain) and (idx in header_idx or q_idx) and names & covered:
                flags.append(f"a line about the story the deep dive covers calls something unsettled; check it against "
                             f"the deep dive: '{plain[:140]}'")
            elif not drop and _UNSETTLED.search(plain) and len(names) >= 1:
                for ds in _lines_sents(body):
                    if len(names & _distinct(ds)) >= 2 and _SETTLED.search(ds) and not _UNSETTLED.search(ds):
                        flags.append(f"calls something unsettled that the deep dive states: '{plain[:100]}' vs "
                                     f"'{ds[:100]}'")
                        break
            if not drop:
                kept.append(s)
        if len(kept) != len(sents):
            out_lines[idx] = " ".join(kept) if kept else ""
    # a Top of mind bullet left as a bare lead is removed
    out_lines = [ln for ln in out_lines if not re.fullmatch(r"\s*-\s*\*\*[^*]+\*\*\s*", ln)]
    return "\n".join(out_lines), notes, flags
