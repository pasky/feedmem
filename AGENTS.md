# AGENTS.md

## Architecture
Twitter/X personal archive tool using Playwright for scraping (API is write-only on free tier).
- `src/feedmem/` - Main package: cli.py (Click CLI), db.py (SQLite+FTS5), scraper.py (Playwright), gdpr.py (archive parser)
- `tests/` - pytest-asyncio tests mirroring src structure
- Storage: SQLite with FTS5 for full-text search; tables: tweet, interaction, media, tweet_fts

## Code Style
- Python 3.13+, strict pyright typing, async/await throughout
- Ruff linting: E, F, I (isort), UP, B, SIM; 100 char line length
- Imports: stdlib → third-party → local, sorted by ruff
- Type hints required on all functions; use `collections.abc` for generic types
- Async fixtures use `@pytest_asyncio.fixture`, tests use `@pytest.mark.asyncio`
- Minimal docstrings; prefer self-documenting code
- Errors should be visible and fail loudly, no try/except pass

## Commands
- Run linting, typecheck etc. via pre-commit.
- Commit once your work is finished. Never use `git add -A` to avoid accidentally adding untracked files.
- Test all: `uv run pytest`
