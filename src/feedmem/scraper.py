"""Playwright-based scraper for Twitter/X."""

import asyncio
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Route, async_playwright

AUTH_STATE_PATH = Path.home() / ".local" / "share" / "feedmem" / "auth_state.json"
TWITTER_URL = "https://x.com"


def parse_twitter_timestamp(ts: str) -> str:
    """Convert Twitter timestamp to ISO format. Returns original if parsing fails."""
    if not ts:
        return ts
    try:
        dt = datetime.strptime(ts, "%a %b %d %H:%M:%S %z %Y")
        return dt.isoformat()
    except ValueError:
        return ts


async def login_interactive() -> None:
    """Open browser for interactive login, save auth state."""
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Firefox tends to work better with Twitter's bot detection
        browser = await p.firefox.launch(headless=False)

        # Use a real device profile for consistent fingerprint
        devices: dict[str, Any] = p.devices  # type: ignore[assignment]
        device: dict[str, Any] = devices["Desktop Firefox"]
        context = await browser.new_context(**device)
        page = await context.new_page()

        await page.goto(f"{TWITTER_URL}/login")
        print("Please log in to Twitter/X in the browser window.")
        print("Take your time - type slowly, don't paste.")
        print("Press Enter here when you're logged in and see your home feed...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.storage_state(path=str(AUTH_STATE_PATH))
        print(f"Auth state saved to {AUTH_STATE_PATH}")
        await browser.close()


def get_auth_state_path() -> Path:
    """Return path where auth state is stored."""
    return AUTH_STATE_PATH


def import_cookies_from_json(cookies_file: Path) -> None:
    """Import cookies from browser extension export (Cookie-Editor JSON format)."""
    import json as json_module

    cookies = json_module.loads(cookies_file.read_text())

    # Convert Cookie-Editor format to Playwright format
    playwright_cookies: list[dict[str, Any]] = []
    for c in cookies:
        cookie: dict[str, Any] = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".x.com"),
            "path": c.get("path", "/"),
        }
        if "expirationDate" in c:
            cookie["expires"] = c["expirationDate"]
        if c.get("secure"):
            cookie["secure"] = True
        if c.get("httpOnly"):
            cookie["httpOnly"] = True
        if c.get("sameSite"):
            same_site = c["sameSite"].lower()
            if same_site == "no_restriction":
                cookie["sameSite"] = "None"
            elif same_site in ("strict", "lax"):
                cookie["sameSite"] = same_site.capitalize()
            # Skip invalid/unknown values
        playwright_cookies.append(cookie)

    # Create Playwright storage state format
    state: dict[str, Any] = {
        "cookies": playwright_cookies,
        "origins": [],
    }

    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STATE_PATH.write_text(json_module.dumps(state, indent=2))


def has_auth_state() -> bool:
    return AUTH_STATE_PATH.exists()


