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
    insert_tweet_if_missing,
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

    await upsert_tweet(
        db,
        id="q1",
        author_id="u1",
        author_handle="quotee",
        content="shared wisdom",
        created_at="2024-01-10T10:00:00Z",
    )
    await upsert_tweet(
        db,
        id="q2",
        author_id="u2",
        author_handle="quoter",
        content="my take",
        created_at="2024-01-11T10:00:00Z",
        quoted_id="q1",
    )
    await upsert_tweet(
        db,
        id="q3",
        author_id="u3",
        author_handle="recursive",
        content="second layer",
        created_at="2024-01-12T10:00:00Z",
        quoted_id="q2",
    )

    quote_results = await search_tweets(db, "wisdom")
    assert [r["id"] for r in quote_results] == ["q3", "q2", "q1"]


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
async def test_insert_if_missing_skips_existing(db: aiosqlite.Connection) -> None:
    """insert_tweet_if_missing should not modify existing tweets."""
    # First insert via regular upsert (simulating scraped tweet with rich data)
    await upsert_tweet(
        db,
        id="existing",
        author_id="rich_author_id",
        author_handle="rich_handle",
        author_name="Rich Name",
        content="rich content with details",
        created_at="2024-01-01T00:00:00Z",
        metrics_likes=100,
        raw_json='{"detailed": true}',
    )

    # Try to insert same ID via if_missing (simulating GDPR with sparse data)
    was_new = await insert_tweet_if_missing(
        db,
        id="existing",
        author_id="sparse_id",
        author_handle="sparse_handle",
        author_name="Sparse",
        content="sparse content",
        created_at="2024-01-01T00:00:00Z",
        metrics_likes=0,
        raw_json='{"sparse": true}',
    )

    assert was_new is False

    # Verify original data preserved
    results = await search_tweets(db, "rich")
    assert len(results) == 1
    assert results[0]["author_handle"] == "rich_handle"
    assert results[0]["content"] == "rich content with details"
    assert results[0]["metrics_likes"] == 100


@pytest.mark.asyncio
async def test_insert_if_missing_inserts_new(db: aiosqlite.Connection) -> None:
    """insert_tweet_if_missing should insert new tweets."""
    was_new = await insert_tweet_if_missing(
        db,
        id="brand_new",
        author_id="new_author",
        author_handle="newuser",
        content="completely new tweet",
        created_at="2024-01-01T00:00:00Z",
    )

    assert was_new is True

    results = await search_tweets(db, "completely")
    assert len(results) == 1
    assert results[0]["author_handle"] == "newuser"


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
    media_urls = {m.url for m in results[0]["media"]}
    assert media_urls == {"https://example.com/1.jpg", "https://example.com/2.jpg"}
    assert results[0]["interaction_type"] == "bookmark"

    search_results = await search_tweets(db, "photo")
    assert len(search_results) == 1
    assert set(search_results[0].keys()) == set(results[0].keys())


@pytest.mark.asyncio
async def test_media_shared_across_tweets(db: aiosqlite.Connection) -> None:
    """Same media ID appearing in multiple tweets should be deduplicated."""
    await upsert_tweet(
        db,
        id="t1",
        author_id="u1",
        author_handle="alice",
        content="original post",
        created_at="2024-01-01T00:00:00Z",
    )
    await upsert_tweet(
        db,
        id="t2",
        author_id="u2",
        author_handle="bob",
        content="retweet of original",
        created_at="2024-01-02T00:00:00Z",
    )
    await add_media(
        db,
        id="shared_media",
        tweet_id="t1",
        url="https://example.com/shared.jpg",
        mime_type="image/jpeg",
    )
    await add_media(
        db,
        id="shared_media",
        tweet_id="t2",
        url="https://example.com/shared.jpg",
        mime_type="image/jpeg",
    )

    results = await list_tweets(db)
    assert len(results) == 2
    for r in results:
        assert len(r["media"]) == 1
        assert r["media"][0].url == "https://example.com/shared.jpg"

    async with db.execute("SELECT COUNT(*) FROM media") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1
