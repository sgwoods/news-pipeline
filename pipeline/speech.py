"""The speech layer: turn the written audio script into what the voice says, deterministically.

The written script (briefings/<day>.script.md) is the source of truth and stays readable: figures keep
their written form ("$20B", "22%", "GPT-6.1"). Right before synthesis this module produces the spoken
form, without any model:

  expand()     money, percentages, units, ranges, multipliers, versions and a few abbreviations -> words
  pronounce()  names and terms from pronunciations.yaml -> respellings the voice gets right
  spoken()     both, in that order

The spoken form is saved next to the MP3 as briefings/<day>.spoken.txt so every word the voice said can
be checked against the script. Nothing here touches the written briefing or the email.
"""
from __future__ import annotations

import re
from pathlib import Path

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
SCALES = [(10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")]
SUFFIX = {"k": "thousand", "K": "thousand", "m": "million", "M": "million", "mn": "million", "b": "billion",
          "B": "billion", "bn": "billion", "t": "trillion", "T": "trillion", "tn": "trillion",
          "thousand": "thousand", "million": "million", "billion": "billion", "trillion": "trillion"}
CURRENCY = {"$": "dollars", "US$": "US dollars", "C$": "Canadian dollars", "CA$": "Canadian dollars", "€": "euros",
            "£": "pounds", "¥": "yen"}
UNITS = {"GW": "gigawatts", "MW": "megawatts", "kW": "kilowatts", "TWh": "terawatt hours", "GWh": "gigawatt hours",
         "MWh": "megawatt hours", "GB": "gigabytes", "TB": "terabytes", "PB": "petabytes", "MB": "megabytes",
         "ms": "milliseconds", "km": "kilometres", "nm": "nanometre"}
ABBREV = {"SOTA": "state of the art", "YoY": "year over year", "QoQ": "quarter over quarter", "e.g.": "for example",
          "i.e.": "that is", "vs.": "versus", "vs": "versus", "approx.": "about", "~": "about ", "≈": "about ",
          "&": "and", "w/": "with"}


def int_words(n: int) -> str:
    if n < 0:
        return "minus " + int_words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" " + int_words(n % 100) if n % 100 else "")
    for size, word in SCALES:
        if n >= size:
            head, rest = divmod(n, size)
            return int_words(head) + " " + word + (" " + int_words(rest) if rest else "")
    return str(n)


def num_words(s: str) -> str:
    """'1,300' -> 'one thousand three hundred'; '1.3' -> 'one point three'; '0.72' -> 'zero point seven two'."""
    s = s.replace(",", "")
    if "." in s:
        whole, frac = s.split(".", 1)
        return int_words(int(whole or 0)) + " point " + " ".join(ONES[int(d)] for d in frac if d.isdigit())
    return int_words(int(s)) if s.isdigit() else s


def year_words(y: int) -> str:
    if 2000 <= y <= 2009:
        return int_words(y)
    hi, lo = divmod(y, 100)
    return int_words(hi) + " " + (("oh " + ONES[lo]) if 0 < lo < 10 else int_words(lo) if lo else "hundred")


NUM = r"\d[\d,]*(?:\.\d+)?"
END = r"(?![\w]|\.\d)"
_SUF = r"(thousand|million|billion|trillion|bn|mn|tn|[kKmMbBtT])\b"
_MONEY = re.compile(r"(?<![\w$])(US\$|C\$|CA\$|\$|€|£|¥)\s?(" + NUM + r")(?:\s?" + _SUF + r")?"
                    r"(?:\s?(?:–|-|to)\s?(?:US\$|C\$|\$|€|£)?(" + NUM + r")(?:\s?" + _SUF + r")?)?")
_PCT = re.compile(r"(" + NUM + r")(?:\s?(?:–|-|to)\s?(" + NUM + r"))?\s?%")
_MULT = re.compile(r"(?<![\w.])(" + NUM + r")\s?[x×](?![\w])")
_UNIT = re.compile(r"(?<![\w.])(" + NUM + r")\s?(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b")
_SCALED = re.compile(r"(?<![\w.$])(" + NUM + r")\s?(bn|mn|tn|[BMKT])\b")
_VERSION = re.compile(r"\b([A-Z][A-Za-z]*)-(\d+(?:\.\d+)*)([a-z]?)\b")      # GPT-6.1, GLM-5.3
_DOTTED = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?=\s?(?:[A-Z][a-z]|Pro|Max|Flash|Ultra|Mini|Sol|Astra|Argon)\b)")
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_RANGE = re.compile(r"(?<![\w.])(" + NUM + r")\s?[–-]\s?(" + NUM + r")(?![\w%]|\.\d)")
_PLAIN = re.compile(r"(?<![\w.])(" + NUM + r")" + END)