async def check_auth(headless: bool = True) -> str:
    """Verify the saved auth state works; return the logged-in username.

    Raises RuntimeError if not logged in, or PlaywrightError on timeout
    (session expired / invalid).
    """
    if not has_auth_state():
        raise RuntimeError("Not logged in. Run 'feedmem login' first.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = await context.new_page()
        try:
            return await _get_username(page)
        finally:
            await browser.close()


TweetData = dict[str, Any]


class ScrapeResult:
    """Result of a scrape operation."""

    def __init__(self, tweets: list[TweetData], stop_reason: str) -> None:
        self.tweets = tweets
        self.stop_reason = stop_reason

    @property
    def hit_limit(self) -> bool:
        return self.stop_reason.startswith("reached limit")


def _extract_tweet_result(result: dict[str, Any]) -> TweetData | None:
    """Parse tweet data from a GraphQL tweet result object."""
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    if not result or result.get("__typename") != "Tweet":
        return None

    legacy = result.get("legacy", {})
    core = result.get("core", {})
    user_results = core.get("user_results", {}).get("result", {})
    user_legacy = user_results.get("legacy", {})
    user_core = user_results.get("core", {})

    tweet_id = result.get("rest_id")
    if not tweet_id:
        return None

    quoted_id = None
    quoted_result = result.get("quoted_status_result", {}).get("result", {})
    if quoted_result:
        qt = quoted_result
        if qt.get("__typename") == "TweetWithVisibilityResults":
            qt = qt.get("tweet", {})
        quoted_id = qt.get("rest_id")

    retweeted_id = legacy.get("retweeted_status_result", {}).get("result", {}).get("rest_id")
    if not retweeted_id:
        rt_result = legacy.get("retweeted_status_result", {}).get("result", {})
        if rt_result.get("__typename") == "TweetWithVisibilityResults":
            retweeted_id = rt_result.get("tweet", {}).get("rest_id")

    media_list: list[dict[str, Any]] = []
    for m in legacy.get("extended_entities", {}).get("media", []):
        media_entry: dict[str, Any] = {
            "id": m.get("id_str", ""),
            "url": m.get("media_url_https", ""),
            "type": m.get("type", ""),
        }
        if m.get("type") == "video" or m.get("type") == "animated_gif":
            variants = m.get("video_info", {}).get("variants", [])
            best = max(
                (v for v in variants if v.get("content_type") == "video/mp4"),
                key=lambda v: v.get("bitrate", 0),
                default=None,
            )
            if best:
                media_entry["video_url"] = best.get("url")
        media_list.append(media_entry)

    return {
        "id": tweet_id,
        "author_id": user_results.get("rest_id", ""),
        "author_handle": user_core.get("screen_name") or user_legacy.get("screen_name", ""),
        "author_name": user_core.get("name") or user_legacy.get("name", ""),
        "content": html.unescape(legacy.get("full_text", "")),
        "created_at": parse_twitter_timestamp(legacy.get("created_at", "")),
        "reply_to_id": legacy.get("in_reply_to_status_id_str"),
        "quoted_id": quoted_id,
        "retweeted_id": retweeted_id,
        "metrics_likes": legacy.get("favorite_count"),
        "metrics_retweets": legacy.get("retweet_count"),
        "metrics_replies": legacy.get("reply_count"),
        "media": media_list,
        "raw_json": json.dumps(result),
    }


def _extract_tweet_from_items(items: list[dict[str, Any]]) -> TweetData | None:
    """Select the most relevant tweet from a conversation thread."""
    tweets: list[TweetData] = []
    for item in items:
        item_content = item.get("item", {}).get("itemContent") or item.get("itemContent")
        if not item_content:
            continue
        tweet_results = item_content.get("tweet_results", {})
        result = tweet_results.get("result", {})
        tweet = _extract_tweet_result(result)
        if tweet:
            tweets.append(tweet)

    if not tweets:
        return None

    reply_tweets = [tweet for tweet in tweets if tweet.get("reply_to_id")]
    return reply_tweets[0] if reply_tweets else tweets[0]


def parse_tweet_from_graphql(entry: dict[str, Any]) -> TweetData | None:
    """Extract tweet data from Twitter's GraphQL response format."""
    try:
        content = entry.get("content", {})
        item_content = content.get("itemContent")

        # Handle conversation thread entries (replies appear this way)
        if item_content is None and "items" in content:
            return _extract_tweet_from_items(content.get("items", []))

        if not item_content:
            return None

        # Handle notification entries (content.itemContent.notification.tweet.tweet_results)
        notification = item_content.get("notification", {})
        if notification:
            tweet_results = notification.get("tweet", {}).get("tweet_results", {})
        else:
            tweet_results = item_content.get("tweet_results", {})
        result = tweet_results.get("result", {})

        return _extract_tweet_result(result)
    except (KeyError, TypeError):
        return None


def extract_instructions_user_timeline(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract instructions from user timeline responses (Likes, UserTweets, etc.)."""
    return (
        data.get("data", {})
        .get("user", {})
        .get("result", {})
        .get("timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )


def extract_instructions_bookmarks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract instructions from bookmarks response."""
    return (
        data.get("data", {})
        .get("bookmark_timeline_v2", {})
        .get("timeline", {})
        .get("instructions", [])
    )


def extract_instructions_notifications(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract instructions from notifications response."""
    return (
        data.get("data", {})
        .get("viewer_v2", {})
        .get("user_results", {})
        .get("result", {})
        .get("notification_timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )


class TweetCollector:
    """Collects tweets from intercepted GraphQL responses."""

    STOP_AFTER_CONSECUTIVE_KNOWN = 10

    def __init__(
        self,
        interaction_type: str,
        known_ids: set[str] | None = None,
        verbose: bool = False,
        extractor: str = "user_timeline",
        skip: int = 0,
    ) -> None:
        self.tweets: list[TweetData] = []
        self.interaction_type = interaction_type
        self._seen_ids: set[str] = set()
        self._known_ids: set[str] = known_ids or set()
        self._consecutive_known: int = 0
        self.should_stop: bool = False
        self._verbose = verbose
        self._extractor = extractor
        self._skip = skip
        self._skipped: int = 0

    @property
    def consecutive_known(self) -> int:
        return self._consecutive_known

    async def handle_response(self, route: Route) -> None:
        try:
            response = await route.fetch()
            try:
                body = await response.json()
                self.extract_tweets(body)
            except (json.JSONDecodeError, ValueError):
                pass
            await route.fulfill(response=response)
        except PlaywrightError as e:
            if "disposed" not in str(e) and "already handled" not in str(e):
                raise

    def extract_tweets(self, data: dict[str, Any]) -> None:
        if self._extractor == "bookmarks":
            instructions = extract_instructions_bookmarks(data)
        elif self._extractor == "notifications":
            instructions = extract_instructions_notifications(data)
        else:
            instructions = extract_instructions_user_timeline(data)

        for instruction in instructions:
            entries = instruction.get("entries", [])
            for entry in entries:
                tweet = parse_tweet_from_graphql(entry)
                if tweet and tweet["id"] not in self._seen_ids:
                    self._seen_ids.add(tweet["id"])
                    if self._skipped < self._skip:
                        self._skipped += 1
                        if self._verbose:
                            handle = tweet["author_handle"]
                            preview = tweet["content"][:50]
                            print(f"  [skip {self._skipped}/{self._skip}] @{handle}: {preview}...")
                        continue
                    if tweet["id"] in self._known_ids:
                        self._consecutive_known += 1
                        if self._verbose:
                            handle = tweet["author_handle"]
                            preview = tweet["content"][:50]
                            count = f"{self._consecutive_known}/{self.STOP_AFTER_CONSECUTIVE_KNOWN}"
                            print(f"  [known] @{handle}: {preview}... ({count})")
                        if self._consecutive_known >= self.STOP_AFTER_CONSECUTIVE_KNOWN:
                            self.should_stop = True
                        continue
                    self._consecutive_known = 0
                    tweet["interaction_type"] = self.interaction_type
                    if self.interaction_type in ("like", "bookmark"):
                        tweet["interaction_timestamp"] = datetime.now().isoformat()
                    else:
                        tweet["interaction_timestamp"] = tweet["created_at"]
                    self.tweets.append(tweet)
                    if self._verbose:
                        handle = tweet["author_handle"]
                        preview = tweet["content"][:50]
                        print(f"  [new #{len(self.tweets)}] @{handle}: {preview}...")


async def scrape_likes(
    max_items: int = 0,
    headless: bool = True,
    scroll_delay_ms: int = 2000,
    known_ids: set[str] | None = None,
    verbose: bool = False,
    skip: int = 0,
) -> ScrapeResult:
    """Scrape liked tweets from Twitter/X."""
    return await _scrape_timeline(
        endpoint_pattern="**/Likes?*",
        url_path="/likes",
        interaction_type="like",
        max_items=max_items,
        headless=headless,
        scroll_delay_ms=scroll_delay_ms,
        known_ids=known_ids,
        verbose=verbose,
        skip=skip,
    )


async def scrape_bookmarks(
    max_items: int = 0,
    headless: bool = True,
    scroll_delay_ms: int = 2000,
    known_ids: set[str] | None = None,
    verbose: bool = False,
    skip: int = 0,
) -> ScrapeResult:
    """Scrape bookmarked tweets from Twitter/X."""
    return await _scrape_timeline(
        endpoint_pattern="**/Bookmarks?*",
        url_path="/i/bookmarks",
        interaction_type="bookmark",
        max_items=max_items,
        headless=headless,
        scroll_delay_ms=scroll_delay_ms,
        known_ids=known_ids,
        verbose=verbose,
        extractor="bookmarks",
        skip=skip,
    )


async def scrape_notifications(
    max_items: int = 0,
    headless: bool = True,
    scroll_delay_ms: int = 2000,
    known_ids: set[str] | None = None,
    verbose: bool = False,
    skip: int = 0,
) -> ScrapeResult:
    """Scrape notifications (mentions/replies to you) from Twitter/X."""
    return await _scrape_timeline(
        endpoint_pattern="**/NotificationsTimeline?*",
        url_path="/notifications/mentions",
        interaction_type="mention",
        max_items=max_items,
        headless=headless,
        scroll_delay_ms=scroll_delay_ms,
        known_ids=known_ids,
        verbose=verbose,
        extractor="notifications",
        skip=skip,
    )


async def scrape_profile(
    max_items: int = 0,
    headless: bool = True,
    scroll_delay_ms: int = 2000,
    known_ids: set[str] | None = None,
    verbose: bool = False,
    skip: int = 0,
) -> ScrapeResult:
    """Scrape your own posts and replies from Twitter/X."""
    return await _scrape_timeline(
        endpoint_pattern="**/UserTweetsAndReplies?*",
        url_path="/PROFILE/with_replies",
        interaction_type="own",
        max_items=max_items,
        headless=headless,
        scroll_delay_ms=scroll_delay_ms,
        known_ids=known_ids,
        verbose=verbose,
        skip=skip,
    )


async def _scrape_timeline(
    endpoint_pattern: str,
    url_path: str,
    interaction_type: str,
    max_items: int,
    headless: bool,
    scroll_delay_ms: int,
    known_ids: set[str] | None = None,
    verbose: bool = False,
    extractor: str = "user_timeline",
    skip: int = 0,
) -> ScrapeResult:
    """Generic timeline scraper using GraphQL interception."""
    if not has_auth_state():
        raise RuntimeError("Not logged in. Run 'feedmem login' first.")

    if verbose:
        known_count = len(known_ids) if known_ids else 0
        print(f"Starting {interaction_type} scrape (known: {known_count} items, skip: {skip})")

    collector = TweetCollector(
        interaction_type, known_ids=known_ids, verbose=verbose, extractor=extractor, skip=skip
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = await context.new_page()

        await page.route(endpoint_pattern, collector.handle_response)

        username = await _get_username(page)
        if url_path == "/likes":
            url_path = f"/{username}/likes"
        elif "/PROFILE" in url_path:
            url_path = url_path.replace("/PROFILE", f"/{username}")

        await page.goto(f"{TWITTER_URL}{url_path}")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        prev_count = 0
        stale_rounds = 0
        stop_reason = "unknown"
        while True:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(scroll_delay_ms)

            current_count = len(collector.tweets)
            if max_items > 0 and current_count >= max_items:
                stop_reason = f"reached limit ({max_items})"
                break
            if collector.should_stop:
                stop_reason = "hit consecutive known items"
                break
            if current_count == prev_count:
                stale_rounds += 1
                if stale_rounds >= 3:
                    stop_reason = "no new items (end of list)"
                    break
            else:
                stale_rounds = 0
            prev_count = current_count

        if verbose:
            print(f"Scrape finished: {stop_reason}, collected {len(collector.tweets)} new items")

        await page.unroute(endpoint_pattern)
        await page.close()
        await browser.close()

    tweets = collector.tweets[:max_items] if max_items > 0 else collector.tweets
    return ScrapeResult(tweets, stop_reason)


async def _get_username(page: Page) -> str:
    """Get current logged-in username from page."""
    max_attempts = 5
    base_delay = 10.0

    for attempt in range(max_attempts):
        try:
            await page.goto(f"{TWITTER_URL}/home")
            profile_link = page.locator('a[data-testid="AppTabBar_Profile_Link"]')
            await profile_link.wait_for(timeout=15000)
            href = await profile_link.get_attribute("href")
            if href:
                return href.strip("/")
        except PlaywrightError as e:
            if "Timeout" not in str(e) or attempt == max_attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            print(f"Timeout getting username, retry in {delay:.0f}s ({attempt + 1}/{max_attempts})")
            await asyncio.sleep(delay)

    raise RuntimeError("Could not determine username")


MEDIA_DIR = Path.home() / ".local" / "share" / "feedmem" / "media"


def get_media_dir() -> Path:
    """Return the directory where media files are stored."""
    return MEDIA_DIR


async def download_media(
    url: str,
    media_id: str,
) -> Path | None:
    """Download media file and return local path. Returns None on failure."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(url)
    ext = Path(parsed.path).suffix or ".jpg"
    ext = re.sub(r"\?.*", "", ext)
    local_path = MEDIA_DIR / f"{media_id}{ext}"

    if local_path.exists():
        return local_path

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            local_path.write_bytes(resp.content)
        return local_path
    except httpx.HTTPError:
        return None


class TweetDetailCollector:
    """Collects tweet data from TweetDetail GraphQL responses."""

    def __init__(self) -> None:
        self.tweet: TweetData | None = None

    async def handle_response(self, route: Route) -> None:
        try:
            response = await route.fetch()
            try:
                body = await response.json()
                self.extract(body)
            except (json.JSONDecodeError, ValueError):
                pass
            await route.fulfill(response=response)
        except PlaywrightError as e:
            if "disposed" not in str(e) and "already handled" not in str(e):
                raise

    def extract(self, data: dict[str, Any]) -> None:
        instructions = data.get("data", {}).get("tweetResult", {}).get("result", {})
        if instructions and instructions.get("__typename") == "Tweet":
            self.tweet = _extract_tweet_result(instructions)
            return

        instructions = (
            data.get("data", {})
            .get("threaded_conversation_with_injections_v2", {})
            .get("instructions", [])
        )
        for inst in instructions:
            for entry in inst.get("entries", []):
                content = entry.get("content", {})
                item_content = content.get("itemContent", {})
                result = item_content.get("tweet_results", {}).get("result", {})
                if result:
                    tweet = _extract_tweet_result(result)
                    if tweet:
                        self.tweet = tweet
                        return


async def scrape_tweet(
    tweet_id: str,
    headless: bool = True,
) -> TweetData | None:
    """Scrape a single tweet by ID. Returns tweet data or None if not found."""
    if not has_auth_state():
        raise RuntimeError("Not logged in. Run 'feedmem login' first.")

    collector = TweetDetailCollector()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = await context.new_page()

        await page.route("**/TweetDetail?*", collector.handle_response)
        await page.route("**/TweetResultByRestId?*", collector.handle_response)

        await page.goto(f"{TWITTER_URL}/i/status/{tweet_id}")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        await page.unroute("**/TweetDetail?*")
        await page.unroute("**/TweetResultByRestId?*")
        await page.close()
        await browser.close()

    return collector.tweet


def get_referenced_ids(tweet: TweetData) -> list[str]:
    """Get list of tweet IDs referenced by this tweet (reply parent, quote, RT)."""
    refs: list[str] = []
    if tweet.get("reply_to_id"):
        refs.append(tweet["reply_to_id"])
    if tweet.get("quoted_id"):
        refs.append(tweet["quoted_id"])
    if tweet.get("retweeted_id"):
        refs.append(tweet["retweeted_id"])
    return refs


TCO_PATTERN = re.compile(r"https://t\.co/\w+")


async def unfurl_url(url: str, timeout: float = 10.0) -> str | None:
    """Resolve a shortened URL to its final destination. Returns None on failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.head(url)
            return str(resp.url)
    except httpx.HTTPError:
        return None


async def unfurl_content(content: str) -> str:
    """Replace all t.co URLs in content with their resolved destinations."""
    urls = TCO_PATTERN.findall(content)
    if not urls:
        return content

    resolved: dict[str, str] = {}
    for url in set(urls):
        final = await unfurl_url(url)
        if final and final != url:
            resolved[url] = final

    result = content
    for short, full in resolved.items():
        result = result.replace(short, full)
    return result
