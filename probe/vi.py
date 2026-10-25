import re, requests
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
js = s.get("https://www.cinemapolis.org/js/app.ba25aaca.js", timeout=30).text
i = js.find("ye={gqlUri:u")
print("BEFORE", js[i-2500:i].replace("\n"," "))
for pat in [r"(?i)(?:site|sites)(?:For|By)Host(?:name)?", r"(?i)hostname[A-Za-z]*\s*:", r"(?i)window\.location\.host(?:name)?"]:
    for m in list(re.finditer(pat, js))[:4]:
        print("JS", pat[:20], "::", js[max(0,m.start()-250):m.start()+250].replace("\n"," ")); print("--")
