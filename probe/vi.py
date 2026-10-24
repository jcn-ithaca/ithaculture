import json, re, datetime as dt, requests
UA_BOT = "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"
UA_BR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
s = requests.Session(); s.headers.update({"User-Agent": UA_BOT})
page = s.get("https://www.visitithaca.com/events/live-music/", timeout=30).text
i = page.find("rest_v2/plugins_events_events_by_date")
print("JS-CONTEXT-START"); print(page[i-3000:i+1500]); print("JS-CONTEXT-END")
tok = s.get("https://www.visitithaca.com/plugins/core/get_simple_token/", timeout=30).text.strip()
now = dt.datetime.now(dt.timezone.utc)
q = {"filter": {"active": True, "$and": [{"categories.catId": {"$in": ["2"]}}],
     "date_range": {"start": {"$date": now.strftime("%Y-%m-%dT04:00:00.000Z")},
     "end": {"$date": (now + dt.timedelta(days=42)).strftime("%Y-%m-%dT04:00:00.000Z")}}},
     "options": {"limit": 200, "skip": 0, "count": True, "castDocs": False,
     "fields": {"categories": 1, "location": 1, "title": 1, "url": 1, "startDate": 1, "endDate": 1, "startTime": 1,
                "endTime": 1, "listing.title": 1, "listing.url": 1, "date": 1, "recurType": 1},
     "hooks": [], "sort": {"date": 1, "rank": 1, "title_sort": 1}}}
url = "https://www.visitithaca.com/includes/rest_v2/plugins_events_events_by_date/find/"
variants = {
  "bot": {},
  "bot+xhr": {"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.visitithaca.com/events/live-music/", "Accept": "application/json"},
  "browser+xhr": {"User-Agent": UA_BR, "X-Requested-With": "XMLHttpRequest", "Referer": "https://www.visitithaca.com/events/live-music/", "Accept": "application/json, text/javascript, */*; q=0.01"},
}
for name, h in variants.items():
    r = s.get(url, params={"json": json.dumps(q), "token": tok}, headers=h, timeout=30)
    print("VARIANT", name, r.status_code, r.headers.get("content-type"), r.text[:150].replace("\n"," "))
    if r.ok and "json" in (r.headers.get("content-type") or ""):
        d = r.json()["docs"]
        print("count", d.get("count"), "docs", len(d["docs"]))
        for e in d["docs"][:3]: print("SAMPLE", json.dumps(e)[:800])
        for e in d["docs"]: print("M", e.get("date","")[:10], e.get("startTime"), "|", e.get("title"), "|", e.get("location"), "|", (e.get("listing") or {}).get("title"))
        break
