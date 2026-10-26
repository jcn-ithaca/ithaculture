import re, requests, html
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
r = s.get("https://brewersithaca.com/template-page", timeout=30)
p = r.text
print("STATUS", r.status_code, len(p))
print("GEN", re.findall(r'<meta[^>]+generator[^>]+>', p)[:3])
for m in re.findall(r'(?:src|href)="([^"]*(?:calendar|ical|\.ics|eventbrite|events|toast)[^"]*)"', p)[:20]: print("LINK", m)
for m in re.findall(r'application/ld\+json[^>]*>(.{0,800})', p, re.S)[:3]: print("LD", m[:800])
body = re.sub(r"(?s)<(script|style|noscript)\b.*?</\1>", " ", p)
txt = html.unescape(re.sub(r"\s*\n\s*", "\n", re.sub(r"<[^>]+>", "\n", body)))
print("TEXT-START"); print(txt[:5000]); print("TEXT-END")
for k in ["__NEXT_DATA__", "window.__", "events", "startDate", "eventDate"]:
    i = p.find(k)
    if i >= 0: print("K", k, "::", re.sub(r"\s+"," ", p[max(0,i-200):i+800]))
