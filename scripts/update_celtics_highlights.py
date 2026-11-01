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
    season = today.year + 1 if today.month >= 8 else today.year
    # ESPN identifies the 2026-27 NBA season as season=2027.
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
    print(f"Found {len(events)} eligible Celtics games in ESPN season(s) {season} and {season - 1}.")
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
    # Search results alone do not establish that a video is public or playable.
    params = urllib.parse.urlencode({
        "part": "snippet", "channelId": NBA_CHANNEL, "type": "video",
        "videoEmbeddable": "true", "maxResults": 25,
        "q": f"Boston Celtics {opponent} game highlights",
        "publishedAfter": (when + dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "publishedBefore": (when + dt.timedelta(days=2)).isoformat().replace("+00:00", "Z"),
        "key": API_KEY,
    })
    data = get_json("https://www.googleapis.com/youtube/v3/search?" + params)
    candidates = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        video_id = item.get("id", {}).get("videoId", "")
        if not (re.search(r"\bceltics\b", title, re.I)
                and re.search(r"\b" + re.escape(opponent) + r"\b", title, re.I)
                and category(title)
                and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)):
            continue
        try:
            published = dt.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if when + dt.timedelta(hours=1) <= published <= when + dt.timedelta(days=2):
            candidates.append((video_id, title, published))
    if not candidates:
        return []

    # videos.list exposes current visibility, embedding and geographic restrictions.
    details = get_json("https://www.googleapis.com/youtube/v3/videos?" +
        urllib.parse.urlencode({
            "part": "status,contentDetails,snippet",
            "id": ",".join(item[0] for item in candidates),
            "key": API_KEY,
        }))
    valid = {}
    for item in details.get("items", []):
        status = item.get("status", {})
        restriction = item.get("contentDetails", {}).get("regionRestriction", {})
        if (status.get("privacyStatus") != "public"
                or status.get("embeddable") is not True
                or status.get("uploadStatus") not in (None, "processed")
                or "GB" in restriction.get("blocked", [])
                or ("allowed" in restriction and "GB" not in restriction["allowed"])):
            continue
        valid[item["id"]] = item

    matches = []
    for video_id, title, published in candidates:
        if video_id not in valid:
            continue
        matches.append({
            "youtubeId": video_id, "source": "NBA on YouTube",
            "category": category(title),
            "providerUrl": f"https://www.youtube.com/watch?v={video_id}",
            "_published": published,
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
    old_games = existing.get("games", {})
    if not isinstance(old_games, dict):
        old_games = {}
    events = completed_games()
    if not events:
        print("No eligible completed Celtics games found; nothing to update.")
        return

    # Keep manually curated non-NBA entries, but revalidate automated entries.
    games = {}
    for game_id, record in old_games.items():
        if isinstance(record, dict):
            manual = [v for v in record.get("videos", [])
                      if isinstance(v, dict) and v.get("source") != "NBA on YouTube"]
            if manual:
                games[game_id] = {"videos": manual}

    candidates = {}
    failed = False
    for game_id, (when, opponent) in events.items():
        try:
            candidates[game_id] = youtube_search(when, opponent)
        except Exception as exc:
            print(f"YouTube lookup failed for {game_id}: {exc}")
            failed = True
    if failed:
        raise SystemExit("Some YouTube lookups failed; preserving previous data for retry.")

    # Assign each YouTube video to just one game, nearest its publication time.
    owners = {}
    for game_id, videos in candidates.items():
        when = events[game_id][0]
        for video in videos:
            video_id = video["youtubeId"]
            distance = abs((video["_published"] - when).total_seconds())
            if video_id not in owners or distance < owners[video_id][0]:
                owners[video_id] = (distance, game_id)

    for game_id, videos in candidates.items():
        selected = []
        for video in videos:
            if owners[video["youtubeId"]][1] != game_id:
                continue
            selected.append({k: v for k, v in video.items() if k != "_published"})
        if selected:
            games.setdefault(game_id, {"videos": []})["videos"].extend(selected)
            print(f"{game_id} vs {events[game_id][1]}: {len(selected)} validated official NBA videos")
    print(f"Saved highlights for {len(games)} games; ESPN remains the website fallback.")
    OUT.write_text(json.dumps({"games": games}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
