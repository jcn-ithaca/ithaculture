import re, requests, datetime as dt
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
base = "https://www.cinemapolis.org"
def ids(u):
    t = s.get(u, timeout=30).text
    return re.findall(r"/checkout/showing/[^/]+/(\d+)", t)
d2 = (dt.date.today() + dt.timedelta(days=2)).isoformat()
b = ids(base + "/now-showing"); print("BASE", len(b), b[:6])
for q in [f"?date={d2}", f"/{d2}", f"?day={d2}", f"?selectedDate={d2}"]:
    x = ids(base + "/now-showing" + q); print("Q", q, len(x), x[:6], "same" if x == b else "DIFF")
js = s.get(base + "/js/app.ba25aaca.js", timeout=30).text
for pat in [r"showingsForDate", r"api-us\.indy\.systems[^\"'`]{0,60}", r"(?i)x-[a-z-]*(?:site|client|tenant|key)[a-z-]*", r"(?i)siteId", r"(?i)uri:\s*[^,]{0,100}"]:
    for m in list(dict.fromkeys(m.start() for m in re.finditer(pat, js)))[:4]:
        print("JS", pat[:20], "::", js[max(0,m-250):m+350].replace("\n"," "))
        print("--")
