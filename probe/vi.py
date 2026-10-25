import json, requests, datetime as dt
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)", "client-type": "consumer", "site-id": "30", "circuit-id": "31"})
base = "https://www.cinemapolis.org"
d2 = (dt.date.today() + dt.timedelta(days=2)).isoformat()
def gql(q, v=None):
    r = s.post(base + "/graphql", json={"query": q, "variables": v or {}}, timeout=30)
    print("GQL", q[:80], "::", r.status_code, r.text[:1500].replace("\n", " ")); print("--")
gql('query($d:String){ showingsForDate(date:$d){ data { id time movie { id name } } } }', {"d": d2})
gql('query($d:String){ showingsForDate(date:$d){ data { id time movie { name } } count } }', {"d": d2})
gql('query($d:String,$s:ID){ showingsForDate(date:$d, siteIds:[$s]){ data { id time movie { name } } } }', {"d": d2, "s": "30"})
