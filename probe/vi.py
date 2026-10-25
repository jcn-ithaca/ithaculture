import re, json, requests, datetime as dt
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
base = "https://www.cinemapolis.org"
p = s.get(base + "/now-showing", timeout=30).text
for m in re.findall(r"(?i).{0,80}site_?id.{0,80}", p)[:5]: print("PAGE-SITEID", m)
js = s.get(base + "/js/app.ba25aaca.js", timeout=30).text
for m in re.finditer(r"siteId:D,", js):
    pass
for m in list(re.finditer(r"[,;]D=([^,;]{0,120})", js))[:5]: print("D=", m.group(1))
for m in list(re.finditer(r"[,;]w=([^,;]{0,120})", js))[:3]: print("w=", m.group(1))
d2 = (dt.date.today() + dt.timedelta(days=2)).isoformat()
def gql(q, v=None):
    r = s.post(base + "/graphql", json={"query": q, "variables": v or {}}, timeout=30)
    print("GQL", r.status_code, r.text[:1200].replace("\n", " ")); print("--")
gql('{ __typename }')
gql('query($d:String){ showingsForDate(date:$d){ data { id time movie { name } } } }', {"d": d2})
gql('query($d:String){ showingsForDate(date:$d){ id time movie { name } } }', {"d": d2})
gql('query($d:String){ showingsForDate(date:$d){ data { id } count } }', {"d": d2})
