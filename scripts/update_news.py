
import json
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

MAX_ARTICLES = 10

TEAMS = {
    "patriots": {
        "name": "New England Patriots",
        "sport": "nfl",
        "searches": [
            '"New England Patriots" when:7d',
            '"New England Patriots" NFL when:7d'
        ],
        "keywords": [
            "patriots",
            "new england",
            "drake maye"
        ]
    },
    "celtics": {
        "name": "Boston Celtics",
        "sport": "nba",
        "searches": [
            '"Boston Celtics" when:7d',
            '"Boston Celtics" NBA when:7d'
        ],
        "keywords": [
            "celtics",
            "boston celtics",
            "jayson tatum",
            "jaylen brown"
        ]
    },
    "red-sox": {
        "name": "Boston Red Sox",
        "sport": "mlb",
        "searches": [
            '"Boston Red Sox" when:7d',
            '"Boston Red Sox" MLB when:7d'
        ],
        "keywords": [
            "red sox",
            "boston red sox",
            "fenway park",
            "alex cora"
        ]
    },
    "bruins": {
        "name": "Boston Bruins",
        "sport": "nhl",
        "searches": [
            '"Boston Bruins" when:7d',
            '"Boston Bruins" NHL when:7d'
        ],
        "keywords": [
            "bruins",
            "boston bruins",
            "david pastrnak",
            "charlie mcavoy"
        ]
    }
}

HEADERS = {
    "User-Agent": "BostonSportsHub/1.0 (news feed reader)"
}


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = unescape(value)
    return " ".join(value.split())


def parse_date(value):
    try:
        return parsedate_to_datetime(value).astimezone(
            timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc).isoformat()


def get_image(item):
    for child in item:
        tag = child.tag.lower()

        if tag.endswith("thumbnail") or tag.endswith("content"):
            url = child.attrib.get("url", "")

            if url.startswith("https://"):
                return url

        if tag.endswith("enclosure"):
            url = child.attrib.get("url", "")
            media_type = child.attrib.get("type", "")

            if (
                url.startswith("https://")
                and media_type.startswith("image/")
            ):
                return url

    description = item.findtext("description", "")

    match = re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+)',
        description,
        re.IGNORECASE
    )

    return unescape(match.group(1)) if match else ""


def get_feeds(team):
    sport = team["sport"]

    feeds = [
        (
            "ESPN",
            f"https://www.espn.com/espn/rss/{sport}/news"
        )
    ]

    for search in team["searches"]:
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(search)
            + "&hl=en-US&gl=US&ceid=US:en"
        )

        feeds.append(("Google News", url))

    return feeds


def read_feed(source, url, keywords):
    request = urllib.request.Request(
        url,
        headers=HEADERS
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:
        content = response.read()

    root = ET.fromstring(content)
    articles = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()

        if not title or not link.startswith("https://"):
            continue

        description = clean_text(
            item.findtext("description")
        )

        if source == "ESPN":
            combined = (
                title + " " + description
            ).lower()

            if not any(
                keyword in combined
                for keyword in keywords
            ):
                continue

        publisher = source
        source_element = item.find("source")

        if (
            source_element is not None
            and source_element.text
        ):
            publisher = clean_text(
                source_element.text
            )

        if source == "Google News" and " - " in title:
            headline, suffix = title.rsplit(" - ", 1)

            if publisher == "Google News":
                publisher = suffix

            title = headline

        articles.append({
            "title": title,
            "description": description[:250],
            "url": link,
            "source": publisher,
            "published": parse_date(
                item.findtext("pubDate")
            ),
            "image": get_image(item)
        })

    return articles


def update_team(team_key, team):
    print(
        f"\nUpdating {team['name']} news..."
    )

    articles = []

    for source, url in get_feeds(team):
        try:
            fetched = read_feed(
                source,
                url,
                team["keywords"]
            )

            articles.extend(fetched)

            print(
                f"{source}: found {len(fetched)} articles"
            )

        except Exception as error:
            print(
                f"Could not read {source}: {error}"
            )

    unique = {}

    for article in articles:
        key = re.sub(
            r"[^a-z0-9]+",
            "",
            article["title"].lower()
        )

        if key not in unique:
            unique[key] = article

        elif (
            article["image"]
            and not unique[key]["image"]
        ):
            unique[key] = article

    latest = sorted(
        unique.values(),
        key=lambda article: article["published"],
        reverse=True
    )[:MAX_ARTICLES]

    if not latest:
        print(
            f"No new {team['name']} articles found. "
            "Keeping existing news."
        )
        return

    output = {
        "updated": datetime.now(
            timezone.utc
        ).isoformat(),
        "articles": latest
    }

    output_file = Path(
        f"{team_key}-news.json"
    )

    output_file.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print(
        f"Saved {len(latest)} articles "
        f"to {output_file}"
    )


def main():
    for team_key, team in TEAMS.items():
        update_team(team_key, team)


if __name__ == "__main__":
    main()
