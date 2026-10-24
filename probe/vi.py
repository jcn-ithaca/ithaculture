import re, requests
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
p = s.get("https://www.visitithaca.com/event/bryan-jacobson-live/8489/", timeout=30).text
for k in ["startTime", "startDate", "\"location\"", "listing", "Bryan Jacobson Live", "recurrence", "\"date\""]:
    for m in [m.start() for m in re.finditer(re.escape(k), p)][:3]:
        print("K", k, "::", re.sub(r"\s+", " ", p[max(0,m-300):m+700]))
        print("--")
