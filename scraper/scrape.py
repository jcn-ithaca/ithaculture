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
import urllib.parse
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


def clip(text, limit):
    """Cut long text at a word boundary and mark the cut."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def event(venue, title, start, *, end=None, all_day=False, url=None,
          description="", kind="event", image=None):
    ev = {
        "venue": venue,
        "title": " ".join(title.split()),
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "all_day": all_day,
        "url": url,
        "description": clip(" ".join(description.split()), 800),
        "kind": kind,
    }
    if image:
        # Only used to pick slideshow pictures; removed before events.json is written.
        ev["image"] = image
    return ev


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


CINEMAPOLIS_GQL = "https://www.cinemapolis.org/graphql"
# The site is an Indy Systems app. Its day buttons call this GraphQL query with
# the cinema's site and circuit ids (baked into the site's app.js).
CINEMAPOLIS_HEADERS = {"client-type": "consumer", "site-id": "30", "circuit-id": "31"}
CINEMAPOLIS_QUERY = "query($d:String){ showingsForDate(date:$d){ data { id time movie { name } } } }"
CINEMAPOLIS_DAYS = 7


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’]", "", name.lower())).strip("-")


def scrape_cinemapolis():
    """Showtimes for the next week from the site's GraphQL API, falling back to
    today's showtimes on the now-showing page if the API stops answering."""
    try:
        return cinemapolis_api()
    except Exception as e:
        print(f"Cinemapolis API failed ({e}); using today's page", file=sys.stderr)
        return cinemapolis_page()


def cinemapolis_api():
    today = now().date()
    out, seen = [], set()
    for i in range(CINEMAPOLIS_DAYS):
        day = (today + dt.timedelta(days=i)).isoformat()
        for attempt in range(3):
            try:
                r = requests.post(CINEMAPOLIS_GQL, timeout=30,
                                  headers={"User-Agent": UA, **CINEMAPOLIS_HEADERS},
                                  json={"query": CINEMAPOLIS_QUERY, "variables": {"d": day}})
                r.raise_for_status()
                body = r.json()
                break
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
        if body.get("errors") or not body.get("data"):
            raise RuntimeError(str(body.get("errors") or body.get("error"))[:200])
        for s in body["data"]["showingsForDate"]["data"]:
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            title = s["movie"]["name"]
            start = dt.datetime.fromisoformat(s["time"].replace("Z", "+00:00")).astimezone(TZ)
            url = f"https://www.cinemapolis.org/checkout/showing/{slugify(title)}/{s['id']}/"
            out.append(event("Cinemapolis", title, start, url=url, kind="film"))
    if not out:
        raise RuntimeError("API returned no showtimes for the week")
    return out


def cinemapolis_page():
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
    return tribe_events("Hangar Theatre", HANGAR_API, "hangar")


def tribe_events(venue, api, name, skip=None):
    """Sites running The Events Calendar (WordPress) have a REST API that
    returns structured events. Multi-day events come back as all-day ranges
    with times only in the description. `skip` is a regex; events whose
    title matches it are left out."""
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    # No end_date: the API drops events that end after it, which hides long runs.
    url = f"{api}?per_page=50&start_date={today.isoformat()}"
    items, page = [], 1
    while url:
        data = fetch(url, f"{name}-{page}.json").json()
        items.extend(data.get("events", []))
        url = data.get("next_rest_url")
        page += 1
    out = []
    for e in items:
        title = html.unescape(e["title"])
        if skip and re.search(skip, title, re.I):
            continue
        desc = BeautifulSoup(e.get("description") or "", "html.parser").get_text(" ")
        start = dt.datetime.fromisoformat(e["start_date"]).replace(tzinfo=TZ)
        end = dt.datetime.fromisoformat(e["end_date"]).replace(tzinfo=TZ)
        if start.date() > horizon:
            continue
        img = e.get("image") or {}
        img = img.get("url") if isinstance(img, dict) else None
        if not e.get("all_day"):
            out.append(event(venue, title, start,
                             end=end if end > start else None,
                             url=e.get("url"), description=desc, image=img))
            continue
        days = (end.date() - start.date()).days + 1
        if days <= 7:
            # Short runs: list the show on each day it plays.
            for i in range(days):
                d = dt.datetime.combine(start.date() + dt.timedelta(i), dt.time(0, 0), TZ)
                out.append(event(venue, title, d, all_day=True,
                                 url=e.get("url"), description=desc))
        else:
            # Long runs (classes, residencies): one entry on the first day.
            span = f"Runs {start:%b %-d} – {end:%b %-d}. "
            out.append(event(venue, title, start, all_day=True,
                             url=e.get("url"), description=span + desc, image=img))
    return out


HOPSHIRE_URL = "https://hopshire.com/hopshire-events/"
HOPSHIRE_API = "https://hopshire.com/wp-json/tribe/events/v1/events"


def scrape_hopshire():
    # Yoga classes and "Kitchen OPEN" hours aren't events worth listing.
    return tribe_events("Hopshire", HOPSHIRE_API, "hopshire", skip=r"\b(yoga|kitchen)\b")


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
    titles, images = [], {}
    for a in soup.find_all("a", href=True):
        # Each event also has its poster linked to the same Tixr page.
        img = a.find("img") if STATE_TIX in a["href"] else None
        if img and img.get("src") and a["href"] not in images:
            images[a["href"]] = requests.compat.urljoin(STATE_URL, img["src"])
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
                         description=" · ".join(extra), image=images.get(href)))
    if not dated:
        raise RuntimeError(f"found {len(titles)} events but could not read any dates")
    return out

