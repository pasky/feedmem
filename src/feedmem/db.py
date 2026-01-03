"""Database schema and operations for feedmem."""

from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
-- Tweets/posts from any platform
CREATE TABLE IF NOT EXISTS tweet (
    id TEXT PRIMARY KEY,
    author_id TEXT NOT NULL,
    author_handle TEXT NOT NULL,
    author_name TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reply_to_id TEXT,
    quoted_id TEXT,
    retweeted_id TEXT,
    thread_id TEXT,
    metrics_likes INTEGER,
    metrics_retweets INTEGER,
    metrics_replies INTEGER,
    raw_json TEXT
);

-- User interactions with tweets
CREATE TABLE IF NOT EXISTS interaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,  -- like, bookmark, retweet, reply, mention, notification
    tweet_id TEXT NOT NULL REFERENCES tweet(id),
    timestamp TEXT NOT NULL,
    metadata TEXT,  -- JSON for type-specific data
    UNIQUE(type, tweet_id)
);

-- Media attachments
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    tweet_id TEXT NOT NULL REFERENCES tweet(id),
    url TEXT NOT NULL,
    local_path TEXT,
    mime_type TEXT,
    extracted_text TEXT,  -- OCR results (future)
    embedding BLOB  -- vector for semantic search (future)
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS tweet_fts USING fts5(
    content,
    author_handle,
    author_name,
    content='tweet',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS tweet_ai AFTER INSERT ON tweet BEGIN
    INSERT INTO tweet_fts(rowid, content, author_handle, author_name)
    VALUES (NEW.rowid, NEW.content, NEW.author_handle, NEW.author_name);
END;

CREATE TRIGGER IF NOT EXISTS tweet_ad AFTER DELETE ON tweet BEGIN
    INSERT INTO tweet_fts(tweet_fts, rowid, content, author_handle, author_name)
    VALUES ('delete', OLD.rowid, OLD.content, OLD.author_handle, OLD.author_name);
END;

CREATE TRIGGER IF NOT EXISTS tweet_au AFTER UPDATE ON tweet BEGIN
    INSERT INTO tweet_fts(tweet_fts, rowid, content, author_handle, author_name)
    VALUES ('delete', OLD.rowid, OLD.content, OLD.author_handle, OLD.author_name);
    INSERT INTO tweet_fts(rowid, content, author_handle, author_name)
    VALUES (NEW.rowid, NEW.content, NEW.author_handle, NEW.author_name);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tweet_author ON tweet(author_handle);
CREATE INDEX IF NOT EXISTS idx_tweet_created ON tweet(created_at);
CREATE INDEX IF NOT EXISTS idx_interaction_type ON interaction(type);
CREATE INDEX IF NOT EXISTS idx_interaction_tweet ON interaction(tweet_id);
CREATE INDEX IF NOT EXISTS idx_media_tweet ON media(tweet_id);
"""


def get_default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "feedmem" / "feedmem.db"


async def init_db(db_path: Path | None = None) -> aiosqlite.Connection:
    if db_path is None:
        db_path = get_default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    await db.executescript(SCHEMA)
    await db.commit()
    return db


async def upsert_tweet(
    db: aiosqlite.Connection,
    *,
    id: str,
    author_id: str,
    author_handle: str,
    content: str,
    created_at: str,
    author_name: str | None = None,
    reply_to_id: str | None = None,
    quoted_id: str | None = None,
    retweeted_id: str | None = None,
    thread_id: str | None = None,
    metrics_likes: int | None = None,
    metrics_retweets: int | None = None,
    metrics_replies: int | None = None,
    raw_json: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO tweet (id, author_id, author_handle, author_name, content, created_at,
                          reply_to_id, quoted_id, retweeted_id, thread_id,
                          metrics_likes, metrics_retweets, metrics_replies, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            content = excluded.content,
            metrics_likes = excluded.metrics_likes,
            metrics_retweets = excluded.metrics_retweets,
            metrics_replies = excluded.metrics_replies,
            raw_json = excluded.raw_json
        """,
        (
            id,
            author_id,
            author_handle,
            author_name,
            content,
            created_at,
            reply_to_id,
            quoted_id,
            retweeted_id,
            thread_id,
            metrics_likes,
            metrics_retweets,
            metrics_replies,
            raw_json,
        ),
    )
    await db.commit()


