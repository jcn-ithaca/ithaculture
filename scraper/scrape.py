"""Scrape Ithaca venue listings into site/events.json and site/ithaculture.ics.

Each venue scraper returns a list of event dicts. A venue that fails is
recorded in the output with its error so the page can say so, and the other
venues are still published.

Usage: python scraper/scrape.py [--out site] [--debug-dir debug]
"""

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("America/New_York")
PUBLISHED_JSON = "https://jcn-ithaca.github.io/ithaculture/events.json"
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


def fetch(url, name=None, attempts=3):
    for i in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            break
        except requests.RequestException:
            if i == attempts - 1:
                raise
            time.sleep(5 * (i + 1))
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


# --- Hangar Theatre ---------------------------------------------------------

HANGAR_URL = "https://hangartheatre.org/buy-tickets/"
HANGAR_API = "https://hangartheatre.org/wp-json/tribe/events/v1/events"


def scrape_hangar():
    """The site runs The Events Calendar, whose REST API returns structured
    events. Multi-day shows come back as all-day ranges with performance
    times only in the description."""
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    # No end_date: the API drops events that end after it, which hides long runs.
    url = f"{HANGAR_API}?per_page=50&start_date={today.isoformat()}"
    items, page = [], 1
    while url:
        data = fetch(url, f"hangar-{page}.json").json()
        items.extend(data.get("events", []))
        url = data.get("next_rest_url")
        page += 1
    out = []
    for e in items:
        title = html.unescape(e["title"])
        desc = BeautifulSoup(e.get("description") or "", "html.parser").get_text(" ")
        start = dt.datetime.fromisoformat(e["start_date"]).replace(tzinfo=TZ)
        end = dt.datetime.fromisoformat(e["end_date"]).replace(tzinfo=TZ)
        if start.date() > horizon:
            continue
        if not e.get("all_day"):
            out.append(event("Hangar Theatre", title, start,
                             end=end if end > start else None,
                             url=e.get("url"), description=desc))
            continue
        days = (end.date() - start.date()).days + 1
        if days <= 7:
            # Short runs: list the show on each day it plays.
            for i in range(days):
                d = dt.datetime.combine(start.date() + dt.timedelta(i), dt.time(0, 0), TZ)
                out.append(event("Hangar Theatre", title, d, all_day=True,
                                 url=e.get("url"), description=desc))
        else:
            # Long runs (classes, residencies): one entry on the first day.
            span = f"Runs {start:%b %-d} – {end:%b %-d}. "
            out.append(event("Hangar Theatre", title, start, all_day=True,
                             url=e.get("url"), description=span + desc))
    return out


# --- State Theatre ----------------------------------------------------------

STATE_URL = "https://stateofithaca.org/events/"
STATE_TIX = "tixr.com/groups/stateofithaca/events/"
STATE_DATE_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{1,2})\b")


