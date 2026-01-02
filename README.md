# feedmem

**Long-term memory for your social feeds.**

Archive your Twitter/X activity (likes, bookmarks, tweets, replies, notifications) and search it later—by keyword now, semantically in the future.

## Features

- **Scrape likes & bookmarks** via headless browser (no API needed)
- **Import GDPR data exports** for your own tweets
- **Full-text search** with SQLite FTS5
- **Works on headless servers** via auth state import

## Installation

```bash
# Clone and install
git clone https://github.com/user/feedmem
cd feedmem
uv sync

# Install Playwright browser (one-time)
uv run playwright install firefox
```

## Quick Start

### Option A: Desktop machine (has display)

```bash
# Interactive login - opens browser window
feedmem login

# Scrape your likes
feedmem scrape likes

# Search
feedmem search "python"
```

### Option B: Import cookies (recommended for headless/bot-detection issues)

If `feedmem login` fails due to bot detection, export cookies from your real browser:

1. Log in to x.com in Chrome/Firefox normally
2. Install the [Cookie-Editor](https://cookie-editor.cgagnier.ca/) extension
3. On x.com, click Cookie-Editor → Export → Export as JSON
4. Save the file and import:
   ```bash
   feedmem login --cookies ~/Downloads/x.com_cookies.json
   ```

### Option C: Copy auth state to server

If login works locally but you need to scrape on a headless server:
   ```bash
   # Find where auth state is stored
   feedmem login --show-path
   # Usually: ~/.local/share/feedmem/auth_state.json

   # Copy to server (create dir first)
   ssh server 'mkdir -p ~/.local/share/feedmem'
   scp ~/.local/share/feedmem/auth_state.json server:~/.local/share/feedmem/
   ```

Now you can scrape:
   ```bash
   feedmem scrape likes
   feedmem scrape bookmarks
   ```

## Commands

```bash
# Authentication
feedmem login                              # Interactive browser login
feedmem login --cookies cookies.json       # Import cookies from Cookie-Editor
feedmem login --show-path                  # Show auth state path (for scp)

# Scraping (requires login first)
feedmem scrape likes                       # Scrape all your likes
feedmem scrape bookmarks                   # Scrape all bookmarks
feedmem scrape likes --limit 100           # Limit to 100 items
feedmem scrape likes --no-headless         # Show browser (for debugging)

# Import GDPR archive (your own tweets)
feedmem ingest archive.zip --username yourhandle

# Search
feedmem search "query"                     # Search all tweets
feedmem search "query" --type like         # Only liked tweets
feedmem search "query" --type bookmark     # Only bookmarks
feedmem search "query" --limit 20          # Limit results
```

## Data Storage

- Database: `~/.local/share/feedmem/feedmem.db` (SQLite)
- Auth state: `~/.local/share/feedmem/auth_state.json`

## Development

```bash
uv sync
uv run ruff check .
uv run pyright
uv run pytest
uv run pytest --cov=feedmem   # With coverage
```

## How It Works

Twitter's API free tier is write-only—you can't read your own likes or bookmarks. GDPR exports only contain tweet IDs for likes/bookmarks, not content.

feedmem uses Playwright to run a headless browser with your logged-in session, intercepting GraphQL responses to capture full tweet data as it scrolls through your likes/bookmarks pages.

## Roadmap

- [ ] Semantic search with embeddings
- [ ] Image OCR for meme search
- [ ] Chrome extension for live capture (particularly of what you see)

## License

MIT
