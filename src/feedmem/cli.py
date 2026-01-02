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


@main.command()
@click.argument("source", type=click.Choice(["likes", "bookmarks", "notifications", "profile"]))
@click.option("--limit", "max_items", default=0, help="Max items to fetch (0=unlimited)")
@click.option("--no-headless", is_flag=True, help="Show browser window")
@click.option("--full", is_flag=True, help="Full scrape (ignore known items)")
@click.option("-v", "--verbose", is_flag=True, help="Show progress during scrape")
@click.option("--with-replies", is_flag=True, help="Include replies (profile only)")
def scrape(
    source: str, max_items: int, no_headless: bool, full: bool, verbose: bool, with_replies: bool
) -> None:
    """Scrape likes, bookmarks, notifications, or profile from Twitter/X."""

    async def run() -> None:
        conn = await db.init_db()
        try:
            interaction_type = INTERACTION_TYPES[source]
            known_ids = None if full else await db.get_tweet_ids(conn, interaction_type)
            if source == "likes":
                tweets = await scraper.scrape_likes(
                    max_items=max_items,
                    headless=not no_headless,
                    known_ids=known_ids,
                    verbose=verbose,
                )
            elif source == "bookmarks":
                tweets = await scraper.scrape_bookmarks(
                    max_items=max_items,
                    headless=not no_headless,
                    known_ids=known_ids,
                    verbose=verbose,
                )
            elif source == "notifications":
                tweets = await scraper.scrape_notifications(
                    max_items=max_items,
                    headless=not no_headless,
                    known_ids=known_ids,
                    verbose=verbose,
                )
            else:
                tweets = await scraper.scrape_profile(
                    max_items=max_items,
                    headless=not no_headless,
                    known_ids=known_ids,
                    verbose=verbose,
                    include_replies=with_replies,
                )

            for tweet in reversed(tweets):
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
            click.echo(f"Saved {len(tweets)} new {source}")
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
