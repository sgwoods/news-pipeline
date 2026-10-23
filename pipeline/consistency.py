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
_NOT_DISCLOSED = re.compile(r"(?:\b(?:no|without)\s+(?:disclosed|published|reported|public)\s+|\bundisclosed\s+)"
                            r"((?:[A-Za-z][A-Za-z-]*)(?:\s*(?:,|and|or)\s*[A-Za-z][A-Za-z-]*){0,4})", re.I)
_DISCLOSED_NEAR = r"(?:says|said|stands at|published|disclosed|reported|reports|of more than|above|over|\$|\d)"
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
                    forms = _SYNONYMS.get(term.lower(), [term])
                    if any(re.search(rf"\b{re.escape(f)}\b[^.]{{0,80}}{_DISCLOSED_NEAR}", hay, re.I) for f in forms):
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
