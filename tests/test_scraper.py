"""Tests for scraper module (parsing logic, not actual scraping)."""

from pathlib import Path
from typing import Any

from feedmem.scraper import (
    TweetCollector,
    TweetDetailCollector,
    extract_instructions_bookmarks,
    extract_instructions_notifications,
    extract_instructions_user_timeline,
    get_auth_state_path,
    get_media_dir,
    get_referenced_ids,
    has_auth_state,
    parse_tweet_from_graphql,
)


def test_parse_tweet_from_graphql_standard() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": "12345",
                        "legacy": {
                            "full_text": "b&amp;b staff &lt;3",
                            "created_at": "Mon Jan 15 10:00:00 +0000 2024",
                            "favorite_count": 42,
                            "retweet_count": 7,
                            "reply_count": 3,
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "user123",
                                    "legacy": {
                                        "screen_name": "testuser",
                                        "name": "Test User",
                                    },
                                }
                            }
                        },
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert tweet["id"] == "12345"
    assert tweet["author_handle"] == "testuser"
    assert tweet["author_name"] == "Test User"
    assert tweet["content"] == "b&b staff <3"
    assert tweet["metrics_likes"] == 42
    assert tweet["metrics_retweets"] == 7


def test_parse_tweet_from_graphql_with_visibility_wrapper() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "TweetWithVisibilityResults",
                        "tweet": {
                            "__typename": "Tweet",
                            "rest_id": "67890",
                            "legacy": {
                                "full_text": "Visibility wrapped tweet",
                                "created_at": "Tue Jan 16 11:00:00 +0000 2024",
                            },
                            "core": {
                                "user_results": {
                                    "result": {
                                        "rest_id": "user456",
                                        "legacy": {
                                            "screen_name": "wrapped",
                                            "name": "Wrapped User",
                                        },
                                    }
                                }
                            },
                        },
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert tweet["id"] == "67890"
    assert tweet["author_handle"] == "wrapped"


def test_parse_tweet_from_graphql_with_media() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": "media123",
                        "legacy": {
                            "full_text": "Tweet with media",
                            "created_at": "Wed Jan 17 12:00:00 +0000 2024",
                            "extended_entities": {
                                "media": [
                                    {
                                        "id_str": "img1",
                                        "media_url_https": "https://pbs.twimg.com/1.jpg",
                                        "type": "photo",
                                    },
                                    {
                                        "id_str": "img2",
                                        "media_url_https": "https://pbs.twimg.com/2.jpg",
                                        "type": "photo",
                                    },
                                ]
                            },
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "user789",
                                    "legacy": {"screen_name": "media_user", "name": "Media"},
                                }
                            }
                        },
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert len(tweet["media"]) == 2
    assert tweet["media"][0]["id"] == "img1"
    assert tweet["media"][1]["url"] == "https://pbs.twimg.com/2.jpg"


def test_parse_tweet_from_graphql_with_reply() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": "reply123",
                        "legacy": {
                            "full_text": "@someone This is a reply",
                            "created_at": "Thu Jan 18 13:00:00 +0000 2024",
                            "in_reply_to_status_id_str": "original999",
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "replier",
                                    "legacy": {"screen_name": "replier", "name": "Replier"},
                                }
                            }
                        },
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert tweet["reply_to_id"] == "original999"


