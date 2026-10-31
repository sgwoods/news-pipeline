# Brand

The AI Briefing has one look, kept in one file: **`brand/brand.yaml`** (Steven, 2026-10-31). Every surface is made
from it: the website, the email, the Slack cards and channel banner, the podcast covers, the feeds and the
dashboard. Change a colour, a tagline or the author image there, and the next build carries it everywhere.

## What's in it

| Part | Value | Used for |
|---|---|---|
| Teal `#3e7e8a` | the brand colour | mastheads, buttons, labels |
| Deep teal `#1e4a52` | the deep dive | its band, cover, page masthead; the dark mode's base |
| Pale `#eef4f5` | the reading surface | page and email background, card body |
| Ink `#14272b`, muted `#5b6d71` | text | body and captions |
| Wave `#b9d3d7` | the waveform motif | covers, cards, banner, site masthead |
| Gold `#f2b84b` | rating stars only | the email's "How is today's briefing?" |
| Inter | the typeface | everything (`assets/fonts`, OFL) |
| Author image | `brand/author-master.png` | the one photo of Steven; every size and the white ring are made from it |
| Taglines | main, deep_dive, audience, byline, channel, description | every surface takes its wording from here |

Dark mode (the reader's setting) swaps the pale surface for deep-teal surfaces (`dark:` in the file).

## Where each surface reads it

- **Website** (`pipeline/site.py`): `site_css()` writes `style.css` from `brand.css_tokens()`; every page has the teal
  masthead with the author image, wordmark, tagline and waveform; deep-dive pages use the deep-teal masthead; each
  day's Slack card is the page's link-preview image.
- **Email** (`pipeline/mailer.py`): `C = brand.email_palette()` (mail apps take inline styles only), the taglines.
- **Slack cards** (`pipeline/card.py`): colours, taglines and the author image.
- **Slack channel banner** (`brand/slack-channel-banner.png`): pinned in #cto-ai-newsletter; the monthly promo in
  #cto-musings carries it.
- **Slack app icon** (`brand/author-icon-512.png`): uploaded by hand in the Slack app's settings when it changes.
- **Podcast covers** (`assets/podcast-cover.png`, `assets/deepdive-cover.png`): `brand.render_cover()`; the feeds
  publish them under versioned names so podcast apps refetch.
- **Feeds**: author name from the brand; the RSS feed carries the cover and the main tagline.
- **Dashboard**: its colours and header, and the **Brand** tab, which shows the whole template and where it appears.
- **Public projects hub** (sgwoods/public): to follow, with the same colours and author image.

## Pipeline module

`pipeline/brand.py`: loads `brand/brand.yaml` (`load`, `color`, `tagline`, `author`), makes the author image at any
size with or without its ring (`author_image`, `paste_author`), draws the waveform, renders the channel banner and
the covers (`render_banner`, `render_cover`), and gives the website and email their colours (`css_tokens`,
`email_palette`).

## Commands

    ./np brand show               # the tokens and taglines
    ./np brand build              # author image sizes (assets/steven-woods.jpg, brand/author-icon-512.png), the banner
    ./np brand build --covers     # also the two podcast covers

After `build`, commit the images; they ship with the next release.
