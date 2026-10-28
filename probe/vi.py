import re, requests, html
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
r = s.get("https://www.t41trivia.com/", timeout=30)
p = r.text
print("STATUS", r.status_code, len(p))
print("GEN", re.findall(r'<meta[^>]+generator[^>]+>', p)[:3])
for m in re.findall(r'(?:src|href)="([^"]*(?:calendar|ical|\.ics|eventbrite|events|google)[^"]*)"', p)[:20]: print("LINK", m)
body = re.sub(r"(?s)<(script|style|noscript)\b.*?</\1>", " ", p)
txt = html.unescape(re.sub(r"\s*\n\s*", "\n", re.sub(r"<[^>]+>", "\n", body)))
i = txt.lower().find("next game")
print("TEXT-AROUND-NEXT", txt[max(0,i-300):i+1500] if i >= 0 else txt[:3000])
j = p.lower().find("next game")
print("RAW-AROUND-NEXT", re.sub(r"\s+"," ", p[max(0,j-500):j+2500]) if j >= 0 else "none")
