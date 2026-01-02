# feedmem Architecture

## Existing Solutions & Critique

### Similar Tools

| Tool | What it does | Limitations |
|------|-------------|-------------|
| **[tweetback](https://github.com/tweetback/tweetback)** | Eleventy-based static site from Twitter archive | Static output only, no search, no continuous updates, no likes/bookmarks |
| **[twitter-web-exporter](https://github.com/prinsss/twitter-web-exporter)** | Userscript to export tweets/bookmarks from browser | Export-only, no storage/search, requires manual scrolling |
| **[semiphemeral](https://github.com/micahflee/semiphemeral)** | Archive + selective deletion of tweets | Focused on deletion, archived, API-dependent |
| **[twitter-archiver](https://github.com/dariusk/twitter-archiver)** | Generate searchable static HTML from archive | Static site, no continuous updates |
| **[ArchiveBox](https://github.com/ArchiveBox/ArchiveBox)** | General web archiving | URL-based, not Twitter-native, no GDPR import |

### Gap feedmem fills

- **Continuous archiving**: Not just a one-time dump, but ongoing capture
- **Unified search**: Across likes, bookmarks, tweets, replies, notifications
- **Semantic search** (planned): Find by meaning, not just keywords
- **Image understanding** (planned): OCR/vision models for meme search
- **Feed-agnostic** (future): Modular to support Bluesky, Mastodon, etc.

---

## Key Architectural Questions

### 1. Storage Backend

**Options:**
- **SQLite** - Simple, single-file, good for personal use, FTS5 for search
- **PostgreSQL** - More scalable, better for hosted/multi-user future
- **DuckDB** - Columnar, good for analytics, embedded

**Recommendation:** Start with **SQLite + FTS5**. Single file, zero config, Python stdlib. Migrate path to Postgres if needed.

### 2. Data Model

```
Tweet/Post
├── id (platform-specific)
├── author_id, author_handle
├── content (text)
├── created_at
├── media[] (urls, local paths)
├── metrics (likes, retweets, etc.)
├── reply_to_id
└── thread_id

Interaction
├── id
├── type (like, bookmark, retweet, reply, mention, notification)
├── tweet_id
├── timestamp
└── metadata (json)

Media
├── id
├── tweet_id
├── url
├── local_path
├── mime_type
├── extracted_text (OCR)
└── embedding (vector, for semantic search)
```

### 3. GDPR Archive Format

Twitter archive structure:
```
data/
├── tweets.js           # Your tweets
├── like.js             # Liked tweet IDs (not full content!)
├── bookmark.js         # Bookmarked tweet IDs  
├── direct-messages.js  # DMs
├── follower.js / following.js
└── ...
```

**Challenge:** `like.js` only contains tweet IDs, not content. Need to hydrate via API or accept partial data.

### 4. Data Ingestion Pipeline

```
┌─────────────────┐
│  GDPR Archive   │ ──────────────────┐
└─────────────────┘                   │
                                      ▼
┌─────────────────┐              ┌─────────┐      ┌──────────┐
│  API Polling    │ ────────────▶│ Ingest  │─────▶│ Database │
└─────────────────┘              │ Layer   │      └──────────┘
                                 └─────────┘           │
┌─────────────────┐                   ▲                │
│ Browser Ext.    │ ──────────────────┘                ▼
│ (future)        │                              ┌──────────┐
└─────────────────┘                              │  Search  │
                                                 │  Index   │
                                                 └──────────┘
```

### 5. Update Strategy

**Options:**
- **API polling**: Use Twitter API (rate limited, requires dev account)
- **Browser extension**: Intercept XHR, capture everything you see
- **Hybrid**: API for owned content, extension for feed

**Recommendation:** Start with **API polling** for your own likes/bookmarks/tweets. Extension is Phase 2.

### 6. Search Architecture

**Phase 1 (MVP):** SQLite FTS5
- Full-text search on tweet content
- Filter by type, date range, author

**Phase 2:** Semantic search
- Embed tweets with sentence-transformers
- Store vectors in sqlite-vec or ChromaDB
- Hybrid: keyword + semantic ranking

**Phase 3:** Multimodal
- OCR on images (Tesseract or cloud API)
- CLIP embeddings for image search

### 7. CLI Design

```bash
# Ingest
feedmem ingest <archive.zip>           # GDPR dump
feedmem ingest --source twitter-api    # Fetch from API

# Update service
feedmem update                         # One-shot update
feedmem update --daemon --interval 1h  # Continuous

# Search
feedmem search "openai meme"           # Keyword
feedmem search "openai meme" --type like --since 7d
feedmem search --semantic "that tweet about humanity projects"  # Phase 2

# Export
feedmem export --format json --since 30d
```

---

## Discussion Points

1. **API access**: Do you have Twitter API credentials? Free tier is very limited now.

2. **Likes hydration**: GDPR dump has only like IDs. Options:
   - Accept partial data (just IDs)
   - Hydrate via API (rate limits)
   - Browser extension captures full content

3. **Media storage**: Download images/videos locally or just store URLs?

4. **Multi-account**: Support multiple Twitter accounts?

5. **Privacy**: This is personal data. Local-only or cloud sync option?

6. **Semantic search priority**: How soon do you want fuzzy/semantic? Adds dependencies (torch, transformers).

---

## Proposed Initial Scope (MVP)

1. ✅ Project setup (done)
2. GDPR archive parser (tweets.js, like.js, bookmark.js)
3. SQLite schema + FTS5 index
4. `feedmem ingest` command
5. `feedmem search` command (keyword)
6. Basic `feedmem update` (if API available)

Dependencies: just `click` for CLI, stdlib for the rest.
