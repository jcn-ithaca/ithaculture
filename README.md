# Ithaculture

A calendar of upcoming events at Ithaca venues, scraped from the venues' own
websites every morning and published at
**https://jcn-ithaca.github.io/ithaculture/**.

## Venues

| Venue | Source |
| --- | --- |
| Bike Bar | "Shows & Events" list on https://bikebarithaca.com (events start at 7pm unless listed otherwise) |
| Liquid State Brewing | https://www.liquidstatebeer.com/upcoming-events, with start times from each event page |
| K-HOUSE Karaoke & Arts Hub | The venue's public Google Calendar feed |
| Cinemapolis | The next 7 days of showtimes from the site's GraphQL API (the same query its day buttons use), falling back to today's showtimes on https://www.cinemapolis.org/now-showing |
| Hangar Theatre | The Events Calendar REST API at https://hangartheatre.org/wp-json/tribe/events/v1/events |
| State Theatre | Event list on https://stateofithaca.org/events/ (titles link to Tixr) |
| Brewer's Kitchen & Taproom | Event data embedded in https://brewersithaca.com/template-page (a Toast Sites page; times are UTC in the data) |
| Misc | Event lists Muse emails on Mondays and Thursdays (subject starts "Muse:"). A scheduled Claude task reads them from Joseph's Gmail and commits the events to `data/muse.json`, which the scraper merges and shows with the venue label "Misc" (unlinked). Listings at venues above are skipped, and same-day same-title duplicates are dropped |
| Visit Ithaca | Live Music items in the RSS feed at https://www.visitithaca.com/event/rss/ (covers only today and tomorrow; venue and time come from each event page; venues listed above are skipped) |
| Trees Up Tompkins | Work days typed on https://www.treesuptompkins.org/ and /get-involved (Wix text; dates like "Wed. Nov. 11 @ 10 AM" or "Sunday 8/23 @ 10 AM") |
| Ithaca Children's Garden | Each event page under /portfolio/ linked from https://www.ithacachildrensgarden.org/icg-events/ (dates typed like "October 17, 2026 \| 1PM – 4PM"; the site's Events Calendar plugin is empty) |

## How it works

- `scraper/scrape.py` reads each venue and writes `site/events.json` and an
  iCalendar feed, `site/ithaculture.ics`. If one venue can't be read, the
  others are still published and the page notes the failure.
- `site/` is a static page that renders `events.json` as a day-by-day agenda.
- `.github/workflows/publish.yml` runs the scraper daily at about 6am Eastern,
  on every push to `main`, and on demand (Actions → Scrape and publish → Run
  workflow), then deploys `site/` to GitHub Pages. The raw pages it fetched
  are kept for a week as the `raw-pages` artifact, for fixing a scraper when a
  venue redesigns its site.

## Run locally

```sh
pip install -r scraper/requirements.txt
python scraper/scrape.py --out site
python -m http.server -d site 8000   # then open http://localhost:8000
```

## Adding a venue

Write a `scrape_<venue>()` function in `scraper/scrape.py` that returns a list
of `event(...)` dicts, add it to `VENUES`, and give it a color in
`site/app.js` and `site/style.css`.