NOT_NOUN = {"of", "in", "for", "to", "and", "or", "from", "per", "a", "an", "the", "on", "at", "by", "with", "as",
            "is", "was", "were", "are", "be", "been", "this", "that", "last", "each", "into", "over", "than", "since",
            "after", "before", "while", "but", "so", "if", "when", "which", "who", "it", "its", "they", "their",
            "annualized", "annually", "total", "more", "less", "worth", "according", "reportedly", "apiece",
            "combined", "earlier", "later", "already", "now", "next", "up", "down", "plus", "or", "nor", "yet",
            "has", "had", "have", "will", "would", "could", "may", "might", "can", "should", "not", "only", "just",
            "last", "this", "then", "there", "here", "about", "against", "under", "above", "below", "through"}


def _adjectival(after: str) -> bool:
    """True when the figure modifies the next word ("$5B loan", "8 GW campus")."""
    m = re.match(r"\s+([A-Za-z][\w-]*)", after)
    if not m:
        return False
    w = m.group(1)
    if w.lower() in NOT_NOUN:
        return False
    return w[0].islower() or w in ("Series",)


def _money(m: re.Match) -> str:
    cur, a, sa, b, sb = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    unit = CURRENCY.get(cur, "dollars")
    sa = SUFFIX.get(sa or "", "")
    sb = SUFFIX.get(sb or "", "") or sa
    if b:
        left = num_words(a) + (" " + sa if sa and sa != sb else "")
        return f"{left} to {num_words(b)}{' ' + sb if sb else ''} {unit}"
    if not sa and "." in a and len(a.split(".")[1]) == 2:              # $0.72, $3.26 -> dollars and cents
        d, c = a.replace(",", "").split(".")
        dollars = int(d or 0)
        if dollars == 0:
            return f"{int_words(int(c))} cents"
        return f"{int_words(dollars)} {unit} {int_words(int(c))}" if int(c) else f"{int_words(dollars)} {unit}"
    if not sa and a.replace(",", "") == "1":
        unit = unit.rstrip("s")
    if _adjectival(m.string[m.end():]):
        unit = unit.rstrip("s")
    return f"{num_words(a)}{' ' + sa if sa else ''} {unit}"