VISIT_URL = "https://www.visitithaca.com/events/live-music/"
VISIT_RSS = "https://www.visitithaca.com/event/rss/"
# Visit Ithaca's events API refuses GitHub's servers, but its RSS feed works.
# The feed only covers today and tomorrow, so that's all this source can show.
# Venues we already scrape directly are skipped to avoid duplicates.
VISIT_SKIP = ("bike bar", "liquid state", "k-house", "khouse", "cinemapolis",
              "hangar", "state theatre", "state theater", "state of ithaca",
              "brewers kitchen", "brewer's kitchen", "brewer’s kitchen", "hopshire",
              "cherry arts", "cherry artspace", "cherry performance space", "cherry gallery",
              "102 cherry st", "130 cherry st", "hands four", "hands 4", "hfdi",
              "argos inn", "argos warehouse", "bar argos", "408 e state")


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

# --- Muse (email lists) ----------------------------------------------------

# Muse emails local event lists on Mondays and Thursdays. A scheduled Claude
# task reads them from Joseph's inbox and writes the events to data/muse.json:
# {"updated": ..., "emails": [...], "events": [{"title", "where", "start"
# (local "YYYY-MM-DDTHH:MM", or "YYYY-MM-DD" for all day), "end", "url",
# "description"}]}. Nothing is fetched here; this just reads that file.
MUSE_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "muse.json"
# Shown on the page as "Misc", with no venue link.
MUSE_VENUE = "Misc"
# How Muse names the venues we scrape directly. Muse listings there are kept,
# but only checked for duplicates against that venue's own listings.
MUSE_VENUES = {
    "Bike Bar": ("bike bar",),
    "Liquid State Brewing": ("liquid state",),
    "K-HOUSE": ("k-house", "khouse"),
    "Cinemapolis": ("cinemapolis",),
    "Hangar Theatre": ("hangar",),
    "Hopshire": ("hopshire",),
    "The Cherry Arts": ("cherry arts", "cherry artspace", "cherry performance space", "cherry gallery"),
    "State Theatre": ("state theatre", "state theater", "state of ithaca"),
    "Brewer's Kitchen & Taproom": ("brewers kitchen", "brewer's kitchen", "brewer’s kitchen"),
    "Trees Up Tompkins": ("trees up",),
    "Ithaca Children's Garden": ("children's garden", "childrens garden", "children’s garden"),
    "Hands Four Dancers": ("hands four", "hands 4", "hfdi"),
    "Argos Inn": ("argos inn", "argos warehouse", "bar argos"),
}


def muse_time(text):
    d = dt.datetime.fromisoformat(text)
    return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)


def scrape_muse():
    if not MUSE_FILE.exists():
        return []
    out = []
    for item in json.loads(MUSE_FILE.read_text()).get("events", []):
        where = " ".join((item.get("where") or "").split())
        all_day = len(item["start"]) == 10
        desc = " · ".join(x for x in (f"at {where}" if where else "", item.get("description") or "") if x)
        ev = event(MUSE_VENUE, item["title"], muse_time(item["start"]),
                   end=muse_time(item["end"]) if item.get("end") else None,
                   all_day=all_day, url=item.get("url"), description=desc)
        ev["where"] = where
        out.append(ev)
    return out


# --- Loose duplicate matching for the roundups (Muse, Visit Ithaca) ---------

# Words that don't tell two listings apart.
FILLER = set("""a an and the of with w at in on for to by from featuring feat ft
presents presenting live music night open mic show party annual
ithaca brewing company co inc bar nightclub theatre theater""".split())
ALIASES = {"bros": "brothers", "bro": "brother", "&": "and", "dj's": "dj"}


def title_words(text, drop=()):
    words = re.findall(r"[a-z0-9&']+", text.lower().replace("’", "'"))
    words = [ALIASES.get(w, w).strip("'") for w in words]
    return {w for w in words if w and w not in FILLER and w not in drop
            and not re.fullmatch(r"\d+(st|nd|rd|th)?", w)}


def same_listing(a, b, drop=()):
    """True if two titles on the same day look like the same event: they share
    two distinctive words, or every distinctive word of one is in the other."""
    wa, wb = title_words(a, drop), title_words(b, drop)
    if not wa or not wb:
        return False
    shared = len(wa & wb)
    return shared >= 2 or shared == min(len(wa), len(wb))


def muse_home(where):
    w = where.lower()
    return next((name for name, keys in MUSE_VENUES.items() if any(k in w for k in keys)), None)


def drop_roundup_duplicates(events, roundups):
    """Drop roundup listings (in order) that a venue scraper, or an earlier
    roundup, already has that day. A roundup listing at a venue we scrape is
    only compared with that venue's listings."""
    kept = [e for e in events if e["venue"] not in roundups]
    for r in roundups:
        for e in [e for e in events if e["venue"] == r]:
            day = e["start"][:10]
            home = muse_home(e.get("where", ""))
            # Not against its own roundup: a play can have two showings a day.
            pool = [k for k in kept if k["start"][:10] == day and k["venue"] != r
                    and (home is None or k["venue"] == home)]
            drop = title_words(f"{e.get('where', '')} {home or ''}")
            if not any(same_listing(e["title"], k["title"], drop | title_words(k["venue"])) for k in pool):
                kept.append(e)
    for e in kept:
        e.pop("where", None)
    return kept


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

ICG_URL = "https://www.ithacachildrensgarden.org/icg-events/"
# The garden's calendar plugin is empty; each event has its own /portfolio/
# page with the date typed in, e.g. "October 17, 2026 | 1PM – 4PM".
ICG_DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)\b")


