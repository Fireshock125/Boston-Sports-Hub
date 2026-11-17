"""Game-specific TV source integrations. Only add channels when fixture and channel share a listing."""
import re
import urllib.request
from html.parser import HTMLParser

class TextLines(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
    def handle_data(self, value):
        value = " ".join(value.split())
        if value:
            self.lines.append(value)

def page_lines(url):
    request = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 (compatible; BostonSportsHub/1.0)"})
    with urllib.request.urlopen(request, timeout=25) as response:
        html = response.read().decode("utf-8","replace")
    parser = TextLines()
    parser.feed(html)
    return parser.lines

def add_channel(games, key, name, country, source):
    channels = games.setdefault(key, {"channels":[]}).setdefault("channels", [])
    if any(c.get("name","").casefold() == name.casefold() and c.get("region","").casefold() == country.casefold() for c in channels):
        return 0
    channels.append({"name":name,"region":country,"status":"Game-specific source listing","source":source})
    return 1

SKY_NFL = "https://www.skysports.com/nfl/news/13582747/nfl-2026-season-live-on-sky-sports-fixtures-kick-off-times-tv-channel-for-games-this-week-and-weekend"
def sky_nfl_games(games, events):
    """Require exact Patriots fixture plus LIVE channel within same listing."""
    lines = page_lines(SKY_NFL)
    added = 0
    for key, (home, away) in events.items():
        if "New England Patriots" not in (home, away):
            continue
        other = away if home == "New England Patriots" else home
        # Sky uses both full names and short team names in its weekly listings.
        matchup = re.compile(r"\b(?:New England )?Patriots\s*(?:@|at|v|vs|versus)\s*"+re.escape(other)+r"\b|\b"+re.escape(other)+r"\s*(?:@|at|v|vs|versus)\s*(?:New England )?Patriots\b",re.I)
        for i, line in enumerate(lines):
            if not matchup.search(line):
                continue
            context = " ".join(lines[i:i+4])
            if not re.search(r"\bLIVE\b",context,re.I):
                continue
            for channel in ("Sky Sports NFL","Sky Sports Main Event","Sky Sports Action","Sky Sports Mix"):
                if re.search(re.escape(channel),context,re.I):
                    added += add_channel(games,key,channel,"UK",SKY_NFL)
            if not any(c.get("region")=="UK" and c.get("source")==SKY_NFL for c in games.get(key,{}).get("channels",[])):
                added += add_channel(games,key,"Sky Sports","UK",SKY_NFL)
    return added
