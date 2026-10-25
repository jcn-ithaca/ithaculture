import re, requests
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
base = "https://www.cinemapolis.org"
p = s.get(base + "/now-showing", timeout=30).text
srcs = re.findall(r'<script[^>]*\ssrc=["\']?([^"\' >]+)', p)
print("SRCS", srcs)
i = p.find("Showtime Quick Selector"); print("QS", re.sub(r"\s+"," ", p[i:i+300]))
for src in srcs:
    if "acsb" in src: continue
    u = requests.compat.urljoin(base + "/", src)
    js = s.get(u, timeout=30).text
    print("JS", u, len(js))
    for pat in [r"graphql[^\"'`]{0,80}", r"[\"'`](/?api/[^\"'`]{0,120})", r"https?://[a-z0-9.-]+/[^\"'`\s]{0,80}", r"showings?By[A-Za-z]*", r"[\"'`][^\"'`]*(?:showing|showtime)[^\"'`]*[\"'`]"]:
        ms = list(dict.fromkeys(re.findall(pat, js)))[:25]
        for m in ms: print("  ", pat[:14], "::", m[:200])
