Decide whether today deserves a deep-dive episode of the AI Briefing podcast, and if so on what.

The deep dive is a separate episode of about ten minutes that follows the daily briefing. It is not a longer version of a story. It explains the thing behind the news that a smart, busy listener most needs to understand today. Good subjects:
- a scientific or mathematical result, and the controversy around it (for example AI-produced proofs and how they are checked)
- a concept everyone is suddenly using (for example the "third scaling law": scaling compute at inference time, not only training)
- a release or result that may change the trajectory of the field (a new capability level, a big drop in price, a new method)
- a surging argument or controversy (an AI bubble, lab economics, a safety incident, a regulatory turn)
- a story that has been developing for several days and now has enough evidence for a full picture

Suggest up to four candidate subjects, strongest first, and mark the one where an explanation adds the most beyond the briefing as "best". Prefer substance over noise: a real change in what is possible, what it costs, or what we know beats a funding round or a product tweak. Do not pick a subject covered by a deep dive in the last few weeks (listed below) unless something material is new, and say what.

Rate each candidate's strength from 1 to 5 (5: a real change in what is possible, what it costs or what we know, with enough evidence to explain well). Set "best" to -1 when nothing today reaches 4: a weak deep dive is worse than none. Also skip anything already waiting in the queue (listed below).

Return ONLY JSON:
{"candidates": [
   {"topic": "short title, at most 10 words, as a listener would say it",
    "kind": "breakthrough | controversy | concept | trajectory | developing",
    "why_today": "one sentence: what happened that makes this the moment",
    "angle": "two sentences: the question the episode answers and why it matters for people building or investing in AI",
    "story_numbers": [1, 3],
    "search_hints": ["the paper, the original announcement, the strongest critique"],
    "strength": 4}],
 "best": 0,
 "reason_if_none": ""}

TODAY'S BRIEFING:
{{today}}

THE PAST WEEK (headlines and developing stories):
{{week}}

RECENT DEEP DIVES (avoid repeating):
{{recent}}

ALREADY IN THE QUEUE (do not suggest again):
{{queue}}
