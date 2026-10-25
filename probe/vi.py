import re, requests
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
p = s.get("https://www.cinemapolis.org/now-showing", timeout=30).text
print("len", len(p))
for pat in [r"(?i)data-date[^>]{0,200}", r"(?i)<(?:button|a)[^>]*(?:date|day)[^>]*>.{0,120}", r"(?i)admin-ajax[^\"']{0,200}", r"(?i)wp-json[^\"']{0,150}", r"(?i)ajax[_-]?url[^,;]{0,200}", r"(?i)action\s*[:=]\s*['\"][a-z_]+['\"]", r"(?i)\?date=[^\"']{0,60}", r"(?i)showtimes?[-_]date[^\"' ]{0,80}"]:
    ms = list(dict.fromkeys(re.findall(pat, p, re.S)))[:8]
    for m in ms: print("P", pat[:22], "::", re.sub(r"\s+", " ", m)[:300])
for src in re.findall(r'<script[^>]+src="([^"]+)"', p): print("SCRIPT", src)
i = p.find("checkout/showing")
print("AROUND-FIRST-SHOWING", re.sub(r"\s+", " ", p[max(0,i-4000):i+300]))
