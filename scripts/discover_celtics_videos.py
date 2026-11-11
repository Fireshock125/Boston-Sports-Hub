#!/usr/bin/env python3
"""Independent Celtics video DISCOVERY audit. Does not change the live site.
Search widely; report candidates, not claims of free or UK playback.
"""
import datetime as dt
import json
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from update_celtics_highlights import API_KEY, ROOT, completed_games, get_json

OUTPUT = ROOT / "celtics-discovery-report.json"
SITES = ("nbcsports.com", "sports.yahoo.com", "nbcsportsboston.com", "clnsmedia.com", "sportsnet.ca")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BostonSportsHub/1.0)"}


def youtube_candidates(when, opponent):
    if not API_KEY:
        return [], "YouTube API key missing"
    params = urllib.parse.urlencode({
        "part": "snippet", "type": "video", "maxResults": 50,
        "q": f"Boston Celtics {opponent} {when.strftime('%B %d %Y')}",
        "publishedAfter": when.isoformat().replace("+00:00", "Z"),
        "publishedBefore": (when + dt.timedelta(days=4)).isoformat().replace("+00:00", "Z"),
        "key": API_KEY,
    })
    try:
        entries = get_json("https://www.googleapis.com/youtube/v3/search?" + params).get("items", [])
        return [{
            "source": "YouTube", "title": x.get("snippet", {}).get("title", ""),
            "url": "https://www.youtube.com/watch?v=" + x["id"]["videoId"],
            "published": x.get("snippet", {}).get("publishedAt", ""),
            "status": "candidate_unverified",
        } for x in entries if x.get("id", {}).get("videoId")], None
    except Exception as exc:
        return [], str(exc)


def website_candidates(when, opponent):
    """Discover publisher pages independently of search-engine RSS indexing."""
    items, errors = [], []
    # CLNS exposes a searchable WordPress content index. This previously found
    # seven Celtics analysis articles in the main highlights workflow.
    for query in (f"Celtics {opponent}", f"Garden Report {opponent}"):
        url = "https://www.clnsmedia.com/wp-json/wp/v2/search?" + urllib.parse.urlencode({
            "search": query, "per_page": 50, "type": "post"
        })
        try:
            results = get_json(url)
            for item in results if isinstance(results, list) else []:
                link = item.get("url", "")
                title = re.sub(r"<[^>]+>", "", item.get("title", ""))
                if not link.startswith("https://www.clnsmedia.com/"):
                    continue
                if not re.search(re.escape(opponent.split()[-1]), title, re.I):
                    continue
                items.append({"source": "CLNS Media", "title": title,
                              "url": link, "status": "candidate_unverified",
                              "discovery": "publisher_search"})
        except Exception as exc:
            errors.append(f"CLNS publisher search: {exc}")

    # General web search is supplemental, not the only route to publisher pages.
    # Do not require the search engine to return exactly a publisher's hostname.
    for domain in SITES:
        query = f'site:{domain} Boston Celtics {opponent} video highlights'
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=18) as response:
                root = ET.fromstring(response.read())
            for item in root.findall(".//channel/item"):
                link = item.findtext("link") or ""
                title = item.findtext("title") or ""
                host = urllib.parse.urlparse(link).hostname or ""
                if not link.startswith("https://") or not (host == domain or host.endswith("." + domain)):
                    continue
                items.append({"source": domain, "title": title, "url": link,
                              "status": "candidate_unverified", "discovery": "web_search"})
        except Exception as exc:
            errors.append(f"{domain}: {exc}")
    return list({item["url"]: item for item in items}.values()), errors


def main():
    events = completed_games()
    report = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
              "purpose": "discovery_only", "verification": "not_playback_tested",
              "games": {}}
    for game_id, (when, opponent) in events.items():
        youtube, youtube_error = youtube_candidates(when, opponent)
        websites, website_errors = website_candidates(when, opponent)
        report["games"][game_id] = {
            "opponent": opponent, "date": when.date().isoformat(),
            "youtube": youtube, "websites": websites,
            "errors": ([youtube_error] if youtube_error else []) + website_errors,
        }
        print(f"{game_id} vs {opponent}: YouTube {len(youtube)}, web {len(websites)}")
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Discovery report written:", OUTPUT)


if __name__ == "__main__":
    main()