def scrape_icg():
    # The events page (body plus its Events menu) links every event; the home
    # page also links news stories, so it isn't used.
    links = []
    soup = BeautifulSoup(fetch(ICG_URL, "icg.html").text, "html.parser")
    for a in soup.select('a[href*="/portfolio/"]'):
        href = a["href"].split("#")[0]
        if href not in links:
            links.append(href)
    if not links:
        raise ValueError("no event pages linked from the events page")
    today = now().date()
    out = []
    for url in links:
        time.sleep(1)
        try:
            soup = BeautifulSoup(fetch(url).text, "html.parser")
        except requests.RequestException as e:
            print(f"Ithaca Children's Garden: skipped {url} ({e})", file=sys.stderr)
            continue
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else (soup.title.string or "").split("–")[0]
        lines = [" ".join(t.split()) for t in soup.get_text("\n").split("\n")]
        lines = [t for t in lines if t]
        seen = set()
        for n, line in enumerate(lines):
            m = ICG_DATE_RE.search(line)
            if not m:
                continue
            try:
                date = dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
            except ValueError:
                continue
            if date < today or date in seen:
                continue
            seen.add(date)
            clock = parse_clock(line[m.end():])
            if not clock and n + 1 < len(lines) and not ICG_DATE_RE.search(lines[n + 1]):
                clock = parse_clock(lines[n + 1])
            if clock:
                start = dt.datetime.combine(date, dt.time(*clock), TZ)
                out.append(event("Ithaca Children's Garden", title, start, url=url))
            else:
                start = dt.datetime.combine(date, dt.time(0), TZ)
                out.append(event("Ithaca Children's Garden", title, start, all_day=True, url=url))
    return out

BREWERS_URL = "https://brewersithaca.com/template-page"
# A Toast Sites page; its events come embedded as Apollo state JSON.


