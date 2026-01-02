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
def login_cmd(show_path: bool) -> None:
    """Interactive browser login to Twitter/X."""
    if show_path:
        click.echo(scraper.get_auth_state_path())
        return
    asyncio.run(scraper.login_interactive())


@main.command()
@click.argument("source", type=click.Choice(["likes", "bookmarks"]))
@click.option("--max", "max_items", default=0, help="Max items to fetch (0=unlimited)")
@click.option("--no-headless", is_flag=True, help="Show browser window")
def scrape(source: str, max_items: int, no_headless: bool) -> None:
    """Scrape likes or bookmarks from Twitter/X."""

    async def run() -> None:
        conn = await db.init_db()
        try:
            if source == "likes":
                tweets = await scraper.scrape_likes(
                    max_items=max_items, headless=not no_headless
                )
            else:
                tweets = await scraper.scrape_bookmarks(
                    max_items=max_items, headless=not no_headless
                )

            for tweet in tweets:
                await db.upsert_tweet(
                    conn,
                    id=tweet["id"],
                    author_id=tweet["author_id"],
                    author_handle=tweet["author_handle"],
                    author_name=tweet["author_name"],
                    content=tweet["content"],
                    created_at=tweet["created_at"],
                    reply_to_id=tweet.get("reply_to_id"),
                    metrics_likes=tweet.get("metrics_likes"),
                    metrics_retweets=tweet.get("metrics_retweets"),
                    metrics_replies=tweet.get("metrics_replies"),
                    raw_json=tweet.get("raw_json"),
                )
                await db.add_interaction(
                    conn,
                    type=tweet["interaction_type"],
                    tweet_id=tweet["id"],
                    timestamp=tweet["interaction_timestamp"],
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
            click.echo(f"Scraped {len(tweets)} {source}")
        finally:
            await conn.close()

    asyncio.run(run())


@main.command()
@click.argument("query")
@click.option("--type", "interaction_type", type=click.Choice(["like", "bookmark"]))
@click.option("--limit", default=50, help="Max results")
def search(query: str, interaction_type: str | None, limit: int) -> None:
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
        itype = r.get("interaction_type", "")
        prefix = f"[{itype}] " if itype else ""
        click.echo(f"{prefix}@{r['author_handle']}: {r['content'][:100]}")
        click.echo(f"  https://x.com/{r['author_handle']}/status/{r['id']}")
        click.echo()


if __name__ == "__main__":
    main()