def test_parse_tweet_from_graphql_conversation_thread() -> None:
    """Test parsing replies from conversation thread entries (profile timeline format)."""
    entry = {
        "content": {
            "items": [
                {
                    "item": {
                        "itemContent": {
                            "tweet_results": {
                                "result": {
                                    "__typename": "Tweet",
                                    "rest_id": "thread123",
                                    "legacy": {
                                        "full_text": "Reply in thread",
                                        "created_at": "Fri Jan 19 14:00:00 +0000 2024",
                                        "in_reply_to_status_id_str": "parent456",
                                    },
                                    "core": {
                                        "user_results": {
                                            "result": {
                                                "rest_id": "threaduser",
                                                "legacy": {
                                                    "screen_name": "threaduser",
                                                    "name": "Thread User",
                                                },
                                            }
                                        }
                                    },
                                }
                            }
                        }
                    }
                }
            ]
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert tweet["id"] == "thread123"
    assert tweet["content"] == "Reply in thread"
    assert tweet["reply_to_id"] == "parent456"
    assert tweet["author_handle"] == "threaduser"


def test_parse_tweet_from_graphql_notification_entry() -> None:
    """Test parsing tweets from notification entries (different structure)."""
    entry = {
        "content": {
            "itemContent": {
                "notification": {
                    "tweet": {
                        "tweet_results": {
                            "result": {
                                "__typename": "Tweet",
                                "rest_id": "notif789",
                                "legacy": {
                                    "full_text": "@you mentioned you",
                                    "created_at": "Sat Jan 20 15:00:00 +0000 2024",
                                    "favorite_count": 5,
                                },
                                "core": {
                                    "user_results": {
                                        "result": {
                                            "rest_id": "mentioner",
                                            "legacy": {
                                                "screen_name": "mentioner",
                                                "name": "Mentioner",
                                            },
                                        }
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert tweet["id"] == "notif789"
    assert tweet["author_handle"] == "mentioner"
    assert tweet["content"] == "@you mentioned you"


def test_parse_tweet_from_graphql_invalid_typename() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "TweetUnavailable",
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is None


def test_parse_tweet_from_graphql_empty_entry() -> None:
    assert parse_tweet_from_graphql({}) is None
    assert parse_tweet_from_graphql({"content": {}}) is None


def test_parse_tweet_from_graphql_missing_id() -> None:
    entry: dict[str, Any] = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "legacy": {"full_text": "No ID"},
                        "core": {"user_results": {"result": {"legacy": {}}}},
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is None


def test_tweet_collector_deduplicates() -> None:
    collector = TweetCollector("like")

    data = {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        _make_entry("111", "First"),
                                        _make_entry("222", "Second"),
                                        _make_entry("111", "First duplicate"),
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    collector.extract_tweets(data)
    assert len(collector.tweets) == 2
    assert {t["id"] for t in collector.tweets} == {"111", "222"}


def test_tweet_collector_adds_interaction_metadata() -> None:
    collector = TweetCollector("bookmark")
    data = {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {"instructions": [{"entries": [_make_entry("999", "Test")]}]}
                    }
                }
            }
        }
    }

    collector.extract_tweets(data)
    assert collector.tweets[0]["interaction_type"] == "bookmark"
    assert "interaction_timestamp" in collector.tweets[0]


def test_has_auth_state(tmp_path: Path) -> None:
    import feedmem.scraper as scraper_module

    original_path = scraper_module.AUTH_STATE_PATH
    try:
        scraper_module.AUTH_STATE_PATH = tmp_path / "nonexistent.json"
        assert not has_auth_state()

        scraper_module.AUTH_STATE_PATH = tmp_path / "exists.json"
        scraper_module.AUTH_STATE_PATH.write_text("{}")
        assert has_auth_state()
    finally:
        scraper_module.AUTH_STATE_PATH = original_path


def test_get_auth_state_path() -> None:
    path = get_auth_state_path()
    assert path.name == "auth_state.json"
    assert "feedmem" in str(path)


def test_tweet_collector_stops_on_consecutive_known() -> None:
    known_ids = {"k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8", "k9", "k10"}
    collector = TweetCollector("like", known_ids=known_ids)

    data = {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        _make_entry("new1", "New"),
                                        *[_make_entry(f"k{i}", "Known") for i in range(1, 11)],
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    collector.extract_tweets(data)
    assert len(collector.tweets) == 1
    assert collector.tweets[0]["id"] == "new1"
    assert collector.should_stop is True


def test_tweet_collector_resets_consecutive_on_new() -> None:
    known_ids = {"k1", "k2", "k3"}
    collector = TweetCollector("like", known_ids=known_ids)

    data = {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        _make_entry("new1", "New"),
                                        _make_entry("k1", "Known"),
                                        _make_entry("k2", "Known"),
                                        _make_entry("new2", "New again"),
                                        _make_entry("k3", "Known"),
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    collector.extract_tweets(data)
    assert len(collector.tweets) == 2
    assert {t["id"] for t in collector.tweets} == {"new1", "new2"}
    assert collector.should_stop is False
    assert collector.consecutive_known == 1


def test_extract_instructions_user_timeline() -> None:
    data = {
        "data": {
            "user": {
                "result": {"timeline": {"timeline": {"instructions": [{"type": "AddEntries"}]}}}
            }
        }
    }
    result = extract_instructions_user_timeline(data)
    assert result == [{"type": "AddEntries"}]
    assert extract_instructions_user_timeline({}) == []


def test_extract_instructions_bookmarks() -> None:
    data = {
        "data": {"bookmark_timeline_v2": {"timeline": {"instructions": [{"type": "AddEntries"}]}}}
    }
    result = extract_instructions_bookmarks(data)
    assert result == [{"type": "AddEntries"}]
    assert extract_instructions_bookmarks({}) == []


def test_extract_instructions_notifications() -> None:
    data = {
        "data": {
            "viewer_v2": {
                "user_results": {
                    "result": {
                        "notification_timeline": {
                            "timeline": {"instructions": [{"type": "AddEntries"}]}
                        }
                    }
                }
            }
        }
    }
    result = extract_instructions_notifications(data)
    assert result == [{"type": "AddEntries"}]
    assert extract_instructions_notifications({}) == []


def test_tweet_collector_with_bookmarks_extractor() -> None:
    collector = TweetCollector("bookmark", extractor="bookmarks")
    data = {
        "data": {
            "bookmark_timeline_v2": {
                "timeline": {"instructions": [{"entries": [_make_entry("bk1", "Bookmarked")]}]}
            }
        }
    }
    collector.extract_tweets(data)
    assert len(collector.tweets) == 1
    assert collector.tweets[0]["id"] == "bk1"
    assert collector.tweets[0]["interaction_type"] == "bookmark"


def test_tweet_collector_with_notifications_extractor() -> None:
    collector = TweetCollector("mention", extractor="notifications")
    data = {
        "data": {
            "viewer_v2": {
                "user_results": {
                    "result": {
                        "notification_timeline": {
                            "timeline": {
                                "instructions": [{"entries": [_make_entry("notif1", "Mentioned")]}]
                            }
                        }
                    }
                }
            }
        }
    }
    collector.extract_tweets(data)
    assert len(collector.tweets) == 1
    assert collector.tweets[0]["id"] == "notif1"
    assert collector.tweets[0]["interaction_type"] == "mention"


def _make_entry(tweet_id: str, text: str) -> dict[str, Any]:
    return {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": tweet_id,
                        "legacy": {
                            "full_text": text,
                            "created_at": "Mon Jan 01 00:00:00 +0000 2024",
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "user1",
                                    "legacy": {"screen_name": "user", "name": "User"},
                                }
                            }
                        },
                    }
                }
            }
        }
    }


def test_parse_tweet_with_quoted_tweet() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": "quote123",
                        "legacy": {
                            "full_text": "Check this out!",
                            "created_at": "Mon Jan 01 00:00:00 +0000 2024",
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "quoter",
                                    "legacy": {"screen_name": "quoter", "name": "Quoter"},
                                }
                            }
                        },
                        "quoted_status_result": {
                            "result": {
                                "__typename": "Tweet",
                                "rest_id": "original456",
                            }
                        },
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert tweet["id"] == "quote123"
    assert tweet["quoted_id"] == "original456"


def test_parse_tweet_with_video_media() -> None:
    entry = {
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": "video123",
                        "legacy": {
                            "full_text": "Video tweet",
                            "created_at": "Mon Jan 01 00:00:00 +0000 2024",
                            "extended_entities": {
                                "media": [
                                    {
                                        "id_str": "vid1",
                                        "media_url_https": "https://pbs.twimg.com/thumb.jpg",
                                        "type": "video",
                                        "video_info": {
                                            "variants": [
                                                {
                                                    "content_type": "application/x-mpegURL",
                                                    "url": "https://video.twimg.com/playlist.m3u8",
                                                },
                                                {
                                                    "content_type": "video/mp4",
                                                    "bitrate": 832000,
                                                    "url": "https://video.twimg.com/low.mp4",
                                                },
                                                {
                                                    "content_type": "video/mp4",
                                                    "bitrate": 2176000,
                                                    "url": "https://video.twimg.com/high.mp4",
                                                },
                                            ]
                                        },
                                    }
                                ]
                            },
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "rest_id": "vid_user",
                                    "legacy": {"screen_name": "vid_user", "name": "Video User"},
                                }
                            }
                        },
                    }
                }
            }
        }
    }

    tweet = parse_tweet_from_graphql(entry)
    assert tweet is not None
    assert len(tweet["media"]) == 1
    assert tweet["media"][0]["type"] == "video"
    assert tweet["media"][0]["video_url"] == "https://video.twimg.com/high.mp4"


