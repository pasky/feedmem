# feedmem

**Long-term memory for your social feeds.**

Archive your Twitter/X activity (likes, bookmarks, tweets, replies, notifications) and search it later—by keyword now, semantically in the future.

## Vision

- Ingest GDPR data exports, then continuously update from API or browser extension
- Key content: **likes**, **bookmarks**, notifications, your posts & replies
- Start with grep-like search, evolve to semantic/fuzzy search
- Future: parse images for visual semantic search

Example queries:
- "a few months ago I tweeted something about big humanity projects"
- "in past days I saw this meme about openai, list all I've liked"

## Status

🚧 **Early development** — architecture phase

## Usage

```bash
# Ingest initial GDPR dump
feedmem ingest /path/to/twitter-archive.zip

# Start continuous update service
feedmem update --daemon

# Search your archive
feedmem search "humanity projects"
```

## Development

```bash
uv sync
uv run ruff check .
uv run pyright
uv run pytest
```

## License

MIT