def expand(text: str) -> str:
    t = text
    for k in ("e.g.", "i.e.", "vs.", "approx.", "w/"):
        t = t.replace(k, ABBREV[k])
    t = re.sub(r"(?<=\s)~|^~", "about ", t)
    t = t.replace("≈", "about ").replace(" & ", " and ")
    t = re.sub(r"\bSOTA\b", "state of the art", t)
    t = re.sub(r"\bYoY\b", "year over year", t)
    t = re.sub(r"\bQoQ\b", "quarter over quarter", t)
    t = re.sub(r"\bvs\b", "versus", t)
    t = re.sub(r"(?<![\w&])#(\d+)\b", lambda m: "number " + num_words(m.group(1)), t)
    t = re.sub(r"\bpass@(\d+)\b", lambda m: "pass at " + num_words(m.group(1)), t)
    t = re.sub(r"\b[Qq]([1-4])\b", lambda m: "Q " + ONES[int(m.group(1))], t)
    # a single capital glued to a version number ("K3.1", "R1", "H100") is said as letter + number, not "Kthree"
    t = re.sub(r"(?<![\w.])([A-Z])(\d+(?:\.\d+)*)(?![\w])", r"\1 \2", t)
    t = re.sub(r"([?!])\.(?=\s|$)", r"\1", t)             # "...the Patches?." (a title ending a sentence)
    t = t.replace("and/or", "and or")
    t = re.sub(r"\best\.(?=\)|\s|$)", "estimate", t)
    # model sizes "74B-A9B" (total / active parameters)
    t = re.sub(r"(?<![\w.])(" + NUM + r")\s?B-A(" + NUM + r")\s?B\b",
               lambda m: f"{num_words(m.group(1))} billion total, {num_words(m.group(2))} billion active", t)
    # multiplier ranges "4x-12x", "3–7x"
    t = re.sub(r"(?<![\w.])(" + NUM + r")\s?[x×]?\s?[–-]\s?(" + NUM + r")\s?[x×](?![\w])",
               lambda m: f"{num_words(m.group(1))} to {num_words(m.group(2))} times", t)
    # per-unit rates "$1.3B/mo", "$20/month", "/yr", "/task"
    rates = {"mo": "a month", "month": "a month", "yr": "a year", "year": "a year", "wk": "a week", "week": "a week",
             "day": "a day", "hr": "an hour", "hour": "an hour", "task": "per task", "user": "per user", "seat": "per seat"}
    t = re.sub(r"/(mo|month|yr|year|wk|week|day|hr|hour|task|user|seat)\b", lambda m: " " + rates[m.group(1)], t)
    # token pricing "$2/$10 per million tokens": input, then output
    t = re.sub(r"([$€£]" + NUM + r"(?:\s?[kKmMbB])?)\s?/\s?([$€£]" + NUM + r"(?:\s?[kKmMbB])?)(?=\s+(?:per|a|/)\s*(?:1M|M|million|1,000,000|thousand|1K|K)?\s*(?:input\s+|output\s+)?tokens)",
               lambda m: f"{m.group(1)} for input and {m.group(2)} for output", t)
    t = _MONEY.sub(_money, t)
    t = _PCT.sub(lambda m: (num_words(m.group(1)) + " to " + num_words(m.group(2)) if m.group(2)
                            else num_words(m.group(1))) + " percent", t)
    t = _MULT.sub(lambda m: num_words(m.group(1)) + " times", t)
    t = _UNIT.sub(lambda m: num_words(m.group(1)) + " " + (UNITS[m.group(2)].rstrip("s") if _adjectival(m.string[m.end():])
                                                             else UNITS[m.group(2)]), t)
    t = _SCALED.sub(lambda m: num_words(m.group(1)) + " " + SUFFIX[m.group(2)], t)
    t = _VERSION.sub(lambda m: m.group(1) + " " + " point ".join(int_words(int(x)) for x in m.group(2).split("."))
                     + (" " + m.group(3) if m.group(3) else ""), t)
    t = _DOTTED.sub(lambda m: int_words(int(m.group(1))) + " point " + " ".join(ONES[int(d)] for d in m.group(2)), t)
    t = _YEAR.sub(lambda m: year_words(int(m.group(1))), t)
    t = _RANGE.sub(lambda m: num_words(m.group(1)) + " to " + num_words(m.group(2)), t)
    t = _PLAIN.sub(lambda m: num_words(m.group(1)), t)
    t = re.sub(r"(dollars?|euros?|pounds?|cents?|percent)\s?/\s?", r"\1 and ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t


# ---------- pronunciation ----------

def load_table(root: Path) -> dict:
    """pronunciations.yaml: {"Andrew Ng": "Andrew Eng", "LeCun": "Luh-Koon", ...} (hand-edited, longest match wins)."""
    import yaml
    p = root / "pronunciations.yaml"
    d = (yaml.safe_load(p.read_text("utf-8")) if p.exists() else None) or {}
    return {str(k): str(v) for k, v in d.items() if k and v}


def pronounce(text: str, table: dict) -> tuple:
    hits = []
    for k in sorted(table, key=len, reverse=True):
        pat = r"(?<![\w-])" + re.escape(k) + r"(?![\w]|-[A-Za-z])"     # "GPT-6.1" counts, "Ng-something" doesn't
        if re.search(pat, text):
            hits.append(k)
            text = re.sub(pat, table[k], text)
    return text, hits


_GLUED = re.compile(r"\b([A-Z][a-z]{2,})(\d+(?:\.\d+)?)\b")      # 'Qwen3.8' -> 'Qwen 3.8' (10-27: heard "QN3, 8")


def spoken(text: str, table: dict) -> str:
    """Pronounce first (so names like 'GPT-6.1 Sol' can have entries), then expand figures. A name glued to its
    version number is split first, so the table's entry for the name applies and the number is read as a number."""
    return expand(pronounce(_GLUED.sub(r"\1 \2", text), table)[0])


_ODD = re.compile(r"\b(?:[A-Za-z]+\d+[A-Za-z\d.]*|[A-Z]{4,}|[a-z]+[A-Z][A-Za-z]+)\b")


def lint(text: str, table: dict | None = None) -> list:
    """Tokens the voice is likely to garble after expansion (mixed letters and digits, long all-caps runs, camelCase
    brand names) that the pronunciation table doesn't cover. Logged before voicing, for pronunciations.yaml."""
    known = {k.lower() for k in (table or {})}
    out = []
    for m in _ODD.finditer(text or ""):
        w = m.group(0)
        if w.lower() not in known and w not in out:
            out.append(w)
    return out[:20]