def scrape_state():
    """The events page is a hand-built Elementor list. Each event has a title
    linking to its Tixr page, then a 'Nov 09' date line and a line like
    'All Ages  Doors: 7:00 PM | Show: 8:00 PM'. Years are omitted."""
    soup = BeautifulSoup(fetch(STATE_URL, "state.html").text, "html.parser")
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    titles = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if STATE_TIX in a["href"] and text and text.upper() not in {"TICKETS", "BUY TICKETS"}:
            if not titles or titles[-1][0] != a["href"]:
                titles.append((a["href"], text, a))
    if not titles:
        raise RuntimeError("no Tixr event links found on the events page")
    hrefs = {h for h, _, _ in titles}
    out, dated = [], 0
    for href, title, a in titles:
        # The date ('Oct' '23') and times ('Doors:' '7:00 PM') are split across
        # elements, so join the block's text and match on that.
        parts = []
        for s in a.find_all_next(string=True, limit=60):
            parent = s.find_parent("a", href=True)
            if parent is not None and parent["href"] in hrefs and parent["href"] != href:
                break  # reached the next event
            text = " ".join(s.split())
            if text and text != title:
                parts.append(text)
        block = " ".join(parts)
        date = doors = show = None
        m = STATE_DATE_RE.search(block)
        if m:
            date = infer_year(MONTHS[m.group(1).lower()], int(m.group(2)), today)
        m = re.search(r"Doors:\s*(\d{1,2}:\d{2}\s*[AP]M)", block)
        if m:
            doors = parse_clock(m.group(1))
        m = re.search(r"Show:\s*(\d{1,2}:\d{2}\s*[AP]M)", block)
        if m:
            show = parse_clock(m.group(1))
        extra = [t for t in parts if t.lower().startswith("with ")][:1]
        if date is None:
            continue
        dated += 1
        if not (today <= date <= horizon):
            continue
        clock = show or doors or (20, 0)
        start = dt.datetime.combine(date, dt.time(*clock), TZ)
        if doors and show:
            extra.append(f"Doors {dt.time(*doors):%-I:%M %p}")
        out.append(event("State Theatre", title, start, url=href,
                         description=" · ".join(extra)))
    if not dated:
        raise RuntimeError(f"found {len(titles)} events but could not read any dates")
    return out

VISIT_URL = "https://www.visitithaca.com/events/live-music/"
VISIT_RSS = "https://www.visitithaca.com/event/rss/"
# Visit Ithaca's events API refuses GitHub's servers, but its RSS feed works.
# The feed only covers today and tomorrow, so that's all this source can show.
# Venues we already scrape directly are skipped to avoid duplicates.
VISIT_SKIP = ("bike bar", "liquid state", "k-house", "khouse", "cinemapolis",
              "hangar", "state theatre", "state theater", "state of ithaca")


def visit_detail(url):
    """Pull the venue and start time out of the JSON an event page logs."""
    page = fetch(url).text
    m = re.search(r'console\.log\((\{"_id".*?\})\);', page, re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(1))
        except ValueError:
            pass
    if not data:
        for key in ("location", "startTime", "endTime"):
            km = re.search(rf'"{key}":"([^"]*)"', page)
            if km:
                data[key] = km.group(1)
    return data


def scrape_visitithaca():
    root = ET.fromstring(fetch(VISIT_RSS, "visitithaca.xml").content)
    items = root.findall("./channel/item")
    if not items:
        raise ValueError("RSS feed had no items")
    out = []
    for item in items:
        cats = [" ".join(html.unescape(c.text or "").split()) for c in item.findall("category")]
        if "Live Music" not in cats:
            continue
        title = html.unescape(item.findtext("title") or "")
        url = item.findtext("link")
        day = dt.datetime.strptime(item.findtext("pubDate")[:16], "%a, %d %b %Y").date()
        time.sleep(2)  # robots.txt asks for a 2 second crawl delay
        info = visit_detail(url)
        where = " ".join((info.get("location") or "").split())
        if any(k in f"{where} {title}".lower() for k in VISIT_SKIP):
            continue
        st = info.get("startTime")
        if st:
            h, mi = map(int, st.split(":")[:2])
            start = dt.datetime.combine(day, dt.time(h, mi), TZ)
            out.append(event("Visit Ithaca", title, start, url=url, description=f"at {where}" if where else ""))
        else:
            out.append(event("Visit Ithaca", title, dt.datetime.combine(day, dt.time(0), TZ),
                             all_day=True, url=url, description=f"at {where}" if where else ""))
    return out

