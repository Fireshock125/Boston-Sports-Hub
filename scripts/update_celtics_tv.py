#!/usr/bin/env python3
"""Refresh Celtics TV listings from ESPN game-specific broadcast metadata.

Preserves individually sourced international/UK listings in the JSON. Never
infers a channel from a general broadcast-rights agreement.
"""
import datetime as dt
import json
import pathlib
import urllib.request
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "celtics-tv-channels.json"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/2/schedule"
COUNTRY = "USA"

SKY_SCHEDULE = "https://www.skysports.com/nba/news/13599587/nba-on-sky-sports-dates-schedule-uk-start-times-and-how-to-watch-or-stream-live-regular-season-and-playoff-action"

class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, text):
        self.parts.append(text)

def refresh_sky_schedule(games, events_by_key):
    """Store UK broadcast evidence, without inventing a specific Sky channel."""
    request = urllib.request.Request(SKY_SCHEDULE, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        html = response.read().decode("utf-8", "replace")
    parser = PageText()
    parser.feed(html)
    page = " ".join(" ".join(parser.parts).split()).casefold()
    count = 0
    for key, (home, away) in events_by_key.items():
        if (away + " @ " + home).casefold() not in page:
            continue
        record = games.setdefault(key, {"channels": []})
        channels = record.setdefault("channels", [])
        if not any(c.get("name", "").casefold().startswith("sky sports") for c in channels):
            channels.append({"name": "Sky Sports", "region": "UK",
                             "status": "Broadcaster listed; specific channel unknown",
                             "source": SKY_SCHEDULE})
            count += 1
    return count


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BostonSportsHub/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def main():
    data = json.loads(OUT.read_text(encoding="utf-8"))
    games = data.setdefault("games", {})
    now = dt.datetime.now(dt.timezone.utc)
    season = now.year + (1 if now.month >= 8 else 0)
    updated = 0
    successes = 0
    events_by_key = {}
    for year in (season, season - 1):
        for season_type in (2, 3):
            try:
                events = get_json(f"{BASE}?season={year}&seasontype={season_type}").get("events", [])
                successes += 1
            except Exception as exc:
                print(f"ESPN {year}/{season_type}: {exc}")
                continue
            for event in events:
                try:
                    date = dt.datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
                    if not dt.timedelta(days=-8) <= date - now <= dt.timedelta(days=75):
                        continue
                    competitors = event["competitions"][0]["competitors"]
                    if not any(str(c.get("team", {}).get("id")) == "2" for c in competitors):
                        continue
                    other = next(c for c in competitors if str(c.get("team", {}).get("id")) != "2")
                    opponent = other["team"]["displayName"]
                    # Use the New York date, including daylight-saving changes.
                    key = f"{date.astimezone(ZoneInfo('America/New_York')).date()}|{opponent}"
                    competition = event["competitions"][0]
                    home = next(c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home")
                    away = next(c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away")
                    events_by_key[key] = (home, away)
                    names = set()
                    for item in competition.get("broadcasts", []) + event.get("broadcasts", []):
                        for name in item.get("names", []) + ([item["name"]] if item.get("name") else []):
                            if isinstance(name, str) and name.strip():
                                names.add(name.strip())
                    names = {n for n in names if not any(term in n.casefold() for term in ("highlights", "recap", "nba tv highlights"))}
                    if not names:
                        continue
                    record = games.setdefault(key, {"channels": []})
                    channels = record.setdefault("channels", [])
                    for name in sorted(names):
                        if any(c.get("name", "").casefold() == name.casefold() for c in channels):
                            continue
                        channels.append({"name": name, "region": COUNTRY,
                                         "status": "Listed by ESPN", "source": "https://www.espn.com/nba/schedule"})
                        updated += 1
                except (KeyError, TypeError, ValueError, StopIteration) as exc:
                    print("Skipped malformed event:", exc)
    if not successes:
        raise SystemExit("No ESPN feeds available; existing listings preserved")
    try:
        print("New Sky UK game listings:", refresh_sky_schedule(games, events_by_key))
    except Exception as exc:
        print("Sky schedule unavailable; existing data preserved:", exc)
    data["lastAutoRefresh"] = now.isoformat()
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added {updated} game-specific channels; retained manually verified international and UK channels")

if __name__ == "__main__":
    main()
