import json, requests, datetime as dt
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)", "client-type": "consumer"})
base = "https://www.cinemapolis.org"
d2 = (dt.date.today() + dt.timedelta(days=2)).isoformat()
def gql(q, v=None, h=None):
    r = s.post(base + "/graphql", json={"query": q, "variables": v or {}}, headers=h or {}, timeout=30)
    print("GQL", q[:70], "::", r.status_code, r.text[:900].replace("\n", " ")); print("--")
    return r
gql('query($d:String){ showingsForDate(date:$d){ data { id time movie { name } } } }', {"d": d2})
gql('{ __type(name:"Query"){ fields { name } } }')
gql('{ configuration { currentSite { id circuitId name } } }')
gql('{ currentSite { id circuitId name } }')
gql('{ site { id circuitId name } }')
gql('{ ShowingList: __type(name:"ShowingList"){ fields { name } } }')
gql('{ __type(name:"Showing"){ fields { name } } }')
