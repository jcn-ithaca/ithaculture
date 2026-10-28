import re, requests, html
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
for u in ["https://www.t41trivia.com/play/", "https://www.t41trivia.com/play/sessions/"]:
    r = s.get(u, timeout=30, allow_redirects=True)
    p = r.text
    print("URL", u, "->", r.url, r.status_code, len(p))
    i = p.find("<main"); i = i if i >= 0 else p.find("<body")
    body = re.sub(r"(?s)<(script|style|noscript|nav|footer)\b.*?</\1>", " ", p[i:])
    print("RAW", re.sub(r"\s+", " ", body)[:6000])
    print("=====")
