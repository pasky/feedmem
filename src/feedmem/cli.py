"""CLI entry point for feedmem."""

import asyncio
from pathlib import Path

import click

from feedmem import db, gdpr, scraper


@click.group()
def main() -> None:
    """Long-term memory for your social feeds."""


@main.command()
@click.argument("archive_path", type=click.Path(exists=True, path_type=Path))
@click.option("--username", required=True, help="Your Twitter username (for author info)")
def ingest(archive_path: Path, username: str) -> None:
    """Ingest tweets from a Twitter GDPR archive zip."""

    async def run() -> int:
        conn = await db.init_db()
        try:
            tweets = gdpr.parse_archive(archive_path)
            for tweet in tweets:
                await db.upsert_tweet(
                    conn,
                    id=tweet["id"],
                    author_id=username,
                    author_handle=username,
                    author_name=username,
                    content=tweet["content"],
                    created_at=tweet["created_at"],
                    reply_to_id=tweet.get("reply_to_id"),
                    metrics_likes=tweet.get("metrics_likes"),
                    metrics_retweets=tweet.get("metrics_retweets"),
                    raw_json=tweet.get("raw_json"),
                )
                for media in tweet.get("media", []):
                    if media.get("id"):
                        await db.add_media(
                            conn,
                            id=media["id"],
                            tweet_id=tweet["id"],
                            url=media["url"],
                            mime_type=media.get("type"),
                        )
            return len(tweets)
        finally:
            await conn.close()

    count = asyncio.run(run())
    click.echo(f"Ingested {count} tweets from archive")


@main.command("login")
@click.option("--show-path", is_flag=True, help="Show auth state path (for scp to servers)")
@click.option(
    "--cookies",
    "cookies_file",
    type=click.Path(exists=True, path_type=Path),
    help="Import cookies from JSON file (Cookie-Editor extension format)",
)
def login_cmd(show_path: bool, cookies_file: Path | None) -> None:
    """Interactive browser login to Twitter/X, or import cookies."""
    if show_path:
        click.echo(scraper.get_auth_state_path())
        return
    if cookies_file:
        scraper.import_cookies_from_json(cookies_file)
        click.echo(f"Cookies imported from {cookies_file}")
        return
    asyncio.run(scraper.login_interactive())


INTERACTION_TYPES = {
    "likes": "like",
    "bookmarks": "bookmark",
    "notifications": "mention",
    "profile": "own",
}


SCRAPE_SOURCES = ["likes", "bookmarks", "notifications", "profile"]


async def _save_tweet(
    conn: db.aiosqlite.Connection,
    tweet: scraper.TweetData,
    interaction_type: str | None = None,
    interaction_timestamp: str | None = None,
    download_media: bool = False,
    verbose: bool = False,
) -> None:
    """Save a single tweet to db, optionally downloading media."""
    await db.upsert_tweet(
        conn,
        id=tweet["id"],
        author_id=tweet["author_id"],
        author_handle=tweet["author_handle"],
        author_name=tweet["author_name"],
        content=tweet["content"],
        created_at=tweet["created_at"],
        reply_to_id=tweet.get("reply_to_id"),
        quoted_id=tweet.get("quoted_id"),
        retweeted_id=tweet.get("retweeted_id"),
        metrics_likes=tweet.get("metrics_likes"),
        metrics_retweets=tweet.get("metrics_retweets"),
        metrics_replies=tweet.get("metrics_replies"),
        raw_json=tweet.get("raw_json"),
    )
    if interaction_type:
        await db.add_interaction(
            conn,
            type=interaction_type,
            tweet_id=tweet["id"],
            timestamp=interaction_timestamp or tweet["created_at"],
        )
    for media in tweet.get("media", []):
        if not media.get("id"):
            continue
        url = media.get("video_url") or media.get("url")
        local_path = None
        if download_media and url:
            if verbose:
                click.echo(f"  Downloading media {media['id']}...")
            path = await scraper.download_media(url, tweet["id"], media["id"])
            local_path = str(path) if path else None
        await db.add_media(
            conn,
            id=media["id"],
            tweet_id=tweet["id"],
            url=url or "",
            local_path=local_path,
            mime_type=media.get("type"),
        )


async def _scrape_referenced(
    conn: db.aiosqlite.Connection,
    tweet_ids: list[str],
    depth: int,
    headless: bool,
    download_media: bool,
    verbose: bool,
) -> int:
    """Recursively scrape referenced tweets. Returns count of newly scraped tweets."""
    if depth <= 0 or not tweet_ids:
        return 0

    all_known = await db.get_tweet_ids(conn)
    to_scrape = [tid for tid in tweet_ids if tid not in all_known]
    if not to_scrape:
        return 0

    if verbose:
        click.echo(f"  Scraping {len(to_scrape)} referenced tweets (depth={depth})...")

    count = 0
    next_refs: list[str] = []

    for tid in to_scrape:
        tweet = await scraper.scrape_tweet(tid, headless=headless)
        if tweet:
            await _save_tweet(conn, tweet, download_media=download_media, verbose=verbose)
            count += 1
            next_refs.extend(scraper.get_referenced_ids(tweet))
            if verbose:
                click.echo(f"    Scraped @{tweet['author_handle']}: {tweet['content'][:40]}...")

    if next_refs:
        count += await _scrape_referenced(
            conn, next_refs, depth - 1, headless, download_media, verbose
        )

    return count


