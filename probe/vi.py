import json, re, datetime as dt, requests
from collections import Counter
H = {"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"}
s = requests.Session(); s.headers.update(H)
page = s.get("https://www.visitithaca.com/events/live-music/", timeout=30)
print("page", page.status_code, len(page.text))
for pat in [r"catId[^,\]}]{0,80}", r"rest_v2[^\"']{0,200}", r"categor[^\n]{0,200}", r"plugins_events[^\"']{0,200}"]:
    for m in list(dict.fromkeys(re.findall(pat, page.text)))[:8]:
        print("PAGE", pat[:10], m[:250])
for src in re.findall(r'<script[^>]+src="([^"]+)"', page.text):
    print("SCRIPT", src)
tok = s.get("https://www.visitithaca.com/plugins/core/get_simple_token/", timeout=30).text.strip()
print("token", tok)
now = dt.datetime.now(dt.timezone.utc)
q = {"filter": {"active": True, "date_range": {"start": {"$date": now.strftime("%Y-%m-%dT04:00:00.000Z")},
     "end": {"$date": (now + dt.timedelta(days=42)).strftime("%Y-%m-%dT04:00:00.000Z")}}},
     "options": {"limit": 500, "skip": 0, "count": True, "castDocs": False,
     "fields": {"categories": 1, "location": 1, "title": 1, "url": 1, "startDate": 1, "endDate": 1, "startTime": 1,
                "endTime": 1, "listing.title": 1, "listing.url": 1, "date": 1, "recurType": 1, "listingid": 1},
     "hooks": [], "sort": {"date": 1, "rank": 1, "title_sort": 1}}}
r = s.get("https://www.visitithaca.com/includes/rest_v2/plugins_events_events_by_date/find/",
          params={"json": json.dumps(q), "token": tok}, timeout=30)
print("api", r.status_code, r.text[:300])
try:
    d = r.json()["docs"]
    print("count", d.get("count"), "docs", len(d["docs"]))
    cats = Counter((c.get("catId"), c.get("catName")) for e in d["docs"] for c in e.get("categories", []))
    for k, v in cats.most_common(): print("CAT", k, v)
    for e in d["docs"][:5]: print("SAMPLE", json.dumps(e)[:600])
    live = [e for e in d["docs"] if any("music" in (c.get("catName") or "").lower() for c in e.get("categories", []))]
    print("music events", len(live))
    for e in live: print("M", e.get("date","")[:10], e.get("startTime"), "|", e.get("title"), "|", e.get("location"), "|", (e.get("listing") or {}).get("title"))
except Exception as ex:
    print("parse fail", ex)