def find_key(obj, key):
    """Yield every value stored under `key` anywhere in nested JSON."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from find_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from find_key(v, key)


def scrape_brewers():
    page = fetch(BREWERS_URL, "brewers.html").text
    m = re.search(r"window\.__APOLLO_STATE__\s*=\s*", page)
    if not m:
        raise ValueError("no embedded event data on the page")
    # Other assignments follow the object in the same script, so decode just it.
    state, _ = json.JSONDecoder().raw_decode(page, m.end())
    out, seen = [], set()
    for events in find_key(state, "calendarEvents"):
        for ev in events or []:
            guid = ev.get("eventGuid")
            if not ev.get("eventDateTime") or guid in seen:
                continue
            seen.add(guid)
            # Drop the leading emoji the venue puts on every title.
            title = re.sub(r"^[^\w(\"'“]+", "", ev.get("name") or "").strip()
            start = dt.datetime.fromisoformat(ev["eventDateTime"].replace("Z", "+00:00")).astimezone(TZ)
            all_day = not ev.get("displayTime", True)
            if all_day:
                start = dt.datetime.combine(start.date(), dt.time(0), TZ)
            out.append(event("Brewer's Kitchen & Taproom", title, start, all_day=all_day,
                             url=ev.get("url") or BREWERS_URL,
                             description=ev.get("description") or ""))
    if not out and "calendarEvents" not in page:
        raise ValueError("event list missing from the page data")
    return out

T41_URL = "https://www.t41trivia.com/"
T41_DATE_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s*(20\d\d)")
# "from 6:00 - 8 p.m.": the start often borrows its a.m./p.m. from the end.
T41_TIME_RE = re.compile(
    r"from\s+(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?m?\.?\s*[-–]\s*\d{1,2}(?::\d{2})?\s*([ap])\.?m\.?", re.I)


T41_PLAY = "https://www.t41trivia.com/play/"
# "<a>Theme</a> at Ithaca Bakery tomorrow, on Thursday, October 29 at 6 p.m.."
T41_ITEM_RE = re.compile(
    r"^\s*at\s+(.+?)(?:\s+(?:today|tonight|tomorrow|in\s+[\w ]+?))?,\s*on\s+[A-Za-z]+,\s+"
    r"([A-Za-z]+)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?(?:\s+at\s+(.+?))?\.*\s*$")


def scrape_t41():
    """Every game under "Upcoming games" on /play/, plus the home page's Next
    Game card (which also gives the year) in case the list changes shape."""
    games = {}
    try:
        for e in t41_upcoming():
            games[e["url"]] = e
    except Exception as e:
        print(f"Table for One Trivia: /play/ list failed ({e})", file=sys.stderr)
    for e in t41_next_game():
        games.setdefault(e["url"], e)
    return list(games.values())


def t41_title(theme):
    # Game names are themes like "Halloweenies/MUSIC/Pats", so say it's trivia.
    theme = theme.replace("\u200b", "").strip()
    return f"Trivia: {theme}" if theme else "Trivia night"


def t41_upcoming():
    soup = BeautifulSoup(fetch(T41_PLAY, "t41play.html").text, "html.parser")
    heading = soup.find(lambda t: t.name in ("h2", "h3", "h4") and "upcoming games" in t.get_text().lower())
    if not heading:
        raise ValueError("no Upcoming games list")
    ul = heading.find_next_sibling("ul")
    today = now().date()
    out = []
    for li in ul.find_all("li", recursive=False) if ul else []:
        link = li.find("a")
        if not link:
            continue
        rest = " ".join("".join(str(x) for x in li.find_all(string=True, recursive=False)).split())
        m = T41_ITEM_RE.match(rest)
        if not m or m.group(2)[:3].lower() not in MONTHS:
            print(f"Table for One Trivia: couldn't read {rest!r}", file=sys.stderr)
            continue
        month, day = MONTHS[m.group(2)[:3].lower()], int(m.group(3))
        date = dt.date(int(m.group(4)), month, day) if m.group(4) else infer_year(month, day, today)
        when = (m.group(5) or "").lower()
        clock = (12, 0) if "noon" in when else parse_clock(when.replace(".", ""))
        url = requests.compat.urljoin(T41_PLAY, link["href"])
        title = t41_title(link.get_text(" ", strip=True))
        desc = f"at {m.group(1).strip()}"
        if clock:
            out.append(event("Table for One Trivia", title, dt.datetime.combine(date, dt.time(*clock), TZ),
                             url=url, description=desc))
        else:
            out.append(event("Table for One Trivia", title, dt.datetime.combine(date, dt.time(0), TZ),
                             all_day=True, url=url, description=desc))
    return out


def t41_next_game():
    """The home page shows the next game in a sidebar card."""
    soup = BeautifulSoup(fetch(T41_URL, "t41.html").text, "html.parser")
    heading = soup.find(lambda t: t.name in ("h2", "h3") and "next game" in t.get_text().lower())
    if not heading:
        raise ValueError("no Next Game panel on the home page")
    panel = heading.find_parent(class_="card") or heading.parent
    out = []
    for card in panel.select(".card-body .card") or [panel]:
        link = card.select_one(".card-header a") or card.find("a")
        title = t41_title(link.get_text(" ", strip=True) if link else "")
        text = " ".join(card.get_text(" ").split())
        m = T41_DATE_RE.search(text)
        if not m:
            continue
        date = dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        where = card.select_one('a[href*="/venue/"]')
        where = where.get_text(" ", strip=True) if where else ""
        url = requests.compat.urljoin(T41_URL, link["href"]) if link and link.get("href") else T41_URL
        tm = T41_TIME_RE.search(text)
        if tm:
            hour = int(tm.group(1)) % 12 + (12 if (tm.group(3) or tm.group(4)).lower() == "p" else 0)
            clock = (hour, int(tm.group(2) or 0))
        else:
            clock = parse_clock(text[m.end():])
        desc = f"at {where}" if where else ""
        if clock:
            out.append(event("Table for One Trivia", title, dt.datetime.combine(date, dt.time(*clock), TZ),
                             url=url, description=desc))
        else:
            out.append(event("Table for One Trivia", title, dt.datetime.combine(date, dt.time(0), TZ),
                             all_day=True, url=url, description=desc))
    return out


# --- The Cherry Arts --------------------------------------------------------

CHERRY_URL = "https://thecherry.org/"
# The season page is renamed each year (2026-27-arts-performance), so it's
# found from the home page's links, with this as the fallback.
CHERRY_SEASON = "https://thecherry.org/2026-27-arts-performance/"
CHERRY_SEASON_RE = re.compile(r"arts-performance|cherry-music|season", re.I)
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
# Ticket links on a show page read "Fri Nov 13 7:30PM".
CHERRY_PERF_RE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+" + _MON + r"\s+(\d{1,2})\b")
# "November 13-22, 2026", "November 6 - December 13, 2026", "December 4, 2026".
CHERRY_RANGE_RE = re.compile(
    r"\b" + _MON + r"\s+(\d{1,2})(?:\s*[-–—]\s*(?:" + _MON + r"\s+)?(\d{1,2}))?,?\s+(20\d\d)\b")


def cherry_show_links():
    pages = []
    try:
        soup = BeautifulSoup(fetch(CHERRY_URL, "cherry.html").text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].split("#")[0]
            if "thecherry.org" in href and CHERRY_SEASON_RE.search(href) and href not in pages:
                pages.append(href)
    except requests.RequestException as e:
        print(f"The Cherry Arts: home page failed ({e})", file=sys.stderr)
    if not any("arts-performance" in u for u in pages):
        pages.append(CHERRY_SEASON)
    links = []
    for n, page in enumerate(pages):
        try:
            soup = BeautifulSoup(fetch(page, f"cherry-season-{n}.html").text, "html.parser")
        except requests.RequestException as e:
            print(f"The Cherry Arts: skipped {page} ({e})", file=sys.stderr)
            continue
        for a in soup.select('a[href*="/cherry-events/"]'):
            href = a["href"].split("#")[0].split("?")[0]
            if href not in links:
                links.append(href)
    return links


def scrape_cherry():
    """The season pages link each show's page (/cherry-events/<slug>/). A show
    page lists its performances as OvationTix links ("Fri Nov 13 7:30PM");
    shows without those (gallery exhibitions, one-offs) only give a date
    range, which becomes all-day entries the way Hangar's runs do."""
    links = cherry_show_links()
    if not links:
        raise ValueError("no show pages linked from the season pages")
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    out = []
    for url in links:
        time.sleep(1)
        try:
            soup = BeautifulSoup(fetch(url).text, "html.parser")
        except requests.RequestException as e:
            print(f"The Cherry Arts: skipped {url} ({e})", file=sys.stderr)
            continue
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        if not title:
            og = soup.find("meta", property="og:title")
            title = (og.get("content") if og else (soup.title.string if soup.title else "")) or ""
            title = re.split(r"\s+[|–-]\s+", title)[0]
        if not title:
            continue
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        desc = (meta.get("content") or "") if meta else ""
        img = page_image(soup, url)

        perfs = set()
        for a in soup.select('a[href*="ovationtix.com"]'):
            if "/performance/" not in a["href"]:
                continue
            text = " ".join(a.get_text(" ").split())
            m = CHERRY_PERF_RE.search(text)
            clock = parse_clock(text[m.end():]) if m else None
            if not m or not clock:
                continue
            date = infer_year(MONTHS[m.group(1).lower()], int(m.group(2)), today)
            start = dt.datetime.combine(date, dt.time(*clock), TZ)
            if start.date() > horizon or start in perfs:
                continue
            perfs.add(start)
            out.append(event("The Cherry Arts", title, start, url=a["href"], description=desc, image=img))
        if perfs:
            continue

        # Look for the run's dates in the page body, below the title.
        body = soup.find("main") or soup.find("article") or soup.body or soup
        text = " ".join(body.get_text(" ").split())
        if title in text:
            text = text[text.index(title):]
        m = CHERRY_RANGE_RE.search(text)
        if not m:
            print(f"The Cherry Arts: no dates found on {url}", file=sys.stderr)
            continue
        m1, d1, m2, d2, year = m.groups()
        year = int(year)
        end_month = MONTHS[(m2 or m1).lower()[:3]]
        start_month = MONTHS[m1.lower()[:3]]
        try:
            first = dt.date(year - (start_month > end_month), start_month, int(d1))
            last = dt.date(year, end_month, int(d2 or d1))
        except ValueError:
            continue
        if last < today or first > horizon:
            continue
        days = (last - first).days + 1
        clock = parse_clock(text[m.end():m.end() + 40])
        if days == 1 and clock:
            out.append(event("The Cherry Arts", title, dt.datetime.combine(first, dt.time(*clock), TZ),
                             url=url, description=desc, image=img))
        elif days <= 7:
            for i in range(days):
                d = first + dt.timedelta(i)
                out.append(event("The Cherry Arts", title, dt.datetime.combine(d, dt.time(0), TZ),
                                 all_day=True, url=url, description=desc, image=img))
        else:
            # Exhibitions run for weeks: one entry on the opening day, or
            # today once it has opened, so a running show stays listed.
            span = f"Runs {first:%b %-d} – {last:%b %-d}. "
            out.append(event("The Cherry Arts", title, dt.datetime.combine(max(first, today), dt.time(0), TZ),
                             all_day=True, url=url, description=span + desc, image=img))
    return out