async def _scrape_source(
    conn: db.aiosqlite.Connection,
    source: str,
    max_items: int,
    headless: bool,
    full: bool,
    verbose: bool,
    recursion_depth: int = 0,
    download_media: bool = False,
) -> tuple[scraper.ScrapeResult, int]:
    """Scrape a single source and save to db. Returns (scrape result, ref count)."""
    interaction_type = INTERACTION_TYPES[source]
    known_ids = None if full else await db.get_tweet_ids(conn, interaction_type)

    scrape_fn = {
        "likes": scraper.scrape_likes,
        "bookmarks": scraper.scrape_bookmarks,
        "notifications": scraper.scrape_notifications,
        "profile": scraper.scrape_profile,
    }[source]

    result = await scrape_fn(
        max_items=max_items,
        headless=headless,
        known_ids=known_ids,
        verbose=verbose,
    )

    all_refs: list[str] = []
    for tweet in reversed(result.tweets):
        await _save_tweet(
            conn,
            tweet,
            interaction_type=tweet["interaction_type"],
            interaction_timestamp=tweet.get("interaction_timestamp"),
            download_media=download_media,
            verbose=verbose,
        )
        all_refs.extend(scraper.get_referenced_ids(tweet))

    ref_count = 0
    if recursion_depth > 0 and all_refs:
        ref_count = await _scrape_referenced(
            conn, all_refs, recursion_depth, headless, download_media, verbose
        )

    return result, ref_count


@main.command()
@click.argument("source", type=click.Choice(SCRAPE_SOURCES + ["all"]))
@click.option("--limit", "max_items", default=100, help="Max items to fetch (0=unlimited)")
@click.option("--no-headless", is_flag=True, help="Show browser window")
@click.option("--full", is_flag=True, help="Full scrape (ignore known items)")
@click.option("-v", "--verbose", is_flag=True, help="Show progress during scrape")
@click.option(
    "--recursion",
    "recursion_depth",
    default=1,
    show_default=True,
    help="Depth for fetching referenced tweets (reply parents, quotes, RTs)",
)
@click.option("--download-media", is_flag=True, help="Download media files locally")
def scrape(
    source: str,
    max_items: int,
    no_headless: bool,
    full: bool,
    verbose: bool,
    recursion_depth: int,
    download_media: bool,
) -> None:
    """Scrape likes, bookmarks, notifications, profile, or all from Twitter/X."""
    sources = SCRAPE_SOURCES if source == "all" else [source]

    async def run() -> None:
        conn = await db.init_db()
        try:
            for src in sources:
                result, ref_count = await _scrape_source(
                    conn,
                    src,
                    max_items,
                    not no_headless,
                    full,
                    verbose,
                    recursion_depth=recursion_depth,
                    download_media=download_media,
                )
                msg = f"Saved {len(result.tweets)} new {src}"
                if ref_count:
                    msg += f" (+{ref_count} referenced)"
                click.echo(msg)
                if result.hit_limit:
                    click.echo(
                        f"WARNING: stopped at --limit={max_items}, there may be more new {src}",
                        err=True,
                    )
        finally:
            await conn.close()

    asyncio.run(run())


def _format_tweet(r: db.SearchResult, verbose: bool = False) -> str:
    """Format a tweet for display."""
    itype = r.get("interaction_type", "")
    prefix = f"[{itype}] " if itype else ""
    handle = r["author_handle"] or "unknown"
    name = r.get("author_name") or ""
    created = r.get("created_at", "")
    content = r["content"] if verbose else r["content"][:256]

    lines = [f"{prefix}@{handle}" + (f" ({name})" if name else "") + f" - {created}"]
    lines.append(content)
    lines.append(f"  https://x.com/{handle}/status/{r['id']}")

    metrics: list[str] = []
    if r.get("metrics_likes") is not None:
        metrics.append(f"♥ {r['metrics_likes']}")
    if r.get("metrics_retweets") is not None:
        metrics.append(f"🔁 {r['metrics_retweets']}")
    if r.get("metrics_replies") is not None:
        metrics.append(f"💬 {r['metrics_replies']}")
    if metrics:
        lines.append(f"  {' | '.join(metrics)}")

    if r.get("reply_to_id"):
        lines.append(f"  ↩ Reply to: https://x.com/i/status/{r['reply_to_id']}")
    if r.get("media_urls"):
        lines.append(f"  Media: {r['media_urls']}")
    return "\n".join(lines)


@main.command("list")
@click.option(
    "--type", "interaction_type", type=click.Choice(["like", "bookmark", "mention", "own"])
)
@click.option("--limit", default=50, help="Max results")
@click.option("-v", "--verbose", is_flag=True, help="Show full tweet text")
def list_cmd(interaction_type: str | None, limit: int, verbose: bool) -> None:
    """List your archived tweets."""

    async def run() -> list[db.SearchResult]:
        conn = await db.init_db()
        try:
            return await db.list_tweets(conn, interaction_type=interaction_type, limit=limit)
        finally:
            await conn.close()

    results = asyncio.run(run())
    if not results:
        click.echo("No tweets found.")
        return

    for r in results:
        click.echo(
            "--------------------------------------------------------------------------------"
        )
        click.echo(_format_tweet(r, verbose))
        click.echo()


@main.command()
@click.argument("query")
@click.option(
    "--type", "interaction_type", type=click.Choice(["like", "bookmark", "mention", "own"])
)
@click.option("--limit", default=50, help="Max results")
@click.option("-v", "--verbose", is_flag=True, help="Show full tweet text")
def search(query: str, interaction_type: str | None, limit: int, verbose: bool) -> None:
    """Search your archived tweets."""

    async def run() -> list[db.SearchResult]:
        conn = await db.init_db()
        try:
            return await db.search_tweets(
                conn, query, interaction_type=interaction_type, limit=limit
            )
        finally:
            await conn.close()

    results = asyncio.run(run())
    if not results:
        click.echo("No results found.")
        return

    for r in results:
        click.echo(_format_tweet(r, verbose))
        click.echo()


if __name__ == "__main__":
    main()
