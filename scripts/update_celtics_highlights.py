#!/usr/bin/env python3
"""Match official NBA YouTube highlights to completed Celtics ESPN games.

Requires YOUTUBE_API_KEY in GitHub Actions secrets. No credentials enter the website.
"""
import datetime as dt
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "celtics-highlights.json"
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
NBA_CHANNEL = "UCWJ2lWNubArHWmf3FIHbfcQ"  # Official NBA channel
TEAM_NAMES = {
    "ATL": "Hawks", "BKN": "Nets", "BOS": "Celtics", "CHA": "Hornets",
    "CHI": "Bulls", "CLE": "Cavaliers", "DAL": "Mavericks", "DEN": "Nuggets",
    "DET": "Pistons", "GS": "Warriors", "GSW": "Warriors", "HOU": "Rockets",
    "IND": "Pacers", "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies",
    "MIA": "Heat", "MIL": "Bucks", "MIN": "Timberwolves", "NO": "Pelicans",
    "NOP": "Pelicans", "NY": "Knicks", "NYK": "Knicks", "OKC": "Thunder",
    "ORL": "Magic", "PHI": "76ers", "PHX": "Suns", "PHO": "Suns",
    "POR": "Trail Blazers", "SAC": "Kings", "SA": "Spurs",
    "SAS": "Spurs", "TOR": "Raptors", "UTA": "Jazz", "UTAH": "Jazz",
    "WAS": "Wizards",
}


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "BostonSportsHub/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def completed_games():
    today = dt.datetime.now(dt.timezone.utc)
    season = today.year if today.month >= 8 else today.year - 1
    events = {}
    for year in (season, season - 1):
        for season_type in (2, 3):
            url = ("https://site.api.espn.com/apis/site/v2/sports/"
                   f"basketball/nba/teams/2/schedule?season={year}&seasontype={season_type}")
            try:
                data = get_json(url)
            except Exception as exc:
                print("ESPN unavailable:", exc)
                continue
            for event in data.get("events", []):
                try:
                    when = dt.datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
                except (ValueError, KeyError):
                    continue
                if not (dt.timedelta(hours=3) < today - when < dt.timedelta(days=12)):
                    continue
                competition = (event.get("competitions") or [{}])[0]
                competitors = competition.get("competitors") or []
                if len(competitors) != 2:
                    continue
                opponent = next((c for c in competitors
                    if str(c.get("team", {}).get("id")) != "2"), None)
                if not opponent:
                    continue
                name = TEAM_NAMES.get(opponent.get("team", {}).get("abbreviation", ""))
                if not name:
                    continue
                events[str(event["id"])] = (when, name)
    return events


def category(title):
    t = title.lower()
    if not ("highlight" in t or "recap" in t):
        return None
    if re.search(r"preview|reaction|interview|analysis|player highlights|top plays", t):
        return None
    if "extended" in t:
        return "extended"
    if "full game" in t or "full highlights" in t:
        return "full"
    return "standard"


def youtube_search(when, opponent):
    params = urllib.parse.urlencode({
        "part": "snippet", "channelId": NBA_CHANNEL, "type": "video",
        "videoEmbeddable": "true", "maxResults": 12,
        "q": f"Boston Celtics {opponent} game highlights",
        "publishedAfter": (when - dt.timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
        "publishedBefore": (when + dt.timedelta(days=3)).isoformat().replace("+00:00", "Z"),
        "key": API_KEY,
    })
    data = get_json("https://www.googleapis.com/youtube/v3/search?" + params)
    matches = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        if not (re.search(r"\bceltics\b", title, re.I)
                and re.search(r"\b" + re.escape(opponent) + r"\b", title, re.I)):
            continue
        kind = category(title)
        video_id = item.get("id", {}).get("videoId", "")
        if kind and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            matches.append({
                "youtubeId": video_id, "source": "NBA on YouTube",
                "category": kind,
                "providerUrl": f"https://www.youtube.com/watch?v={video_id}",
            })
    return matches[:4]


def main():
    if not API_KEY:
        raise SystemExit("Missing YOUTUBE_API_KEY secret; no changes made.")
    existing = {"games": {}}
    if OUT.exists():
        try:
            existing = json.loads(OUT.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    games = existing.get("games", {})
    if not isinstance(games, dict):
        games = {}
    events = completed_games()
    if not events:
        print("No eligible completed Celtics games found; nothing to update.")
        return
    for game_id, (when, opponent) in sorted(events.items(), key=lambda x: x[1][0], reverse=True):
        try:
            videos = youtube_search(when, opponent)
        except Exception as exc:
            print(f"YouTube lookup failed for {game_id}: {exc}")
            continue
        if videos:
            games[game_id] = {"videos": videos}
            print(f"{game_id} vs {opponent}: {len(videos)} official NBA videos")
    # Keep recent games, and preserve manually curated entries if any.
    OUT.write_text(json.dumps({"games": games}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
