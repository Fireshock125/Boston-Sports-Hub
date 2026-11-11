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
import email.utils
import xml.etree.ElementTree as ET
import html

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "celtics-highlights.json"
API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
CELTICS_CHANNEL = "UCMfT9dr6xC_RIWoA9hI0meQ"
NBA_CHANNEL = "UCWJ2lWNubArHWmf3FIHbfcQ"
OFFICIAL_CHANNELS = {NBA_CHANNEL: ("NBA Official", 300), CELTICS_CHANNEL: ("Boston Celtics Official", 260)}


def nbc_channel_id():
    """Resolve NBC Sports Boston by its official YouTube handle, not a guessed ID."""
    url = "https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode({
        "part": "id", "forHandle": "@nbcsboston", "key": API_KEY,
    })
    items = get_json(url).get("items", [])
    return items[0]["id"] if items else None

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


def category(title, duration, description=""):
    """Classify discovered videos only after search; keep discussion out of highlights."""
    t = html.unescape(title).lower()
    d = html.unescape(description).lower()
    if duration <= 0:
        return None
    # A title can contain 'highlights' while the video is a reaction or podcast.
    if re.search(r"reaction|reacts? to|post[ -]?game (?:show|reaction|press)|analysis|breakdown|interview|press conference|podcast|talk show|discussion|review|preview|watch.?along|watch party|live stream|livestream|play.?by.?play|commentary|film study|film room|mic.?d up|player highlights|best plays|top plays|shorts?", t):
        return None
    if re.search(r"reaction|podcast|watch.?along|watch party|live stream|livestream|postgame show", d) and not re.search(r"game highlights|full game highlights|extended highlights", t):
        return None
    if not re.search(r"highlights|game recap|full game", t):
        return None
    # Full game replays are not highlights.
    if duration > 1800:
        return None
    if "extended" in t:
        return "extended"
    if "full game highlights" in t or "full highlights" in t:
        return "full"
    return "standard"


def youtube_search(when, opponent, channel_id=None):
    """Discover broadly, then validate and filter, then rank elsewhere."""
    after = when
    before = when + dt.timedelta(days=4)
    queries = [f"Celtics {opponent} highlights {when.strftime('%B %d %Y')}"]
    discovered = {}
    for query in queries:
        params_dict = {
            "part": "snippet", "type": "video", "videoEmbeddable": "true",
            "maxResults": 50, "order": "relevance", "q": query,
            "publishedAfter": after.isoformat().replace("+00:00", "Z"),
            "publishedBefore": before.isoformat().replace("+00:00", "Z"),
            "key": API_KEY,
        }
        if channel_id:
            params_dict["channelId"] = channel_id
        data = get_json("https://www.googleapis.com/youtube/v3/search?" +
                        urllib.parse.urlencode(params_dict))
        for item in data.get("items", []):
            video_id = item.get("id", {}).get("videoId", "")
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                discovered[video_id] = item.get("snippet", {})
    print(f"Search vs {opponent}: discovered {len(discovered)} videos before filtering")
    if not discovered:
        return []

    # YouTube's videos endpoint accepts up to 50 IDs per request.
    details = []
    ids = list(discovered)
    for offset in range(0, len(ids), 50):
        data = get_json("https://www.googleapis.com/youtube/v3/videos?" +
            urllib.parse.urlencode({
                "part": "status,contentDetails,snippet",
                "id": ",".join(ids[offset:offset + 50]),
                "key": API_KEY,
            }))
        details.extend(data.get("items", []))

    matches = []
    for item in details:
        video_id = item.get("id", "")
        snippet = item.get("snippet", {})
        title = html.unescape(snippet.get("title", ""))
        description = snippet.get("description", "")
        actual_channel_id = snippet.get("channelId", "")
        # Stage 2: validate that the video belongs to this matchup and works in GB.
        if not (re.search(r"\bceltics\b", title, re.I)
                and re.search(r"\b" + re.escape(opponent) + r"\b", title, re.I)):
            continue
        try:
            published = dt.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if not after <= published <= before:
            continue
        status = item.get("status", {})
        content = item.get("contentDetails", {})
        region = content.get("regionRestriction", {})
        if (status.get("privacyStatus") != "public"
                or status.get("embeddable") is not True
                or status.get("uploadStatus") not in (None, "processed")
                or "GB" in region.get("blocked", [])
                or ("allowed" in region and "GB" not in region["allowed"])):
            continue
        match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
                             content.get("duration", ""))
        if not match:
            continue
        seconds = sum(int(n or 0) * scale for n, scale in zip(match.groups(), (3600, 60, 1)))
        # Stage 2: reject reactions, interviews and other non-highlight formats.
        kind = category(title, seconds, description)
        if kind is None:
            continue
        if channel_id and actual_channel_id != channel_id:
            continue
        source = OFFICIAL_CHANNELS.get(actual_channel_id, ("YouTube highlights", 0))[0]
        matches.append({
            "youtubeId": video_id,
            "source": source,
            "category": kind,
            "durationSeconds": seconds,
            "providerUrl": f"https://www.youtube.com/watch?v={video_id}",
            "_published": published,
            "_score": (1 if actual_channel_id in OFFICIAL_CHANNELS else 0, seconds),
        })
    print(f"  {len(matches)} suitable highlights after filtering")
    # Stage 3: rank happens in main(), after all channel and general searches merge.
    return matches


