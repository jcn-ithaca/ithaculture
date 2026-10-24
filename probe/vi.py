import re, requests
s = requests.Session(); s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ithaculture/1.0; +https://jcn-ithaca.github.io/ithaculture/)"})
for u in ["https://www.visitithaca.com/robots.txt", "https://www.visitithaca.com/sitemap.xml", "https://www.visitithaca.com/event/rss/",
          "https://www.visitithaca.com/events/rss/", "https://www.visitithaca.com/includes/rest_v2/plugins_events_events_by_date/find/?json=%7B%7D&token=x"]:
    try:
        r = s.get(u, timeout=30)
        print("URL", u, r.status_code, r.headers.get("content-type"), len(r.text)); print(r.text[:1500]); print("----")
    except Exception as e:
        print("URL", u, "ERR", e)
