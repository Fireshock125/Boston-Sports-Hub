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
                if not (dt.timedelta(hours=3) < today - when < dt.timedelta(days=14)):
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
    if re.search(r"preview|reaction|interview|analysis|press conference|podcast|shorts|live stream|watch party|top plays", t):
        return None
    if "extended" in t:
        return "extended"
    if "full game highlights" in t or "full highlights" in t:
        return "full"
    return "standard"


def youtube_search(when, opponent):
    # Search globally, not by channel. Restrict publication to shortly after the
    # game so an older meeting between the same teams is unlikely to match.
    after = when + dt.timedelta(hours=1)
    before = when + dt.timedelta(days=2)
    params = urllib.parse.urlencode({
        "part": "snippet", "type": "video", "videoEmbeddable": "true",
        "maxResults": 50, "order": "relevance",
        "q": f"{"Boston Celtics"} {opponent} game highlights {when.strftime('%B %d %Y')}",
        "publishedAfter": after.isoformat().replace("+00:00", "Z"),
        "publishedBefore": before.isoformat().replace("+00:00", "Z"),
        "key": API_KEY,
    })
    print(f"API query vs {opponent}: {dict(urllib.parse.parse_qsl(params)).get('q')}")
    data = get_json("https://www.googleapis.com/youtube/v3/search?" + params)
    results = data.get("items", [])
    print(f"API returned {len(results)} results for {opponent}; totalResults estimate: {data.get('pageInfo', {}).get('totalResults', 'unknown')}")
    for index, entry in enumerate(results, 1):
        snippet = entry.get("snippet", {})
        print(f"  API #{index}: {snippet.get('title', '')} | {entry.get('id', {}).get('videoId', '')} | {snippet.get('publishedAt', '')}")
    candidates = []
    for item in results:
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        video_id = item.get("id", {}).get("videoId", "")
        # Require both teams in title; descriptions alone are too unreliable.
        if not (re.search(re.escape("Celtics"), title, re.I)
                and (re.search(re.escape(opponent), title, re.I) or re.search(re.escape(opponent.split()[-1]), title, re.I))
                and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)):
            print(f"  REJECT matchup/ID: {title}")
            continue
        if re.search(r"preview|reaction|interview|podcast|shorts|live stream|watch party", title, re.I):
            print(f"  REJECT title exclusion: {title}")
            continue
        try:
            published = dt.datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            print(f"  REJECT invalid published date: {title}")
            continue
        if not after <= published <= before:
            print(f"  REJECT publication window: {title}")
            continue
        candidates.append((video_id, title, description, published))
    print(f"Search vs {opponent}: {len(results)} results, {len(candidates)} team/date candidates")
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
                or status.get("embeddable") is not True
                or status.get("uploadStatus") not in (None, "processed")
                or "GB" in region.get("blocked", [])
                or ("allowed" in region and "GB" not in region["allowed"])):
            print(f"  REJECT availability: {item.get('id')} | {item.get('snippet', {}).get('title', '')}")
            continue
        duration = content.get("duration", "")
        match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match:
            print(f"  REJECT duration metadata: {item.get('id')}")
            continue
        seconds = sum(int(n or 0) * scale for n, scale in zip(match.groups(), (3600, 60, 1)))
        kind = category(item.get("snippet", {}).get("title", ""), seconds)
        if kind is None:
            print(f"  REJECT category: {item.get('id')} | {item.get('snippet', {}).get('title', '')}")
            continue
        valid[item["id"]] = (seconds, kind, item.get("snippet", {}).get("channelId", ""))
    print(f"  {len(valid)} UK-accessible, embeddable videos (no duration limit)")

    matches = []
    for video_id, title, description, published in candidates:
        if video_id not in valid:
            continue
        seconds, kind, channel_id = valid[video_id]
        # Longer footage and explicit game highlights outrank player-centric clips.
        explicit = bool(re.search(r"game highlights|extended highlights|full highlights|game recap", title, re.I))
        player_focus = bool(re.search(r"\b(points|pts|triple.double|career.high|highlights of|goes off|explodes)\b", title, re.I))
        official = channel_id in (CELTICS_CHANNEL, NBA_CHANNEL)
        score = (100 if explicit else 0) + (25 if official else 0)
        score += min(seconds, 900) / 30
        if player_focus:
            score -= 45
        matches.append({
            "youtubeId": video_id,
            "source": "YouTube highlights",
            "category": kind,
            "durationSeconds": seconds,
            "providerUrl": f"https://www.youtube.com/watch?v={video_id}",
            "_published": published,
            "_score": score,
        })
    matches.sort(key=lambda v: v["_score"], reverse=True)
    for index, video in enumerate(matches, 1):
        print(f"  RANK #{index}: {video['youtubeId']} | score={video['_score']:.1f} | {video['durationSeconds']}s")
    print(f"  Selected {min(len(matches), 4)} of {len(matches)} suitable videos")
    return matches[:4]


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
    failed_games = set()
    for game_id, (when, opponent) in events.items():
        try:
            found = youtube_search(when, opponent)
            candidates[game_id] = found
            print(f"{game_id}: {len(candidates[game_id])} Bruins-style ranked highlight choices")
        except Exception as exc:
            print(f"YouTube lookup failed for {game_id}: {exc}")
            failed_games.add(game_id)
    if failed_games:
        print(f"Temporary YouTube errors for {len(failed_games)} game(s); retaining their previous entries.")

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
    # A temporary 429 is not evidence that earlier videos disappeared.
    # Preserve existing game records ONLY for failed lookups; successful
    # searches use the newly filtered and ranked results.
    for game_id in failed_games:
        record = old_games.get(game_id)
        if isinstance(record, dict):
            games[game_id] = dict(record)
    # Keep previous analysis even when highlights are not found this run.
    for game_id, record in old_games.items():
        if not isinstance(record, dict):
            continue
        if record.get("analysis"):
            games.setdefault(game_id, {}).setdefault("analysis", record["analysis"])

    if not games:
        print("No highlights found; preserving previous file rather than publishing an empty feed.")
        return
    print(f"Saved highlights and analysis for {len(games)} games; no ESPN video fallback.")
    OUT.write_text(json.dumps({"games": games}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
