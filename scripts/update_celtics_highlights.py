#!/usr/bin/env python3
"""Find UK-accessible Celtics game highlights across YouTube.

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
CELTICS_CHANNEL = "UCMfT9dr6xC_RIWoA9hI0meQ"
NBA_CHANNEL = "UCWJ2lWNubArHWmf3FIHbfcQ"
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


def category(title, duration):
    t = title.lower()
    if duration < 180 or duration > 1800:
        return None
    if "extended" in t:
        return "extended"
    if "full game highlights" in t or "full highlights" in t:
        return "full"
    return "standard"


def youtube_search(when, opponent, channel_id):
    # Search globally, not by channel. Restrict publication to shortly after the
    # game so an older meeting between the same teams is unlikely to match.
    after = when
    before = when + dt.timedelta(days=3)
    params = urllib.parse.urlencode({
        "part": "snippet", "type": "video",
        "maxResults": 50, "order": "date",
        "q": f"Celtics {opponent} full game highlights",
        "publishedAfter": after.isoformat().replace("+00:00", "Z"),
        "publishedBefore": before.isoformat().replace("+00:00", "Z"),
        "key": API_KEY,
    })
    data = get_json("https://www.googleapis.com/youtube/v3/search?" + params)
    results = data.get("items", [])
    candidates = []
    for item in results:
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        video_id = item.get("id", {}).get("videoId", "")
        # Require both teams in title; descriptions alone are too unreliable.
        if not (re.search(r"\bceltics\b", title, re.I)
                and re.search(r"\b" + re.escape(opponent) + r"\b", title, re.I)
                and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)):
            continue
        try:
            published = dt.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if not after <= published <= before:
            continue
        candidates.append((video_id, title, description, published))
    print(f"Official channel {channel_id} vs {opponent}: {len(results)} recent uploads, {len(candidates)} team/date candidates")
    if not candidates:
        return []

    details = get_json("https://www.googleapis.com/youtube/v3/videos?" +
        urllib.parse.urlencode({
            "part": "status,contentDetails,snippet",
            "id": ",".join(x[0] for x in candidates),
            "key": API_KEY,
        }))
    valid = {}
    for item in details.get("items", []):
        status = item.get("status", {})
        content = item.get("contentDetails", {})
        region = content.get("regionRestriction", {})
        if (status.get("privacyStatus") != "public"
                or status.get("uploadStatus") not in (None, "processed")
                or "GB" in region.get("blocked", [])
                or ("allowed" in region and "GB" not in region["allowed"])):
            continue
        duration = content.get("duration", "")
        match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match:
            continue
        seconds = sum(int(n or 0) * scale for n, scale in zip(match.groups(), (3600, 60, 1)))
        kind = category(item.get("snippet", {}).get("title", ""), seconds)
        if kind is None:
            continue
        valid[item["id"]] = (seconds, kind, channel_id)
    print(f"  {len(valid)} UK-accessible official videos between 3 and 30 minutes")

    matches = []
    for video_id, title, description, published in candidates:
        if video_id not in valid:
            continue
        seconds, kind, channel_id = valid[video_id]
        # Longer footage and explicit game highlights outrank player-centric clips.
        explicit = bool(re.search(r"game highlights|extended highlights|full highlights|game recap|highlights.*(?:celtics|vs)", title, re.I))
        player_focus = bool(re.search(r"\b(points|pts|triple.double|career.high|highlights of|goes off|explodes)\b", title, re.I))
        score = 100 + (25 if channel_id == NBA_CHANNEL else 15)
        score += min(seconds, 900) / 30
        if player_focus:
            score -= 45
        matches.append({
            "youtubeId": video_id,
            "source": "NBA on YouTube" if channel_id == NBA_CHANNEL else ("Celtics on YouTube" if channel_id == CELTICS_CHANNEL else "YouTube highlights"),
            "category": kind,
            "durationSeconds": seconds,
            "providerUrl": f"https://www.youtube.com/watch?v={video_id}",
            "_published": published,
            "_score": score,
        })
    matches.sort(key=lambda v: v["_score"], reverse=True)
    print(f"  Selected {min(len(matches), 4)} of {len(matches)} suitable videos")
    return matches[:20]


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

    # Keep manually curated entries; retain verified official videos on lookup gaps.
    games = {}
    for game_id, record in old_games.items():
        if isinstance(record, dict):
            manual = [v for v in record.get("videos", [])
                      if isinstance(v, dict) and v.get("source") not in ("NBA on YouTube", "YouTube highlights")]
            if manual:
                games[game_id] = {"videos": manual}

    candidates = {}
    failed = False
    for game_id, (when, opponent) in events.items():
        try:
            candidates[game_id] = youtube_search(when, opponent, NBA_CHANNEL)
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
            selected.append({k: v for k, v in video.items() if not k.startswith("_")})
        if selected:
            games[game_id] = {"videos": selected}
            print(f"{game_id} vs {events[game_id][1]}: {len(selected)} validated YouTube videos")
    if not games:
        print("No highlights found; preserving previous file rather than publishing an empty feed.")
        return
    print(f"Saved highlights for {len(games)} games; ESPN remains the website fallback.")
    OUT.write_text(json.dumps({"games": games}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
