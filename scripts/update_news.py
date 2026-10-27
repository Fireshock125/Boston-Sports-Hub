
import json
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

OUTPUT = Path("patriots-news.json")
MAX_ARTICLES = 10

FEEDS = [
    (
        "ESPN",
        "https://www.espn.com/espn/rss/nfl/news"
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(
            '"New England Patriots" when:7d'
        )
        + "&hl=en-US&gl=US&ceid=US:en"
    ),
    (
        "Google News",
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(
            '"New England Patriots" NFL when:7d'
        )
        + "&hl=en-US&gl=US&ceid=US:en"
    )
]

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
            if url.startswith("https://") and media_type.startswith("image/"):
                return url

    description = item.findtext("description", "")
    match = re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+)',
        description,
        re.IGNORECASE
    )
    return unescape(match.group(1)) if match else ""


def read_feed(source, url):
    request = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read()

    root = ET.fromstring(content)
    articles = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()

        if not title or not link.startswith("https://"):
            continue

        # ESPN's NFL feed covers all teams, so filter its headlines.
        if source == "ESPN":
            combined = (
                title + " " + clean_text(item.findtext("description"))
            ).lower()

            if not any(term in combined for term in [
                "patriots",
                "new england",
                "drake maye"
            ]):
                continue

        publisher = source
        source_element = item.find("source")

        if source_element is not None and source_element.text:
            publisher = clean_text(source_element.text)

        description = clean_text(item.findtext("description"))

        # Google News often adds the publisher to the headline.
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
            "published": parse_date(item.findtext("pubDate")),
            "image": get_image(item)
        })

    return articles


def main():
    articles = []

    for source, url in FEEDS:
        try:
            fetched = read_feed(source, url)
            articles.extend(fetched)
            print(f"{source}: found {len(fetched)} articles")
        except Exception as error:
            print(f"Could not read {source}: {error}")

    unique = {}
    for article in articles:
        key = re.sub(
            r"[^a-z0-9]+", "",
            article["title"].lower()
        )

        if key not in unique:
            unique[key] = article
        elif article["image"] and not unique[key]["image"]:
            unique[key] = article

    latest = sorted(
        unique.values(),
        key=lambda article: article["published"],
        reverse=True
    )[:MAX_ARTICLES]

    # Don't erase previously collected news if all feeds fail.
    if not latest:
        print("No new articles found. Keeping existing news.")
        return

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "articles": latest
    }

    OUTPUT.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Saved {len(latest)} articles to {OUTPUT}")


if __name__ == "__main__":
    main()
