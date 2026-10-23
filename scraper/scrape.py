"""Scrape Ithaca venue listings into site/events.json and site/ithaculture.ics.

Each venue scraper returns a list of event dicts. A venue that fails is
recorded in the output with its error so the page can say so, and the other
venues are still published.

Usage: python scraper/scrape.py [--out site] [--debug-dir debug]
"""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import traceback
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("America/New_York")
DAYS_AHEAD = 42
UA = (
    "Mozilla/5.0 (compatible; ithaculture/1.0; "
    "+https://github.com/jcn-ithaca/ithaculture)"
)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

DEBUG_DIR = None


def now():
    return dt.datetime.now(TZ)


def fetch(url, name=None):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    if DEBUG_DIR and name:
        (DEBUG_DIR / name).write_bytes(r.content)
    return r


def infer_year(month, day, today):
    """Listings omit the year. Pick the year that puts the date closest to today."""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def parse_clock(text):
    """'7:00 PM', '7PM', '8:15pm' -> (hour, minute) or None."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\b", text)
    if not m:
        return None
    hour = int(m.group(1)) % 12
    if m.group(3).lower() == "p":
        hour += 12
    return hour, int(m.group(2) or 0)


def event(venue, title, start, *, end=None, all_day=False, url=None,
          description="", kind="event"):
    return {
        "venue": venue,
        "title": " ".join(title.split()),
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "all_day": all_day,
        "url": url,
        "description": " ".join(description.split())[:300],
        "kind": kind,
    }


# --- Bike Bar ---------------------------------------------------------------

BIKEBAR_URL = "https://bikebarithaca.com"


def scrape_bikebar():
    """The homepage 'Shows & Events' block lists lines like
    '10/17 Public Water Supply -Rochester based indie'. Events start at 7pm."""
    soup = BeautifulSoup(fetch(BIKEBAR_URL, "bikebar.html").text, "html.parser")
    today = now().date()
    out, seen = [], set()
    for line in soup.get_text("\n").splitlines():
        m = re.match(r"^\s*(\d{1,2})/(\d{1,2})\s+(\S.*?)\s*$", line)
        if not m:
            continue
        d = infer_year(int(m.group(1)), int(m.group(2)), today)
        if d is None:
            continue
        text = m.group(3)
        # 'Act name -genre description' (space, hyphen, no space).
        title, _, desc = text.partition(" -")
        clock = parse_clock(text) or (19, 0)
        key = (d, title)
        if key in seen:
            continue
        seen.add(key)
        start = dt.datetime.combine(d, dt.time(*clock), TZ)
        out.append(event("Bike Bar", title.strip(), start,
                         url=BIKEBAR_URL, description=desc.strip()))
    if not out:
        raise RuntimeError("no M/D event lines found on the homepage")
    return out


# --- Liquid State Brewing ---------------------------------------------------

LIQUID_URL = "https://www.liquidstatebeer.com/upcoming-events"
LIQUID_DETAIL = "/event-details-registration/"
DATE_RE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+([A-Z][a-z]{2})\w*\s+(\d{1,2})\b")
FULL_DT_RE = re.compile(
    r"([A-Z][a-z]{2})\w*\s+(\d{1,2}),\s+(\d{4}),\s+(\d{1,2}:\d{2}\s*[AP]M)"
    r"(?:\s*[–-]\s*(?:([A-Z][a-z]{2})\w*\s+(\d{1,2}),\s+(\d{4}),\s+)?(\d{1,2}:\d{2}\s*[AP]M))?")
SLUG_DT_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})/?$")


def liquid_detail_time(url):
    """Read the 'Time & Location' line, e.g. 'Oct 23, 2026, 7:00 PM – 11:00 PM'."""
    text = BeautifulSoup(fetch(url).text, "html.parser").get_text(" ")
    m = FULL_DT_RE.search(text)
    if not m:
        return None, None
    mon, day, year, t1 = m.group(1), m.group(2), m.group(3), m.group(4)
    d = dt.date(int(year), MONTHS[mon.lower()], int(day))
    start = dt.datetime.combine(d, dt.time(*parse_clock(t1)), TZ)
    end = None
    if m.group(8):
        end_d = d
        if m.group(5):
            end_d = dt.date(int(m.group(7)), MONTHS[m.group(5).lower()], int(m.group(6)))
        end = dt.datetime.combine(end_d, dt.time(*parse_clock(m.group(8))), TZ)
        if end <= start:
            end += dt.timedelta(days=1)
    return start, end


def scrape_liquid():
    html = fetch(LIQUID_URL, "liquidstate.html").text
    soup = BeautifulSoup(html, "html.parser")
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    cards = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if LIQUID_DETAIL not in href:
            continue
        href = requests.compat.urljoin(LIQUID_URL, href)
        title = a.get_text(" ", strip=True)
        card = cards.setdefault(href, {"title": None, "date": None})
        if title and title.lower() not in {"rsvp", "buy tickets", "more info",
                                           "register", "get tickets"}:
            card["title"] = card["title"] or title
        if card["date"] is None:
            s = a.find_next(string=DATE_RE)
            if s:
                m = DATE_RE.search(s)
                card["date"] = infer_year(MONTHS[m.group(1).lower()], int(m.group(2)), today)
    if not cards:
        raise RuntimeError("no event links found on the upcoming-events page")

    out = []
    for url, card in cards.items():
        start = end = None
        m = SLUG_DT_RE.search(url)
        if m:
            y, mo, d, h, mi = map(int, m.groups())
            start = dt.datetime(y, mo, d, h, mi, tzinfo=TZ)
        elif card["date"]:
            start = dt.datetime.combine(card["date"], dt.time(19, 0), TZ)
        if start and not (today <= start.date() <= horizon):
            continue
        try:
            s2, e2 = liquid_detail_time(url)
            if s2:
                start, end = s2, e2
        except requests.RequestException as e:
            print(f"  liquid state: detail page failed for {url}: {e}", file=sys.stderr)
        if not start or not card["title"]:
            continue
        out.append(event("Liquid State Brewing", card["title"], start, end=end, url=url))
    if not out:
        raise RuntimeError(f"found {len(cards)} event links but could not date any of them")
    return out


# --- K-HOUSE Karaoke & Arts Hub ---------------------------------------------

KHOUSE_ICS = (
    "https://calendar.google.com/calendar/ical/"
    "0dcc47371cce0043343b8bc2edac62f0903949bafd11d91bdd71b644c4323811"
    "%40group.calendar.google.com/public/basic.ics"
)
KHOUSE_URL = "https://www.khousekaraoke.com"


def scrape_khouse():
    cal = icalendar.Calendar.from_ical(fetch(KHOUSE_ICS, "khouse.ics").content)
    today = now().date()
    out = []
    for e in recurring_ical_events.of(cal).between(today, today + dt.timedelta(days=DAYS_AHEAD)):
        s = e["DTSTART"].dt
        en = e.get("DTEND").dt if e.get("DTEND") else None
        all_day = not isinstance(s, dt.datetime)
        if all_day:
            start = dt.datetime.combine(s, dt.time(0, 0), TZ)
            end = None
        else:
            start = s.astimezone(TZ)
            end = en.astimezone(TZ) if isinstance(en, dt.datetime) else None
        summary = str(e.get("SUMMARY", "Untitled"))
        if summary.lower().startswith("private"):
            continue
        out.append(event("K-HOUSE", summary, start,
                         end=end, all_day=all_day, url=KHOUSE_URL,
                         description=str(e.get("DESCRIPTION", ""))))
    return out


# --- Cinemapolis ------------------------------------------------------------

CINEMAPOLIS_URL = "https://www.cinemapolis.org/now-showing"


def film_title(texts):
    """Film links read like 'PRIMETIME — FINAL WEEK! -' or 'Primetime'.
    Prefer a mixed-case version and drop promo suffixes."""
    texts = [re.split(r"\s+[—–]\s+", t)[0].strip(" -–—") for t in texts]
    texts = [t for t in texts if t]
    mixed = [t for t in texts if not t.isupper()]
    if mixed:
        return mixed[0]
    return texts[0].title().replace("'S ", "'s ").replace("’S ", "’s ") if texts else ""


def scrape_cinemapolis():
    """The now-showing page lists today's showtimes as checkout links:
    /checkout/showing/<film-slug>/<id>/ with text like '8:00PM'."""
    soup = BeautifulSoup(fetch(CINEMAPOLIS_URL, "cinemapolis.html").text, "html.parser")
    names = {}
    for a in soup.find_all("a", href=re.compile(r"/movie/[^/]+/?")):
        slug = re.search(r"/movie/([^/]+)", a["href"]).group(1)
        text = a.get_text(" ", strip=True)
        if text:
            names.setdefault(slug, []).append(text)
    titles = {slug: film_title(texts) for slug, texts in names.items()}
    today = now().date()
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/checkout/showing/[^/]+/\d+")):
        m = re.search(r"/checkout/showing/([^/]+)/(\d+)", a["href"])
        slug, show_id = m.groups()
        clock = parse_clock(a.get_text(" ", strip=True))
        if not clock or show_id in seen:
            continue
        seen.add(show_id)
        title = titles.get(slug) or slug.replace("-", " ").title()
        start = dt.datetime.combine(today, dt.time(*clock), TZ)
        out.append(event("Cinemapolis", title, start,
                         url=requests.compat.urljoin(CINEMAPOLIS_URL, a["href"]),
                         kind="film"))
    if not out:
        raise RuntimeError("no showtime links found on the now-showing page")
    return out


VENUES = [
    ("Bike Bar", BIKEBAR_URL, scrape_bikebar),
    ("Liquid State Brewing", LIQUID_URL, scrape_liquid),
    ("K-HOUSE", KHOUSE_URL, scrape_khouse),
    ("Cinemapolis", CINEMAPOLIS_URL, scrape_cinemapolis),
]


def write_ics(events, path):
    cal = icalendar.Calendar()
    cal.add("prodid", "-//ithaculture//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Ithaculture")
    for ev in events:
        ve = icalendar.Event()
        start = dt.datetime.fromisoformat(ev["start"])
        key = f"{ev['venue']}|{ev['title']}|{ev['start']}".encode()
        ve.add("uid", f"{hashlib.sha1(key).hexdigest()[:16]}@ithaculture")
        ve.add("summary", f"{ev['title']} @ {ev['venue']}")
        if ev["all_day"]:
            ve.add("dtstart", start.date())
        else:
            ve.add("dtstart", start)
            ve.add("dtend", dt.datetime.fromisoformat(ev["end"]) if ev["end"]
                   else start + dt.timedelta(hours=2))
        ve.add("location", ev["venue"])
        if ev["url"]:
            ve.add("url", ev["url"])
        if ev["description"]:
            ve.add("description", ev["description"])
        cal.add_component(ve)
    path.write_bytes(cal.to_ical())


def main():
    global DEBUG_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--debug-dir")
    args = ap.parse_args()
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.debug_dir:
        DEBUG_DIR = pathlib.Path(args.debug_dir)
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    events, venues = [], []
    for name, url, fn in VENUES:
        try:
            found = fn()
            venues.append({"name": name, "url": url, "ok": True, "count": len(found)})
            events.extend(found)
            print(f"{name}: {len(found)} events")
        except Exception as e:
            traceback.print_exc()
            venues.append({"name": name, "url": url, "ok": False, "error": str(e)})
            print(f"{name}: FAILED ({e})")

    today = now().date()
    events = [e for e in events if dt.datetime.fromisoformat(e["start"]).date() >= today]
    events.sort(key=lambda e: (e["start"], e["venue"], e["title"]))
    data = {"generated_at": now().isoformat(timespec="seconds"),
            "venues": venues, "events": events}
    (out_dir / "events.json").write_text(json.dumps(data, indent=1))
    write_ics(events, out_dir / "ithaculture.ics")
    for e in events:
        print(f"  {e['start'][:16]}  {e['venue']:<20}  {e['title']}")
    print(f"wrote {len(events)} events")
    if not any(v["ok"] for v in venues):
        sys.exit("every venue failed")


if __name__ == "__main__":
    main()
