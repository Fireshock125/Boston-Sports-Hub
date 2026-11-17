#!/usr/bin/env python3
"""Refresh Patriots game-specific NFL TV networks from ESPN.
Never infer a specific Sky/5/foreign feed from general league rights.
"""
import datetime as dt
import json
import pathlib
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "patriots-tv-channels.json"
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/17/schedule"
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent":"BostonSportsHub/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)

def main():
    data = json.loads(OUT.read_text()) if OUT.exists() else {"games":{}}
    games = data.setdefault("games",{})
    now = dt.datetime.now(dt.timezone.utc)
    count = 0
    successes = 0
    for season in (now.year,now.year-1):
        for typ in (1,2,3):
            try:
                events = fetch(f"{URL}?season={season}&seasontype={typ}").get("events",[])
                successes += 1
            except Exception as exc:
                print("Schedule unavailable:",exc)
                continue
            for event in events:
                try:
                    date = dt.datetime.fromisoformat(event["date"].replace("Z","+00:00"))
                    if not -120 <= (date-now).days <= 120: continue
                    competition = event["competitions"][0]
                    competitors = competition["competitors"]
                    if not any(str(c.get("team",{}).get("id")) == "17" for c in competitors):
                        continue
                    opponent = next(c["team"]["displayName"] for c in competitors if str(c["team"].get("id")) != "17")
                    key = date.astimezone(ZoneInfo("America/New_York")).date().isoformat()+"|"+opponent
                    names = set()
                    for b in competition.get("broadcasts",[]) + event.get("broadcasts",[]):
                        names.update(n.strip() for n in b.get("names",[]) if isinstance(n,str) and n.strip())
                        if isinstance(b.get("name"),str): names.add(b["name"].strip())
                    names = {n for n in names if not any(term in n.casefold() for term in ("redzone", "red zone", "highlights", "recap", "nfl network highlights"))}
                    if not names: continue
                    channels = games.setdefault(key,{"channels":[]})["channels"]
                    for name in sorted(names):
                        if any(c["name"].casefold()==name.casefold() for c in channels): continue
                        channels.append({"name":name,"region":"USA","status":"ESPN game-specific listing","source":"https://www.espn.com/nfl/schedule"})
                        count += 1
                except (KeyError,TypeError,StopIteration,ValueError) as exc:
                    print("Skipped event:",exc)
    if not successes: raise SystemExit("No schedule feeds succeeded; preserving old data")
    data["lastAutoRefresh"]=now.isoformat()
    OUT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n")
    print("Added",count,"game-specific broadcast networks")
if __name__=="__main__":
    main()
