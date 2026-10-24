import re, requests, html, xml.etree.ElementTree as ET
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
base = "https://www.visitithaca.com/event/rss/"
def titles(u):
    r = s.get(u, timeout=30)
    try: return [(i.findtext("pubDate")[:16], i.findtext("title")[:40]) for i in ET.fromstring(r.content).findall("./channel/item")]
    except Exception: return r.status_code
b = titles(base); print("BASE", b[0], b[-1])
for q in ["?page=2", "?skip=30", "?offset=30", "?start=30", "?startDate=11/07/2026", "?startdate=11/07/2026&enddate=11/14/2026", "?date=11/07/2026", "?sdate=2026-11-07&edate=2026-11-14", "?days=14"]:
    t = titles(base + q); print("Q", q, t if isinstance(t, int) else (len(t), t[0], t[-1]))
for u in ["https://www.visitithaca.com/event/bryan-jacobson-live/8489/", "https://www.visitithaca.com/event/fabi-at-the-south-hill-cider-community-concert-series/10062/"]:
    p = s.get(u, timeout=30).text
    p = re.sub(r"(?s)<(script|style|nav|header|footer)\b.*?</\1>", " ", p)
    txt = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", p)))
    txt = re.sub(r"(\|\s*)+", "| ", txt)
    i = txt.find("Bryan Jacobson Live") if "bryan" in u else txt.find("Fabi at")
    print("DETAIL", u); print(txt[max(0,i-200):i+2500])
    for m in re.findall(r'(?s)<div[^>]+class="[^"]*(?:detail|info|dates|times|location|address)[^"]*"', s.get(u).text)[:15]: print("CLS", m[:150])
