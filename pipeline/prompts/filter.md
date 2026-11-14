Decide which of the items below are worth analyzing for Steven's briefing. Steven is a seed-to-Series A AI investor in Canada; the briefing exists to tell him what changed for the companies he backs and the ones he might. Judge by what the item is about, not by how it is written: a short post about a real event is KEEP; a long post about nothing is DROP.

KEEP (any one is enough):
- AI research, models and capabilities: a release, a benchmark or price change, a scientific or mathematical result, an open-weights model, a robotics or physical-AI system (robots, world models, simulation-to-hardware, lab automation). A lab or founder announcing its own release counts as KEEP: the self-promotion is the news, the evidence check comes later.
- Real-world AI use and business value: deployments, measured results, customers, pricing, margins, failures and incidents (security, safety, outages, lawsuits over AI behaviour).
- Legal AI and the legal industry's use of AI (a portfolio company is in this market): law-firm and vendor moves, Copilot for Legal, Harvey, Legora, AI-native firms hiring lawyers, legal-tech product and pricing news, even when framed as industry rather than AI news.
- Money: any round, valuation, acquisition, merger, IPO, secondary, debt or compute deal that involves an AI company or AI infrastructure, at any stage and any size, including defence, health, climate or fintech companies whose product is AI. "Not AI-specific" is not a reason to drop a deal with an amount.
- AI economics and capex: data centers, power, chips and the compute supply chain, cloud and neocloud finances, export controls.
- The companies and people that make the AI market: leadership changes, board actions, investigations, regulatory and political action, and personal-conduct stories once they reach a board, a regulator, a legislature or the share price, at labs, chip and cloud vendors (Nvidia, OpenAI, Anthropic, Google, Microsoft, Meta, AMD, TSMC, CoreWeave and peers). "Personal scandal" at the CEO of the industry's supplier is market news.
- Sovereign, multilingual and Canadian or European AI, and Canadian or European AI startups.
- Policy, law and standards affecting AI companies (the EU AI Act, US state laws, safety reporting, copyright rulings, procurement).
- A tracked person's substantive argument, data point or guest appearance on any of the above, even when short or sarcastic.

DROP:
- Personal chatter (movies, sports, food, travel, family), jokes and one-line reactions with no claim, greetings and tag-only posts.
- Event logistics and promotion with no content (a conference next week, "come see me"), job posts, newsletter housekeeping.
- Posts that only announce an article already in the archive (same link), reposts and translated duplicates.
- Items with no real text (an image, a bare link, a truncated teaser with no claim).
- Technology, business or politics with no AI connection at all (a non-AI company's earnings, a game console feature, general elections).

When unsure, KEEP: the next stage scores importance and the briefing's caps do the cutting; a wrong KEEP costs a few seconds, a wrong DROP loses the story for the day. Give a short reason (max 12 words) that names the KEEP or DROP line you applied.

Return JSON: {"decisions": [{"id": "<item id>", "keep": true|false, "reason": "..."}]} with exactly one decision per item.

{{items}}
