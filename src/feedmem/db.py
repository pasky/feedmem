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

-- Media attachments (deduplicated by Twitter media ID)
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    local_path TEXT,
    mime_type TEXT,
    description TEXT,  -- LLM-generated description
    embedding BLOB  -- vector for semantic search (future)
);

-- Junction table for tweet-media many-to-many relationship
CREATE TABLE IF NOT EXISTS tweet_media (
    tweet_id TEXT NOT NULL REFERENCES tweet(id),
    media_id TEXT NOT NULL REFERENCES media(id),
    PRIMARY KEY (tweet_id, media_id)
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

-- FTS5 for media descriptions
CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
    description,
    content='media',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS media_ai AFTER INSERT ON media BEGIN
    INSERT INTO media_fts(rowid, description)
    VALUES (NEW.rowid, NEW.description);
END;

CREATE TRIGGER IF NOT EXISTS media_ad AFTER DELETE ON media BEGIN
    INSERT INTO media_fts(media_fts, rowid, description)
    VALUES ('delete', OLD.rowid, OLD.description);
END;

CREATE TRIGGER IF NOT EXISTS media_au AFTER UPDATE ON media BEGIN
    INSERT INTO media_fts(media_fts, rowid, description)
    VALUES ('delete', OLD.rowid, OLD.description);
    INSERT INTO media_fts(rowid, description)
    VALUES (NEW.rowid, NEW.description);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tweet_author ON tweet(author_handle);
CREATE INDEX IF NOT EXISTS idx_tweet_created ON tweet(created_at);
CREATE INDEX IF NOT EXISTS idx_tweet_reply_to ON tweet(reply_to_id);
CREATE INDEX IF NOT EXISTS idx_tweet_quoted ON tweet(quoted_id);
CREATE INDEX IF NOT EXISTS idx_tweet_retweeted ON tweet(retweeted_id);
CREATE INDEX IF NOT EXISTS idx_interaction_type ON interaction(type);
CREATE INDEX IF NOT EXISTS idx_interaction_tweet ON interaction(tweet_id);
CREATE INDEX IF NOT EXISTS idx_tweet_media_tweet ON tweet_media(tweet_id);
CREATE INDEX IF NOT EXISTS idx_tweet_media_media ON tweet_media(media_id);
"""


def get_default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "feedmem" / "feedmem.db"


async def init_db(db_path: Path | None = None) -> aiosqlite.Connection:
    if db_path is None:
        db_path = get_default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    await db.executescript(SCHEMA)
    await _migrate(db)
    await db.commit()
    return db


async def _migrate(db: aiosqlite.Connection) -> None:
    """Apply schema migrations for existing databases."""
    async with db.execute("PRAGMA table_info(tweet)") as cursor:
        columns = {row[1] for row in await cursor.fetchall()}

    if "quoted_id" not in columns:
        await db.execute("ALTER TABLE tweet ADD COLUMN quoted_id TEXT")
    if "retweeted_id" not in columns:
        await db.execute("ALTER TABLE tweet ADD COLUMN retweeted_id TEXT")

    async with db.execute("PRAGMA table_info(media)") as cursor:
        media_columns = {row[1] for row in await cursor.fetchall()}

    if "tweet_id" in media_columns:
        await db.execute(
            """
            INSERT OR IGNORE INTO tweet_media (tweet_id, media_id)
            SELECT tweet_id, id FROM media
            """
        )
        await db.execute("DROP INDEX IF EXISTS idx_media_tweet")
        await db.execute("ALTER TABLE media DROP COLUMN tweet_id")

    if "extracted_text" in media_columns:
        await db.execute("ALTER TABLE media RENAME COLUMN extracted_text TO description")

    # Populate media_fts if empty but media has data
    async with db.execute("SELECT COUNT(*) FROM media_fts") as cursor:
        media_fts_count = (await cursor.fetchone())[0]  # type: ignore[index]
    if media_fts_count == 0:
        async with db.execute("SELECT COUNT(*) FROM media") as cursor:
            media_count = (await cursor.fetchone())[0]  # type: ignore[index]
        if media_count > 0:
            await db.execute(
                """
                INSERT INTO media_fts(rowid, description)
                SELECT rowid, description FROM media WHERE description IS NOT NULL
                """
            )


async def insert_tweet_if_missing(
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
) -> bool:
    """Insert tweet only if it doesn't exist. Returns True if inserted, False if skipped."""
    cursor = await db.execute(
        """
        INSERT INTO tweet (id, author_id, author_handle, author_name, content, created_at,
                          reply_to_id, quoted_id, retweeted_id, thread_id,
                          metrics_likes, metrics_retweets, metrics_replies, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
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
    return cursor.rowcount > 0


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
    description: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO media (id, url, local_path, mime_type, description)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            local_path = COALESCE(excluded.local_path, media.local_path),
            description = COALESCE(excluded.description, media.description)
        """,
        (id, url, local_path, mime_type, description),
    )
    await db.execute(
        """
        INSERT INTO tweet_media (tweet_id, media_id)
        VALUES (?, ?)
        ON CONFLICT DO NOTHING
        """,
        (tweet_id, id),
    )
    await db.commit()


SearchResult = dict[str, Any]


class MediaItem:
    __slots__ = ("url", "description")

    def __init__(self, url: str, description: str | None) -> None:
        self.url = url
        self.description = description


async def get_tweet_media(
    db: aiosqlite.Connection, tweet_ids: list[str]
) -> dict[str, list[MediaItem]]:
    """Fetch media for multiple tweets, returning {tweet_id: [MediaItem, ...]}."""
    if not tweet_ids:
        return {}
    placeholders = ",".join("?" * len(tweet_ids))
    sql = f"""
        SELECT tm.tweet_id, COALESCE(m.local_path, m.url) as url, m.description
        FROM tweet_media tm
        JOIN media m ON m.id = tm.media_id
        WHERE tm.tweet_id IN ({placeholders})
    """
    result: dict[str, list[MediaItem]] = {}
    async with db.execute(sql, tweet_ids) as cursor:
        async for row in cursor:
            tweet_id, url, description = row
            if tweet_id not in result:
                result[tweet_id] = []
            result[tweet_id].append(MediaItem(url, description))
    return result


async def _enrich_with_media(
    db: aiosqlite.Connection, results: list[SearchResult]
) -> list[SearchResult]:
    """Add media list to each result."""
    tweet_ids = [r["id"] for r in results]
    media_map = await get_tweet_media(db, tweet_ids)
    for r in results:
        r["media"] = media_map.get(r["id"], [])
    return results


async def get_tweet(db: aiosqlite.Connection, tweet_id: str) -> SearchResult | None:
    """Get a single tweet by ID."""
    sql = """
        SELECT t.id, t.author_id, t.author_handle, t.author_name, t.content, t.created_at,
               t.reply_to_id, t.quoted_id, t.retweeted_id,
               t.metrics_likes, t.metrics_retweets, t.metrics_replies
        FROM tweet t
        WHERE t.id = ?
    """
    async with db.execute(sql, (tweet_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [d[0] for d in cursor.description] if cursor.description else []
        result = dict(zip(columns, row, strict=False))
    results = await _enrich_with_media(db, [result])
    return results[0]


async def list_tweets(
    db: aiosqlite.Connection,
    *,
    interaction_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
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
               t.reply_to_id, t.quoted_id, t.retweeted_id,
               t.metrics_likes, t.metrics_retweets, t.metrics_replies,
               i.type as interaction_type, i.timestamp as interaction_timestamp
        FROM tweet t
        LEFT JOIN latest_interaction li ON li.tweet_id = t.id
        LEFT JOIN interaction i ON i.id = li.interaction_id
    """
    if interaction_type:
        sql += " WHERE i.type IS NOT NULL"
    sql += """
        ORDER BY COALESCE(i.timestamp, t.created_at) DESC
        LIMIT ? OFFSET ?
    """
    params.append(limit)
    params.append(offset)

    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row, strict=False)) for row in rows]
    return await _enrich_with_media(db, results)


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
    offset: int = 0,
) -> list[SearchResult]:
    sql = """
        WITH RECURSIVE matching_base AS (
            SELECT t.id
            FROM tweet_fts f
            JOIN tweet t ON t.rowid = f.rowid
            WHERE tweet_fts MATCH ?
            UNION
            SELECT DISTINCT t.id
            FROM tweet t
            JOIN tweet_media tm ON tm.tweet_id = t.id
            JOIN media m ON m.id = tm.media_id
            JOIN media_fts mf ON mf.rowid = m.rowid
            WHERE media_fts MATCH ?
        ),
        matching_tweets(id) AS (
            SELECT id FROM matching_base
            UNION
            SELECT t.id
            FROM tweet t
            JOIN matching_tweets mt
                ON t.reply_to_id = mt.id
                OR t.quoted_id = mt.id
                OR t.retweeted_id = mt.id
        )
        SELECT t.id, t.author_id, t.author_handle, t.author_name, t.content, t.created_at,
               t.reply_to_id, t.quoted_id, t.retweeted_id,
               t.metrics_likes, t.metrics_retweets, t.metrics_replies,
               i.type as interaction_type, i.timestamp as interaction_timestamp
        FROM matching_tweets mt
        JOIN tweet t ON t.id = mt.id
        LEFT JOIN interaction i ON i.id = (
            SELECT id FROM interaction
            WHERE tweet_id = t.id
    """
    params: list[str | int] = [query, query]
    if interaction_type:
        sql += " AND type = ?"
        params.append(interaction_type)
    sql += """
            ORDER BY id DESC LIMIT 1
        )
    """
    if interaction_type:
        sql += " WHERE i.type IS NOT NULL"
    sql += """
        ORDER BY t.created_at DESC
        LIMIT ? OFFSET ?
    """
    params.append(limit)
    params.append(offset)

    async with db.execute(sql, params) as cursor:
        rows = await cursor.fetchall()
        columns = [d[0] for d in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row, strict=False)) for row in rows]
    return await _enrich_with_media(db, results)
