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
| Cinemapolis | Today's showtimes from https://www.cinemapolis.org/now-showing |
| Hangar Theatre | The Events Calendar REST API at https://hangartheatre.org/wp-json/tribe/events/v1/events |
| State Theatre | Event list on https://stateofithaca.org/events/ (titles link to Tixr) |
| Visit Ithaca | Live Music items in the RSS feed at https://www.visitithaca.com/event/rss/ (covers only today and tomorrow; venue and time come from each event page; venues above are skipped) |
| Trees Up Tompkins | Work days typed on https://www.treesuptompkins.org/ and /get-involved (Wix text; dates like "Wed. Nov. 11 @ 10 AM" or "Sunday 8/23 @ 10 AM") |

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