async def add_interaction(
    db: aiosqlite.Connection,
    *,
    type: str,
    tweet_id: str,
    timestamp: str,
    metadata: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO interaction (type, tweet_id, timestamp, metadata)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(type, tweet_id) DO NOTHING
        """,
        (type, tweet_id, timestamp, metadata),
    )
    await db.commit()


async def add_media(
    db: aiosqlite.Connection,
    *,
    id: str,
    tweet_id: str,
    url: str,
    local_path: str | None = None,
    mime_type: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO media (id, tweet_id, url, local_path, mime_type)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            local_path = excluded.local_path
        """,
        (id, tweet_id, url, local_path, mime_type),
    )
    await db.commit()


SearchResult = dict[str, Any]


async def list_tweets(
    db: aiosqlite.Connection,
    *,
    interaction_type: str | None = None,
    limit: int = 50,
) -> list[SearchResult]:
    sql = """
        WITH latest_interaction AS (
            SELECT tweet_id, MAX(id) AS interaction_id
            FROM interaction
    """
    params: list[str | int] = []
    if interaction_type:
        sql += " WHERE type = ?"
        params.append(interaction_type)
    sql += """
            GROUP BY tweet_id
        )
        SELECT t.id, t.author_id, t.author_handle, t.author_name, t.content, t.created_at,
               t.reply_to_id, t.metrics_likes, t.metrics_retweets, t.metrics_replies,
               i.type as interaction_type, i.timestamp as interaction_timestamp,
               GROUP_CONCAT(DISTINCT m.url) as media_urls
        FROM tweet t
        LEFT JOIN latest_interaction li ON li.tweet_id = t.id
        LEFT JOIN interaction i ON i.id = li.interaction_id
        LEFT JOIN media m ON m.tweet_id = t.id
    """
    if interaction_type:
        sql += " WHERE i.type IS NOT NULL"
    sql += """
        GROUP BY t.id
        ORDER BY COALESCE(i.timestamp, t.created_at) DESC
        LIMIT ?
    """
    params.append(limit)

    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        return [dict(zip(columns, row, strict=False)) for row in rows]


async def get_tweet_ids(
    db: aiosqlite.Connection,
    interaction_type: str | None = None,
) -> set[str]:
    """Get all known tweet IDs, optionally filtered by interaction type."""
    if interaction_type:
        sql = """
            SELECT DISTINCT t.id FROM tweet t
            JOIN interaction i ON i.tweet_id = t.id
            WHERE i.type = ?
        """
        async with db.execute(sql, (interaction_type,)) as cursor:
            rows = await cursor.fetchall()
    else:
        async with db.execute("SELECT id FROM tweet") as cursor:
            rows = await cursor.fetchall()
    return {row[0] for row in rows}


async def search_tweets(
    db: aiosqlite.Connection,
    query: str,
    *,
    interaction_type: str | None = None,
    limit: int = 50,
) -> list[SearchResult]:
    sql = """
        WITH latest_interaction AS (
            SELECT tweet_id, MAX(id) AS interaction_id
            FROM interaction
    """
    params: list[str | int] = []
    if interaction_type:
        sql += " WHERE type = ?"
        params.append(interaction_type)
    sql += """
            GROUP BY tweet_id
        )
        SELECT t.id, t.author_handle, t.author_name, t.content, t.created_at,
               i.type as interaction_type, i.timestamp as interaction_timestamp
        FROM tweet_fts f
        JOIN tweet t ON t.rowid = f.rowid
        LEFT JOIN latest_interaction li ON li.tweet_id = t.id
        LEFT JOIN interaction i ON i.id = li.interaction_id
        WHERE tweet_fts MATCH ?
    """
    params.append(query)
    if interaction_type:
        sql += " AND i.type IS NOT NULL"
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        return [dict(zip(columns, row, strict=False)) for row in rows]