# --- Hands Four Dancers of Ithaca -------------------------------------------

H4D_URL = "https://www.hands4dancers.org/upcoming-dances"
# A Squarespace events page that also keeps every past dance, so it's
# filtered by date. (robots.txt disallows ?format=json/ical, so the HTML is
# read.) Dances move around town (LACS, CSMA, Stewart Park), so the place goes
# in the description.
GCAL_DATES_RE = re.compile(r"dates=(\d{8}T\d{6}Z)(?:%2F|/)(\d{8}T\d{6}Z)")


def h4d_times(art):
    """(start, end) for one listing: from its Google Calendar link (UTC), or
    else from the date and 24-hour times Squarespace prints."""
    for a in art.select('a[href*="google.com/calendar"]'):
        m = GCAL_DATES_RE.search(a["href"])
        if m:
            s, e = (dt.datetime.strptime(x, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(TZ)
                    for x in m.groups())
            return s, e
    date_tag = art.select_one("time.event-date[datetime]") or art.find("time", attrs={"datetime": True})
    if not date_tag:
        return None, None
    day = dt.date.fromisoformat(date_tag["datetime"][:10])
    start_tag = art.select_one(".event-time-12hr-start") or art.select_one(".event-time-12hr")
    end_tag = art.select_one(".event-time-12hr-end")
    clock = parse_clock(start_tag.get_text(" ")) if start_tag else None
    if not clock:
        return dt.datetime.combine(day, dt.time(0), TZ), None
    start = dt.datetime.combine(day, dt.time(*clock), TZ)
    end_clock = parse_clock(end_tag.get_text(" ")) if end_tag else None
    end_day = dt.date.fromisoformat(end_tag["datetime"][:10]) if end_tag and end_tag.get("datetime") else day
    end = dt.datetime.combine(end_day, dt.time(*end_clock), TZ) if end_clock else None
    return start, end


def scrape_h4d():
    soup = BeautifulSoup(fetch(H4D_URL, "hands4dancers.html").text, "html.parser")
    arts = soup.select("article.eventlist-event") or soup.select("article[class*=eventlist]")
    if not arts:
        raise ValueError("no event list on the page")
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    out = []
    for art in arts:
        link = art.select_one(".eventlist-title a[href]") or art.select_one("h1 a[href], h2 a[href]")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        start, end = h4d_times(art)
        if not title or not start or start.date() < today or start.date() > horizon:
            continue
        url = requests.compat.urljoin(H4D_URL, link["href"])
        where_tag = art.select_one(".eventlist-meta-address")
        where = ""
        if where_tag:
            street = ""
            for a in where_tag.select("a"):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(a.get("href", "")).query).get("q")
                street = street or (q[0].split(" Ithaca")[0].strip() if q else "")
                a.decompose()
            where = " ".join(where_tag.get_text(" ").split())
            if street and street.lower() not in where.lower():
                where = f"{where}, {street}" if where else street
        # The band and caller are in the listing's description.
        body = art.select_one(".eventlist-excerpt") or art.select_one(".eventlist-description")
        desc = " ".join((body.get_text(" ") if body else "").split())
        if where:
            desc = f"at {where.rstrip('.')}. {desc}".strip()
        img = None
        tag = art.select_one(".eventlist-column-thumbnail img") or art.find("img")
        if tag:
            src = tag.get("data-src") or tag.get("data-image") or tag.get("src")
            if src and not src.startswith("data:"):
                img = requests.compat.urljoin(H4D_URL, src)
        all_day = start.time() == dt.time(0) and end is None
        out.append(event("Hands Four Dancers", title, start, end=end, all_day=all_day,
                         url=url, description=desc, image=img))
    return out

# --- Argos Inn ---------------------------------------------------------------

