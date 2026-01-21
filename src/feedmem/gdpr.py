"""GDPR archive parser for Twitter data exports."""

import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from feedmem.scraper import parse_twitter_timestamp

TweetData = dict[str, Any]


@dataclass
class ArchiveStats:
    own_tweets: int = 0
    likes: int = 0


def parse_js_file(content: str) -> Any:
    """Parse Twitter's JS-wrapped JSON files (e.g., 'window.YTD.tweets.part0 = [....')."""
    match = re.search(r"=\s*(\[[\s\S]*\])\s*;?\s*$", content, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    raise ValueError("Could not parse JS file format")


def iter_archive(archive_path: Path) -> Iterator[TweetData]:
    """Iterate over tweets from a Twitter GDPR archive zip (own tweets first, then likes)."""
    with zipfile.ZipFile(archive_path, "r") as zf:
        # First: own tweets
        for name in zf.namelist():
            if name.endswith("tweets.js") or name.endswith("tweet.js"):
                with zf.open(name) as f:
                    content = f.read().decode("utf-8")
                    data = parse_js_file(content)
                    for item in data:
                        tweet = _parse_tweet(item.get("tweet", item))
                        if tweet:
                            yield tweet

        # Second: likes (limited data - no author, no timestamp, truncated content)
        for name in zf.namelist():
            if name.endswith("like.js"):
                with zf.open(name) as f:
                    content = f.read().decode("utf-8")
                    data = parse_js_file(content)
                    for item in data:
                        like = _parse_like(item.get("like", item))
                        if like:
                            yield like


def get_archive_stats(archive_path: Path) -> ArchiveStats:
    """Get counts of items in archive without fully parsing."""
    stats = ArchiveStats()
    with zipfile.ZipFile(archive_path, "r") as zf:
        for name in zf.namelist():
            if name.endswith("tweets.js") or name.endswith("tweet.js"):
                with zf.open(name) as f:
                    content = f.read().decode("utf-8")
                    data = parse_js_file(content)
                    stats.own_tweets = len(data)
            elif name.endswith("like.js"):
                with zf.open(name) as f:
                    content = f.read().decode("utf-8")
                    data = parse_js_file(content)
                    stats.likes = len(data)
    return stats


def parse_archive(archive_path: Path) -> list[TweetData]:
    """Parse tweets from a Twitter GDPR archive zip."""
    return list(iter_archive(archive_path))


def _parse_tweet(raw: dict[str, Any]) -> TweetData | None:
    """Convert a tweet from GDPR format to our internal format."""
    tweet_id = raw.get("id_str") or raw.get("id")
    if not tweet_id:
        return None

    return {
        "id": str(tweet_id),
        "author_id": "",
        "author_handle": "",
        "author_name": "",
        "content": raw.get("full_text", raw.get("text", "")),
        "created_at": parse_twitter_timestamp(raw.get("created_at", "")),
        "reply_to_id": raw.get("in_reply_to_status_id_str"),
        "metrics_likes": raw.get("favorite_count"),
        "metrics_retweets": raw.get("retweet_count"),
        "media": [
            {
                "id": m.get("id_str", ""),
                "url": m.get("media_url_https", m.get("media_url", "")),
                "type": m.get("type", ""),
            }
            for m in raw.get("extended_entities", {}).get("media", [])
        ],
        "raw_json": json.dumps(raw),
        "interaction_type": "own",
    }


def _parse_like(raw: dict[str, Any]) -> TweetData | None:
    """Convert a like from GDPR format to our internal format.

    Note: GDPR likes have very limited data - no author, no timestamp, truncated content.
    """
    tweet_id = raw.get("tweetId")
    if not tweet_id:
        return None

    return {
        "id": str(tweet_id),
        "author_id": "",
        "author_handle": "",
        "author_name": "",
        "content": raw.get("fullText", ""),  # Often truncated with "..." or "… https://..."
        "created_at": "",  # Not available in GDPR likes
        "media": [],
        "raw_json": json.dumps(raw),
        "interaction_type": "like",
    }
