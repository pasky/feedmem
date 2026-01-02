"""Tests for scraper module (parsing logic, not actual scraping)."""

from pathlib import Path
from typing import Any

from feedmem.scraper import (
    TweetCollector,
    get_auth_state_path,
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
