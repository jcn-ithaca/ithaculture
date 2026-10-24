import re, requests, xml.etree.ElementTree as ET
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
def items(u):
    r = s.get(u, timeout=30)
    try: root = ET.fromstring(r.content)
    except Exception as e: return r.status_code, None
    return r.status_code, root.findall("./channel/item")
code, its = items("https://www.visitithaca.com/event/rss/")
print("base", code, len(its))
from collections import Counter
print(Counter(c.text.strip() for i in its for c in i.findall("category")).most_common())
for i in its[:2]:
    print("ITEM", ET.tostring(i, encoding="unicode")[:2500])
music = [i for i in its if any("Music" in (c.text or "") for c in i.findall("category"))]
for i in music: print("M", i.findtext("pubDate"), "|", i.findtext("title"), "|", i.findtext("link"))
for q in ["?categoryid=2", "?catid=2", "?category=2", "?categories=2", "?cat=2", "?limit=200", "?count=200", "?days=42"]:
    c, x = items("https://www.visitithaca.com/event/rss/" + q)
    print("Q", q, c, None if x is None else len(x), None if not x else x[0].findtext("title"))
if music:
    u = music[0].findtext("link")
    p = s.get(u, timeout=30)
    print("DETAIL", u, p.status_code, len(p.text))
    for pat in [r'application/ld\+json[^>]*>(.{0,1500})', r'(?s)class="[^"]*(?:dates|date|time|location|address)[^"]*"[^>]*>(.{0,300})']:
        for m in re.findall(pat, p.text, re.S)[:6]: print("D", re.sub(r"\s+", " ", m)[:600])