def youtube_analysis(when, opponent, channel_id):
    """Find actual NBC Sports Boston postgame analysis videos for this matchup."""
    after = when
    before = when + dt.timedelta(days=3)
    params = urllib.parse.urlencode({
        "part": "snippet", "type": "video", "videoEmbeddable": "true",
        "maxResults": 50, "order": "relevance", "channelId": channel_id,
        "q": f"Celtics {opponent} postgame",
        "publishedAfter": after.isoformat().replace("+00:00", "Z"),
        "publishedBefore": before.isoformat().replace("+00:00", "Z"),
        "key": API_KEY,
    })
    results = get_json("https://www.googleapis.com/youtube/v3/search?" + params).get("items", [])
    candidates = []
    for entry in results:
        snippet = entry.get("snippet", {})
        title = snippet.get("title", "")
        video_id = entry.get("id", {}).get("videoId", "")
        if not (re.search(r"\bceltics\b", title, re.I)
                and re.search(re.escape(opponent.split()[-1]), title, re.I)
                and re.search(r"post.?game|analysis|breakdown|reaction|takeaways|recap", title, re.I)
                and not re.search(r"preview|pregame|live stream|watch party|shorts", title, re.I)
                and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)):
            continue
        candidates.append((video_id, title))
    if not candidates:
        return []
    details = get_json("https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({
        "part": "status,contentDetails,snippet",
        "id": ",".join(v[0] for v in candidates), "key": API_KEY,
    }))
    valid = {}
    for item in details.get("items", []):
        status = item.get("status", {})
        content = item.get("contentDetails", {})
        region = content.get("regionRestriction", {})
        if (status.get("privacyStatus") != "public"
                or status.get("embeddable") is not True
                or "GB" in region.get("blocked", [])
                or ("allowed" in region and "GB" not in region["allowed"])
                or item.get("snippet", {}).get("channelId") != channel_id):
            continue
        duration = content.get("duration", "")
        match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match:
            continue
        seconds = sum(int(n or 0) * scale for n, scale in zip(match.groups(), (3600, 60, 1)))
        if 180 <= seconds <= 5400:
            valid[item["id"]] = seconds
    return [{
        "youtubeId": video_id,
        "source": "NBC Sports Boston",
        "category": "analysis",
        "durationSeconds": valid[video_id],
        "providerUrl": f"https://www.youtube.com/watch?v={video_id}",
    } for video_id, title in candidates if video_id in valid][:10]



