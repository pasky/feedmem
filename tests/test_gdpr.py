"""Tests for GDPR archive parser."""

import json
import zipfile
from pathlib import Path

import pytest

from feedmem.gdpr import parse_archive, parse_js_file


def test_parse_js_file_standard_format() -> None:
    content = 'window.YTD.tweets.part0 = [{"tweet": {"id": "123"}}]'
    result = parse_js_file(content)
    assert result == [{"tweet": {"id": "123"}}]


def test_parse_js_file_with_whitespace() -> None:
    content = """window.YTD.tweets.part0 = [
        {"tweet": {"id": "456", "full_text": "Hello world"}}
    ]"""
    result = parse_js_file(content)
    assert len(result) == 1
    assert result[0]["tweet"]["id"] == "456"


def test_parse_js_file_invalid_format() -> None:
    with pytest.raises(ValueError, match="Could not parse"):
        parse_js_file("not valid js format")


def test_parse_archive_extracts_tweets(tmp_path: Path) -> None:
    archive_path = tmp_path / "twitter-archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "111",
                "full_text": "First tweet about Python",
                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
                "favorite_count": 5,
                "retweet_count": 2,
            }
        },
        {
            "tweet": {
                "id_str": "222",
                "full_text": "Second tweet about Rust",
                "created_at": "Tue Jan 02 14:00:00 +0000 2024",
            }
        },
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    result = parse_archive(archive_path)
    assert len(result) == 2
    assert result[0]["id"] == "111"
    assert result[0]["content"] == "First tweet about Python"
    assert result[0]["metrics_likes"] == 5
    assert result[1]["id"] == "222"
    assert "Rust" in result[1]["content"]


def test_parse_archive_handles_media(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "333",
                "full_text": "Tweet with image",
                "created_at": "Wed Jan 03 10:00:00 +0000 2024",
                "extended_entities": {
                    "media": [
                        {
                            "id_str": "media1",
                            "media_url_https": "https://pbs.twimg.com/media/abc.jpg",
                            "type": "photo",
                        }
                    ]
                },
            }
        }
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    result = parse_archive(archive_path)
    assert len(result) == 1
    assert len(result[0]["media"]) == 1
    assert result[0]["media"][0]["id"] == "media1"
    assert "abc.jpg" in result[0]["media"][0]["url"]


def test_parse_archive_handles_replies(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "444",
                "full_text": "@someone This is a reply",
                "created_at": "Thu Jan 04 09:00:00 +0000 2024",
                "in_reply_to_status_id_str": "999",
            }
        }
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    result = parse_archive(archive_path)
    assert result[0]["reply_to_id"] == "999"


def test_parse_archive_empty_zip(tmp_path: Path) -> None:
    archive_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/other.js", "window.YTD.other.part0 = []")

    result = parse_archive(archive_path)
    assert result == []


def test_parse_archive_preserves_raw_json(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweet_obj = {
        "id_str": "555",
        "full_text": "Test",
        "created_at": "Fri Jan 05 08:00:00 +0000 2024",
        "custom_field": "preserved",
    }
    js_content = f"window.YTD.tweets.part0 = [{json.dumps({'tweet': tweet_obj})}]"

    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    result = parse_archive(archive_path)
    raw = json.loads(result[0]["raw_json"])
    assert raw["custom_field"] == "preserved"
