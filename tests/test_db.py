"""Tests for feedmem database operations."""

from collections.abc import AsyncGenerator
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from feedmem.db import (
    add_interaction,
    add_media,
    init_db,
    list_tweets,
    search_tweets,
    upsert_tweet,
)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[aiosqlite.Connection]:
    conn = await init_db(Path(":memory:"))
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_upsert_and_search(db: aiosqlite.Connection) -> None:
    await upsert_tweet(
        db,
        id="123",
        author_id="user1",
        author_handle="testuser",
        author_name="Test User",
        content="Hello world, this is a test tweet about Python",
        created_at="2024-01-15T10:00:00Z",
    )
    await add_interaction(db, type="like", tweet_id="123", timestamp="2024-01-15T12:00:00Z")

    results = await search_tweets(db, "python")
    assert len(results) == 1
    assert results[0]["author_handle"] == "testuser"
    assert results[0]["interaction_type"] == "like"


@pytest.mark.asyncio
async def test_search_by_interaction_type(db: aiosqlite.Connection) -> None:
    await upsert_tweet(
        db,
        id="1",
        author_id="u1",
        author_handle="alice",
        content="cats are great",
        created_at="2024-01-01T00:00:00Z",
    )
    await upsert_tweet(
        db,
        id="2",
        author_id="u2",
        author_handle="bob",
        content="cats rule",
        created_at="2024-01-02T00:00:00Z",
    )
    await add_interaction(db, type="like", tweet_id="1", timestamp="2024-01-01T01:00:00Z")
    await add_interaction(db, type="bookmark", tweet_id="2", timestamp="2024-01-02T01:00:00Z")

    likes = await search_tweets(db, "cats", interaction_type="like")
    assert len(likes) == 1
    assert likes[0]["author_handle"] == "alice"

    bookmarks = await search_tweets(db, "cats", interaction_type="bookmark")
    assert len(bookmarks) == 1
    assert bookmarks[0]["author_handle"] == "bob"


@pytest.mark.asyncio
async def test_upsert_updates_existing(db: aiosqlite.Connection) -> None:
    await upsert_tweet(
        db,
        id="999",
        author_id="u1",
        author_handle="test",
        content="original",
        created_at="2024-01-01T00:00:00Z",
        metrics_likes=10,
    )
    await upsert_tweet(
        db,
        id="999",
        author_id="u1",
        author_handle="test",
        content="updated content",
        created_at="2024-01-01T00:00:00Z",
        metrics_likes=50,
    )
    results = await search_tweets(db, "updated")
    assert len(results) == 1
    assert "updated" in results[0]["content"]


@pytest.mark.asyncio
async def test_search_deduplicates_interactions(db: aiosqlite.Connection) -> None:
    await upsert_tweet(
        db,
        id="abc",
        author_id="u1",
        author_handle="combo",
        content="hello world with python",
        created_at="2024-01-01T00:00:00Z",
    )
    await add_interaction(db, type="like", tweet_id="abc", timestamp="2024-01-01T01:00:00Z")
    await add_interaction(
        db,
        type="bookmark",
        tweet_id="abc",
        timestamp="2024-01-01T02:00:00Z",
    )

    results = await search_tweets(db, "python")
    assert len(results) == 1
    assert results[0]["id"] == "abc"
    assert results[0]["interaction_type"] == "bookmark"


@pytest.mark.asyncio
async def test_list_collapses_interaction_and_media(db: aiosqlite.Connection) -> None:
    await upsert_tweet(
        db,
        id="xyz",
        author_id="u1",
        author_handle="mediauser",
        content="photo tweet",
        created_at="2024-01-01T00:00:00Z",
    )
    await add_media(
        db,
        id="m1",
        tweet_id="xyz",
        url="https://example.com/1.jpg",
        mime_type="image/jpeg",
    )
    await add_media(
        db,
        id="m2",
        tweet_id="xyz",
        url="https://example.com/2.jpg",
        mime_type="image/jpeg",
    )
    await add_interaction(db, type="like", tweet_id="xyz", timestamp="2024-01-01T01:00:00Z")
    await add_interaction(
        db,
        type="bookmark",
        tweet_id="xyz",
        timestamp="2024-01-01T02:00:00Z",
    )

    results = await list_tweets(db)
    assert len(results) == 1
    urls = (results[0]["media_urls"] or "").split(",")
    assert set(urls) == {"https://example.com/1.jpg", "https://example.com/2.jpg"}
    assert results[0]["interaction_type"] == "bookmark"