ARGOS_URL = "https://www.argosinn.com/public-events"
# A Wix page with the shows typed in as free text, no feed and no event pages:
# a title (and sometimes a subtitle), then "Sunday, November 8th", a time
# like "6PM-8PM" or "Doors 7pm, Show 7:30pm", the room, the price, and a
# "MORE INFO HERE" link to the performer, Facebook or Eventbrite. A weekly
# section lists "Jazz Trio Performance" on "Wednesdays".
ARGOS_DATE_RE = re.compile(
    r"\b(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)(?:day)?\.?,?\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
ARGOS_WEEKLY_RE = re.compile(r"^(?:every\s+)?(mon|tues|wednes|thurs|fri|satur|sun)days?\b", re.I)
ARGOS_WEEKDAYS = ["mon", "tues", "wednes", "thurs", "fri", "satur", "sun"]
ARGOS_ROOMS = ("argos warehouse", "bar argos")
ARGOS_STOP_RE = re.compile(r"more info|^\w+\s+events$|^weekly events$", re.I)
ARGOS_WEEKLY_WEEKS = 4
CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?"


def argos_times(text, date):
    """(start, end) from 'Doors 7pm, Show 7:30pm', '6PM-8PM', '8PM-Midnight',
    '5:30 - 7:30pm'. The start borrows am/pm from the end when it has none."""
    t = text.lower().replace("noon", "12pm")

    def at(h, mi, ap, day=date):
        return dt.datetime.combine(day, dt.time(int(h) % 12 + (12 if ap[0] == "p" else 0), int(mi or 0)), TZ)

    show = re.search(r"show\s*(?:at\s*)?" + CLOCK, t)
    if show and show.group(3):
        return at(*show.groups()), None
    m = re.search(CLOCK + r"\s*(?:-|–|—|to)\s*(?:(midnight)|" + CLOCK + ")", t)
    if m:
        h1, m1, ap1, midnight, h2, m2, ap2 = m.groups()
        ap_end = "pm" if midnight else ap2
        ap_start = ap1 or ap_end
        if ap_start:
            start = at(h1, m1, ap_start)
            if midnight:
                end = dt.datetime.combine(date + dt.timedelta(days=1), dt.time(0), TZ)
            else:
                end = at(h2, m2, ap_end) if ap_end else None
                if end and end <= start:
                    end += dt.timedelta(days=1)
            return start, end
    clock = parse_clock(text)
    if clock:
        return dt.datetime.combine(date, dt.time(*clock), TZ), None
    return None, None


def argos_details(lines):
    """Pull the time text, room and the rest (price etc.) out of a block's lines."""
    when, room, rest = [], None, []
    for t in lines:
        low = t.lower()
        if re.search(r"\d\s*(?:[ap]\.?m|-|–)|midnight|doors|show", low) and not when:
            when.append(t)
        elif any(r in low for r in ARGOS_ROOMS) and len(t) < 40:
            room = re.sub(r"^location:\s*", "", t, flags=re.I)
        else:
            rest.append(t)
    return " ".join(when), room, rest


def scrape_argos():
    soup = BeautifulSoup(fetch(ARGOS_URL, "argos.html").text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    # Remember where each MORE INFO link goes, keyed by its position in the text.
    links = []
    for a in soup.find_all("a", href=True):
        if "more info" in a.get_text(" ").lower():
            links.append(a["href"])
            a.replace_with(soup.new_string("\nMORE INFO\n"))
    # Keep each poster in place too; it goes on the slideshow. Wix serves a
    # blurred thumbnail, and the original is the URL cut after the media id.
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        m = re.match(r"(https://static\.wixstatic\.com/media/[^/]+)", src)
        img.replace_with(soup.new_string(f"\nIMG {m.group(1)}\n" if m else "\n"))
    lines = [" ".join(t.split()) for t in soup.get_text("\n").split("\n")]
    lines = [t for t in lines if t and t not in ("|", "·")]
    images = {n: t[4:] for n, t in enumerate(lines) if t.startswith("IMG ")}
    today = now().date()
    horizon = today + dt.timedelta(days=DAYS_AHEAD)
    out, link_no = [], 0
    starts = [n for n, t in enumerate(lines) if ARGOS_DATE_RE.search(t) or ARGOS_WEEKLY_RE.match(t)]
    if not starts:
        raise ValueError("no dated events found on the page")
    for idx, n in enumerate(starts):
        # Title lines: just above the date, back to the previous block's end.
        head = []
        for t in reversed([t for t in lines[max(0, n - 4):n] if not t.startswith("IMG ")][-3:]):
            if ARGOS_STOP_RE.search(t) or ARGOS_DATE_RE.search(t):
                break
            head.insert(0, t)
        if not head:
            continue
        title, subtitle = head[0], head[1:]
        # Detail lines: after the date, up to MORE INFO or the next block's title.
        nxt = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        body, url, image = [], None, None
        m = ARGOS_DATE_RE.search(lines[n]) or ARGOS_WEEKLY_RE.match(lines[n])
        tail = lines[n][m.end():].strip(" |,-–")
        if tail:
            body.append(tail)
        for k, t in enumerate(lines[n + 1:nxt], start=n + 1):
            if k in images:
                image = image or images[k]
                continue
            if t == "MORE INFO":
                url = links[link_no] if link_no < len(links) else None
                link_no += 1
                break
            if ARGOS_STOP_RE.search(t):
                break
            body.append(t)
        when, room, rest = argos_details(body[:6])
        desc_parts = subtitle + ([f"at {room}"] if room else []) + rest
        desc = " · ".join(p.strip(" |") for p in desc_parts if p.strip(" |"))
        if ARGOS_DATE_RE.search(lines[n]):
            dates = [infer_year(MONTHS[m.group(1).lower()[:3]], int(m.group(2)), today)]
        else:
            wd = ARGOS_WEEKDAYS.index(m.group(1).lower())
            first = today + dt.timedelta(days=(wd - today.weekday()) % 7)
            dates = [first + dt.timedelta(weeks=w) for w in range(ARGOS_WEEKLY_WEEKS)]
        for date in dates:
            if not date or date < today or date > horizon:
                continue
            start, end = argos_times(when, date)
            ev_url = url or ARGOS_URL
            if start:
                out.append(event("Argos Inn", title, start, end=end, url=ev_url, description=desc,
                                 image=image))
            else:
                out.append(event("Argos Inn", title, dt.datetime.combine(date, dt.time(0), TZ),
                                 all_day=True, url=ev_url, description=desc, image=image))
    return out


VENUES = [
    ("Bike Bar", BIKEBAR_URL, scrape_bikebar),
    ("Liquid State Brewing", LIQUID_URL, scrape_liquid),
    ("K-HOUSE", KHOUSE_URL, scrape_khouse),
    ("Cinemapolis", CINEMAPOLIS_URL, scrape_cinemapolis),
    ("Hangar Theatre", HANGAR_URL, scrape_hangar),
    ("Hopshire", HOPSHIRE_URL, scrape_hopshire),
    ("The Cherry Arts", CHERRY_URL, scrape_cherry),
    ("Hands Four Dancers", H4D_URL, scrape_h4d),
    ("Argos Inn", ARGOS_URL, scrape_argos),
    ("State Theatre", STATE_URL, scrape_state),
    ("Brewer's Kitchen & Taproom", BREWERS_URL, scrape_brewers),
    ("Table for One Trivia", T41_URL, scrape_t41),
    (MUSE_VENUE, None, scrape_muse),
    ("Visit Ithaca", VISIT_URL, scrape_visitithaca),
    ("Trees Up Tompkins", TUT_URL, scrape_trees_up),
    ("Ithaca Children's Garden", ICG_URL, scrape_icg),
]


# --- Slideshow --------------------------------------------------------------

# On wide screens the page shows a slideshow of pictures of the coming days'
# performers and events. Pictures only come from an event's own page on the
# venue's site (or the venue's own API), never from a search, and a picture
# is dropped when it looks like a site-wide default rather than this event's:
# a logo, the venue home page's share image, or the same picture on two
# different events. They're saved, shrunk, into site/slides/.
SLIDES_MAX = 8
SLIDES_DAYS = 7
SLIDES_PER_VENUE = 2
SLIDE_WIDTH = 900
# Roundups link to other people's pages, so their pictures can't be vouched for.
SLIDES_SKIP_VENUES = {MUSE_VENUE, "Visit Ithaca"}
# Recurring house nights go to the back of the queue behind named performers.
ROUTINE_RE = re.compile(r"\b(trivia|bingo|open mic|book club|karaoke|jam|closed|meeting|roundtable|flight night|dj night)\b", re.I)
GENERIC_IMAGE_RE = re.compile(r"logo|favicon|placeholder|default|site-?icon|blank|spacer", re.I)

# Official performer videos. A scheduled Claude task searches YouTube nightly
# for the coming week's performers and writes data/videos.json:
# {"updated": ..., "videos": [{"venue", "title", "date" ("YYYY-MM-DD"),
# "performer", "youtube_id", "channel", "channel_url", "note"}], "checked":
# [{"venue", "title", "date"}]}. It only lists a video from the performer's
# own channel. Here each one is checked again with YouTube's oEmbed endpoint:
# it must still be public and embeddable and its uploader must be the channel
# the task named, or it's ignored and the slide keeps its picture.
VIDEOS_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "videos.json"
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def title_key(venue, title, date):
    return (venue, re.sub(r"[^a-z0-9]+", " ", title.lower()).strip(), date)


def channel_key(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower().replace("vevo", "").replace("official", ""))


def load_videos():
    """Videos from data/videos.json that YouTube confirms, keyed by title_key."""
    if not VIDEOS_FILE.exists():
        return {}
    out = {}
    for v in json.loads(VIDEOS_FILE.read_text()).get("videos", []):
        vid = v.get("youtube_id") or ""
        if not YOUTUBE_ID_RE.match(vid) or not v.get("channel"):
            continue
        try:
            r = requests.get("https://www.youtube.com/oembed", timeout=20, headers={"User-Agent": UA},
                             params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"})
            if r.status_code != 200:
                print(f"  video {vid} for {v.get('title')}: not embeddable ({r.status_code})", file=sys.stderr)
                continue
            meta = r.json()
        except Exception as ex:
            print(f"  video {vid} for {v.get('title')}: check failed ({ex})", file=sys.stderr)
            continue
        by_name = channel_key(meta.get("author_name")) == channel_key(v["channel"])
        by_url = bool(v.get("channel_url")) and (meta.get("author_url") or "").rstrip("/").lower() \
            == v["channel_url"].rstrip("/").lower().replace("://youtube.com", "://www.youtube.com")
        if not (by_name or by_url):
            print(f"  video {vid} for {v.get('title')}: uploader {meta.get('author_name')!r} "
                  f"is not {v['channel']!r}", file=sys.stderr)
            continue
        out[title_key(v["venue"], v["title"], v["date"])] = {
            "id": vid, "channel": meta.get("author_name") or v["channel"],
            "title": meta.get("title") or "", "thumb": meta.get("thumbnail_url")}
    return out


def page_image(soup, base):
    """The share picture a page declares (og:image or twitter:image), if any."""
    for attrs in ({"property": "og:image"}, {"name": "og:image"},
                  {"property": "og:image:secure_url"}, {"name": "twitter:image"},
                  {"property": "twitter:image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            return requests.compat.urljoin(base, tag["content"].strip())
    return None


def slide_candidates(events, venue_pages):
    """Upcoming non-film events with a page of their own or a checked video,
    soonest first, one entry per show. Shows with a video come first."""
    today = now().date()
    last = today + dt.timedelta(days=SLIDES_DAYS)
    seen, out = set(), []
    for e in events:
        if e["kind"] == "film" or (e["venue"] in SLIDES_SKIP_VENUES and not e.get("video")):
            continue
        if not (today <= dt.date.fromisoformat(e["start"][:10]) <= last):
            continue
        key = (e["venue"], e["title"].lower())
        if key in seen:
            continue
        page = (e.get("url") or "").split("#")[0].rstrip("/")
        own_page = page and page not in venue_pages and requests.compat.urlparse(page).path.strip("/")
        if not (e.get("image") or own_page or e.get("video")):
            continue
        seen.add(key)
        out.append(e)
    # Stable sort: soonest first within each group.
    return sorted(out, key=lambda e: (not e.get("video"), bool(ROUTINE_RE.search(e["title"]))))


def image_for(e):
    if e.get("image"):
        return e["image"]
    if e["venue"] in SLIDES_SKIP_VENUES or not e.get("url"):
        return None
    soup = BeautifulSoup(fetch(e["url"], attempts=2).text, "html.parser")
    return page_image(soup, e["url"])


def load_picture(url):
    """Download a picture and return it as a resized RGB Pillow image, or None
    when it's too small or oddly shaped to be a performer or event photo."""
    from PIL import Image
    import io
    r = fetch(url, attempts=2)
    if not r.headers.get("content-type", "image/").startswith("image/") or len(r.content) > 15_000_000:
        return None, None
    img = Image.open(io.BytesIO(r.content))
    img.load()
    w, h = img.size
    if w < 400 or h < 250 or not (0.5 <= w / h <= 2.6):
        return None, None
    digest = hashlib.sha1(img.convert("RGB").resize((16, 16)).tobytes()).hexdigest()
    img = img.convert("RGB")
    if w > SLIDE_WIDTH:
        img = img.resize((SLIDE_WIDTH, round(h * SLIDE_WIDTH / w)), Image.LANCZOS)
    return img, digest


def video_picture(video):
    """The video's own thumbnail, for a show with no picture of its own."""
    for url in (f"https://i.ytimg.com/vi/{video['id']}/maxresdefault.jpg", video.get("thumb"),
                f"https://i.ytimg.com/vi/{video['id']}/hqdefault.jpg"):
        if not url:
            continue
        try:
            pic, digest = load_picture(url)
        except Exception:
            continue
        if pic is not None:
            return url, pic, digest
    return None, None, None


def build_slides(events, out_dir):
    venue_pages = {u.rstrip("/") for _, u, _ in VENUES if u}
    try:
        videos = load_videos()
    except Exception:
        traceback.print_exc()
        videos = {}
    for e in events:
        v = videos.get(title_key(e["venue"], e["title"], e["start"][:10]))
        if v:
            e["video"] = v
    print(f"slideshow: {len(videos)} checked videos, {sum(1 for e in events if e.get('video'))} matched to events")
    candidates = slide_candidates(events, venue_pages)
    # The venue home page's share picture is the site default; don't use it.
    home_images = {}
    found = []  # (event, image url, picture, digest)
    for e in candidates:
        if len(found) >= SLIDES_MAX * 3:
            break
        src = pic = digest = None
        try:
            src = image_for(e)
            if not src or GENERIC_IMAGE_RE.search(requests.compat.urlparse(src).path):
                src = None
            venue_url = next((u for n, u, _ in VENUES if n == e["venue"]), None)
            if src and venue_url and e["venue"] not in home_images:
                try:
                    home = BeautifulSoup(fetch(venue_url, attempts=1).text, "html.parser")
                    home_images[e["venue"]] = page_image(home, venue_url)
                except requests.RequestException:
                    home_images[e["venue"]] = None
            if src and src != home_images.get(e["venue"]):
                pic, digest = load_picture(src)
        except Exception as ex:
            print(f"  slides: no picture for {e['venue']} / {e['title']} ({ex})", file=sys.stderr)
        if pic is None and e.get("video"):
            src, pic, digest = video_picture(e["video"])
        if pic is not None:
            found.append((e, src, pic, digest))

    # A picture used for two different shows is a placeholder, not a performer.
    by_digest, by_src = {}, {}
    for e, src, _, digest in found:
        by_digest.setdefault(digest, set()).add(e["title"].lower())
        by_src.setdefault(src, set()).add(e["title"].lower())
    found = [f for f in found if len(by_digest[f[3]]) == 1 and len(by_src[f[1]]) == 1]

    # Soonest first, but at most two per venue unless there's room to spare.
    picked, counts = [], {}
    for e, *_ in found:
        if len(picked) < SLIDES_MAX and counts.get(e["venue"], 0) < SLIDES_PER_VENUE:
            picked.append(e)
            counts[e["venue"]] = counts.get(e["venue"], 0) + 1
    for e, *_ in found:
        if len(picked) < SLIDES_MAX and e not in picked:
            picked.append(e)
    picked.sort(key=lambda e: e["start"])
    pics = {id(e): (src, pic) for e, src, pic, _ in found}

    slide_dir = out_dir / "slides"
    slide_dir.mkdir(exist_ok=True)
    for old in slide_dir.glob("*.jpg"):
        old.unlink()
    slides = []
    for i, e in enumerate(picked, 1):
        src, pic = pics[id(e)]
        name = f"slides/{i}.jpg"
        pic.save(out_dir / name, "JPEG", quality=80, optimize=True, progressive=True)
        slide = {"image": name, "source": src, "title": e["title"], "venue": e["venue"],
                 "start": e["start"], "all_day": e["all_day"], "url": e.get("url")}
        if e.get("video"):
            slide["video"] = {k: e["video"][k] for k in ("id", "channel", "title")}
        slides.append(slide)
        video = f"  + video {e['video']['id']} ({e['video']['channel']})" if e.get("video") else ""
        print(f"  slide {i}: {e['start'][:16]}  {e['venue']}  {e['title']}  <- {src}{video}")
    return slides


def write_upcoming(events, path):
    """A short list of the coming week's shows (no films) for the scheduled
    task that looks for performer videos; events.json is too long to read."""
    today = now().date()
    last = today + dt.timedelta(days=SLIDES_DAYS + 1)
    seen, shows = set(), []
    for e in events:
        date = e["start"][:10]
        key = title_key(e["venue"], e["title"], date)
        if e["kind"] == "film" or key in seen or not (today <= dt.date.fromisoformat(date) <= last):
            continue
        seen.add(key)
        shows.append({"venue": e["venue"], "title": e["title"], "date": date, "start": e["start"],
                      "url": e.get("url"),
                      "description": (e.get("description") or "")[:200]})
    path.write_text(json.dumps({"generated_at": now().isoformat(timespec="seconds"), "shows": shows}, indent=1))


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
    events = drop_roundup_duplicates(events, [MUSE_VENUE, "Visit Ithaca"])
    events.sort(key=lambda e: (e["start"], e["venue"], e["title"]))
    try:
        slides = build_slides(events, out_dir)
    except Exception:
        traceback.print_exc()
        slides = []
    print(f"slideshow: {len(slides)} pictures")
    for e in events:
        e.pop("image", None)
        e.pop("video", None)
    data = {"generated_at": now().isoformat(timespec="seconds"),
            "venues": venues, "events": events, "slides": slides}
    (out_dir / "events.json").write_text(json.dumps(data, indent=1))
    write_upcoming(events, out_dir / "upcoming.json")
    write_ics(events, out_dir / "ithaculture.ics")
    for e in events:
        print(f"  {e['start'][:16]}  {e['venue']:<20}  {e['title']}")
    print(f"wrote {len(events)} events")
    if not any(v["ok"] for v in venues):
        sys.exit("every venue failed")


if __name__ == "__main__":
    main()
