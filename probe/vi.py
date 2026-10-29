import re, requests, html
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
r = s.get("https://hopshire.com/hopshire-events/", timeout=30); p = r.text
print("STATUS", r.status_code, len(p))
print("GEN", re.findall(r'<meta[^>]+generator[^>]+>', p)[:3])
for m in sorted(set(re.findall(r'(?:src|href)="([^"]*(?:calendar|ical|\.ics|tribe|eventbrite|events|wp-json|google)[^"]*)"', p)))[:25]: print("LINK", m)
for k in ["tribe", "ical", "data-calendar", "fullcalendar", "eventon", "ajde", "mec-", "simcal", "ai1ec", "tockify", "timely"]:
    print("HAS", k, p.lower().count(k))
for m in re.findall(r'application/ld\+json[^>]*>(.{0,600})', p, re.S)[:3]: print("LD", m[:600])
body = re.sub(r"(?s)<(script|style|noscript|header|footer|nav)\b.*?</\1>", " ", p)
txt = html.unescape(re.sub(r"\s*\n\s*", "\n", re.sub(r"<[^>]+>", "\n", body)))
print("TEXT", txt[:4000])
for u in ["https://hopshire.com/wp-json/tribe/events/v1/events?per_page=5", "https://hopshire.com/events/?ical=1"]:
    rr = s.get(u, timeout=30); print("TRY", u, rr.status_code, rr.headers.get("content-type"), rr.text[:400].replace("\n"," "))