def test_get_referenced_ids() -> None:
    tweet: dict[str, Any] = {
        "id": "123",
        "reply_to_id": "parent1",
        "quoted_id": "quoted2",
        "retweeted_id": None,
    }
    refs = get_referenced_ids(tweet)
    assert refs == ["parent1", "quoted2"]

    tweet2: dict[str, Any] = {"id": "456"}
    assert get_referenced_ids(tweet2) == []


def test_tweet_detail_collector_extracts_from_result() -> None:
    collector = TweetDetailCollector()
    data = {
        "data": {
            "tweetResult": {
                "result": {
                    "__typename": "Tweet",
                    "rest_id": "detail123",
                    "legacy": {
                        "full_text": "Detail tweet",
                        "created_at": "Mon Jan 01 00:00:00 +0000 2024",
                    },
                    "core": {
                        "user_results": {
                            "result": {
                                "rest_id": "detailuser",
                                "legacy": {"screen_name": "detailuser", "name": "Detail User"},
                            }
                        }
                    },
                }
            }
        }
    }
    collector.extract(data)
    assert collector.tweet is not None
    assert collector.tweet["id"] == "detail123"


def test_get_media_dir() -> None:
    path = get_media_dir()
    assert path.name == "media"
    assert "feedmem" in str(path)