TUT_URL = "https://www.treesuptompkins.org/get-involved"
TUT_PAGES = ["https://www.treesuptompkins.org/", TUT_URL]
# Trees Up Tompkins types its work days as free text on a Wix site, e.g.
# "Wed. Nov. 11 @ 10 AM" or "Sunday 8/23 @ 10 AM - 12 PM".
WD = r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+"
TUT_NAMED_RE = re.compile(WD + r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b")
TUT_NUM_RE = re.compile(WD + r"(\d{1,2})/(\d{1,2})\b")
TUT_AT_RE = re.compile(r"^\s*@\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\.?)?")


def tut_clock(rest):
    """Read the '@ 10 AM' / '@4:30' / '@ 10-12' after a date; None if no time."""
    m = TUT_AT_RE.match(rest)
    if not m:
        return None, rest
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        hour = hour % 12 + (12 if m.group(3)[0].lower() == "p" else 0)
    elif hour < 8:
        hour += 12  # "@4:30" for a volunteer work day means afternoon
    rest = rest[m.end():]
    # Drop an end time such as "- 12 PM" or "-12".
    rest = re.sub(r"^\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:[AaPp]\.?[Mm]\.?)?", "", rest)
    return (hour, minute), rest


def scrape_trees_up():
    today = now().date()
    out, seen = [], set()
    for i, page_url in enumerate(TUT_PAGES):
        soup = BeautifulSoup(fetch(page_url, f"treesup{i}.html").text, "html.parser")
        lines = [" ".join(t.split()) for t in soup.get_text("\n").split("\n")]
        lines = [t for t in lines if t]
        for n, line in enumerate(lines):
            m = TUT_NAMED_RE.search(line)
            if m:
                month, day = MONTHS[m.group(1).lower()], int(m.group(2))
            else:
                m = TUT_NUM_RE.search(line)
                if not m:
                    continue
                month, day = int(m.group(1)), int(m.group(2))
            try:
                date = infer_year(month, day, today)
            except ValueError:
                continue
            if not date or date < today:
                continue
            clock, rest = tut_clock(line[m.end():])
            rest = rest.strip(" -–:|")
            following = []
            for t in lines[n + 1:n + 4]:
                if TUT_NAMED_RE.search(t) or TUT_NUM_RE.search(t):
                    break
                following.append(t.strip(" -–"))
            title = rest or (following.pop(0) if following else "Volunteer work day")
            # Wix splits sentences across elements, so rejoin with spaces.
            description = " ".join(t for t in following[:2] if not t.lower().startswith("click"))
            key = (date, title.lower())
            if key in seen:
                continue
            seen.add(key)
            if clock:
                start = dt.datetime.combine(date, dt.time(*clock), TZ)
                out.append(event("Trees Up Tompkins", title, start, url=TUT_URL, description=description))
            else:
                start = dt.datetime.combine(date, dt.time(0), TZ)
                out.append(event("Trees Up Tompkins", title, start, all_day=True, url=TUT_URL,
                                 description=description))
    return out


VENUES = [
    ("Bike Bar", BIKEBAR_URL, scrape_bikebar),
    ("Liquid State Brewing", LIQUID_URL, scrape_liquid),
    ("K-HOUSE", KHOUSE_URL, scrape_khouse),
    ("Cinemapolis", CINEMAPOLIS_URL, scrape_cinemapolis),
    ("Hangar Theatre", HANGAR_URL, scrape_hangar),
    ("State Theatre", STATE_URL, scrape_state),
    ("Visit Ithaca", VISIT_URL, scrape_visitithaca),
    ("Trees Up Tompkins", TUT_URL, scrape_trees_up),
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
    previous = None
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
            # Keep the venue's last published listings rather than dropping it.
            if previous is None:
                try:
                    previous = requests.get(PUBLISHED_JSON, timeout=30).json()
                except Exception:
                    previous = {}
            kept = [ev for ev in previous.get("events", []) if ev["venue"] == name]
            events.extend(kept)
            print(f"{name}: kept {len(kept)} events from the last published run")

    today = now().date()
    events = [e for e in events if dt.datetime.fromisoformat(e["start"]).date() >= today]
    # Drop Visit Ithaca listings that a venue scraper already found that day.
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    seen = {(e["start"][:10], norm(e["title"])) for e in events if e["venue"] != "Visit Ithaca"}
    events = [e for e in events
              if e["venue"] != "Visit Ithaca" or (e["start"][:10], norm(e["title"])) not in seen]
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