def clns_analysis(when, opponent):
    """Find matchup-specific CLNS postgame articles on the publisher's website."""
    matches = []
    # WordPress search covers more posts than the site's short RSS front page.
    for query in (f"Celtics {opponent}", f"Garden Report {opponent}"):
        url = "https://www.clnsmedia.com/wp-json/wp/v2/search?" + urllib.parse.urlencode({
            "search": query, "per_page": 20, "type": "post"
        })
        try:
            results = get_json(url)
        except Exception as exc:
            print(f"CLNS website search unavailable: {exc}")
            continue
        for item in (results[:12] if isinstance(results, list) else []):
            title = html.unescape(re.sub(r"<[^>]*>", "", item.get("title", "")))
            link = item.get("url", "")
            if not (link.startswith("https://www.clnsmedia.com/")
                    and re.search(re.escape(opponent.split()[-1]), title, re.I)
                    and re.search(r"celtics|garden report|postgame", title, re.I)):
                continue
            # WordPress search API doesn't return a reliable publication date.
            # Check the public article's published metadata via the posts API.
            post_id = item.get("id")
            if not isinstance(post_id, int):
                continue
            try:
                post = get_json(f"https://www.clnsmedia.com/wp-json/wp/v2/posts/{post_id}")
                published = dt.datetime.fromisoformat(post["date_gmt"] + "+00:00")
            except Exception:
                continue
            if not when <= published <= when + dt.timedelta(days=3):
                continue
            if not re.search(r"postgame|garden report|reaction|breakdown|analysis|recap|win|lose|beat|fall|escape|dominate|struggle", title, re.I):
                continue
            matches.append({"source": "CLNS Media", "category": "analysis",
                            "providerUrl": link, "title": title, "access": "free_page"})
        if matches:
            break
    return list({v["providerUrl"]: v for v in matches}.values())[:5]


def video_rank(video, analysis=False):
    """Professional coverage first; prefer concise complete highlights over long videos."""
    source = video.get("source", "")
    duration = int(video.get("durationSeconds") or 0)
    professional = {"NBA Official": 5, "NBC Sports Boston": 4,
                    "Boston Celtics Official": 4, "CLNS Media": 3}.get(source, 1)
    if analysis:
        return (professional, 1 if video.get("youtubeId") else 0, -abs(duration - 1200))
    return (1 if 480 <= duration <= 900 else 0,
            professional, 1 if 480 <= duration <= 1200 else 0,
            -abs(duration - 660))

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
                      if isinstance(v, dict) and v.get("source") not in ("NBA on YouTube", "YouTube highlights", "NBA Official", "Boston Celtics Official", "NBC Sports Boston")]
            if manual:
                games[game_id] = {"videos": manual}

    # One broad search per game: discover, filter, then rank.
    # Avoid multiple expensive YouTube search calls per game (HTTP 429).
    candidates = {}
    analysis_candidates = {}
    website_analysis = {}
    failed = False
    for game_id, (when, opponent) in events.items():
        try:
            found = youtube_search(when, opponent)
            candidates[game_id] = sorted(found, key=video_rank, reverse=True)[:4]
            print(f"{game_id}: {len(found)} filtered highlights, {len(candidates[game_id])} ranked choices")
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
    # Keep analysis independent from highlights, including games with no highlights.
    for game_id, analysis in analysis_candidates.items():
        combined_analysis = analysis + website_analysis.get(game_id, [])
        combined_analysis.sort(key=lambda v: video_rank(v, analysis=True), reverse=True)
        if combined_analysis:
            games.setdefault(game_id, {})["analysis"] = combined_analysis
        elif isinstance(old_games.get(game_id), dict) and old_games[game_id].get("analysis"):
            games.setdefault(game_id, {})["analysis"] = old_games[game_id]["analysis"]
    # Preserve previous videos when a fresh search misses a game.
    for game_id, record in old_games.items():
        if game_id not in games and isinstance(record, dict) and record.get("videos"):
            # Do not restore old, unverified highlights when discovery finds no match.
            if record.get("analysis"):
                games[game_id] = {"analysis": record["analysis"]}

    if not games:
        print("No highlights found; preserving previous file rather than publishing an empty feed.")
        return
    print(f"Saved highlights and analysis for {len(games)} games; no ESPN video fallback.")
    OUT.write_text(json.dumps({"games": games}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
