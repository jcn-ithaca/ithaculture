import re, json, requests, datetime as dt
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
base = "https://www.cinemapolis.org"
p = s.get(base + "/now-showing", timeout=30).text
for m in re.findall(r"<script>(.{0,600}?)</script>", p, re.S)[:6]: print("INLINE", re.sub(r"\s+"," ", m)[:600])
for m in re.findall(r"<meta[^>]+>", p)[:30]: print("META", m[:200])
js = s.get(base + "/js/app.ba25aaca.js", timeout=30).text
for pat in [r"(?i)[\"'](?:x-)?site-?id[\"']", r"(?i)[\"']client-?type[\"']", r"(?i)[\"']circuit-?id[\"']", r"headers:\{[^}]{0,200}", r"siteId:D", r"(?i)getSiteId|currentSiteId|site_id"]:
    for m in list(re.finditer(pat, js))[:4]:
        print("JS", pat[:18], "::", js[max(0,m.start()-300):m.start()+300].replace("\n"," ")); print("--")
