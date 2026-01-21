"""Tests for CLI commands."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from feedmem.cli import main


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Long-term memory" in result.output


def test_login_show_path() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["login", "--show-path"])
    assert result.exit_code == 0
    assert "auth_state.json" in result.output


def test_ingest_command(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "123",
                "full_text": "Test tweet",
                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
            }
        }
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    runner = CliRunner()
    with (
        runner.isolated_filesystem(temp_dir=tmp_path),
        patch("feedmem.db.get_default_db_path", return_value=Path(":memory:")),
    ):
        result = runner.invoke(main, ["ingest", str(archive_path), "--username", "testuser"])
    assert result.exit_code == 0
    assert "Processed 1 tweets" in result.output
    assert "1 inserted" in result.output


def test_ingest_dry_run(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "dry1",
                "full_text": "Dry run test",
                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
            }
        },
        {
            "tweet": {
                "id_str": "dry2",
                "full_text": "Another tweet",
                "created_at": "Mon Jan 01 13:00:00 +0000 2024",
            }
        },
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    runner = CliRunner()
    with (
        runner.isolated_filesystem(temp_dir=tmp_path),
        patch("feedmem.db.get_default_db_path", return_value=Path(":memory:")),
    ):
        result = runner.invoke(
            main, ["ingest", str(archive_path), "--username", "testuser", "--dry-run"]
        )
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "2 new tweets" in result.output


def test_ingest_limit(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": f"lim{i}",
                "full_text": f"Tweet {i}",
                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
            }
        }
        for i in range(10)
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    runner = CliRunner()
    with (
        runner.isolated_filesystem(temp_dir=tmp_path),
        patch("feedmem.db.get_default_db_path", return_value=Path(":memory:")),
    ):
        result = runner.invoke(
            main, ["ingest", str(archive_path), "--username", "testuser", "--limit", "3"]
        )
    assert result.exit_code == 0
    assert "Processed 3 tweets" in result.output
    assert "3 inserted" in result.output


def test_ingest_skips_existing(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "existing_id",
                "full_text": "GDPR version",
                "created_at": "Mon Jan 01 12:00:00 +0000 2024",
            }
        }
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    runner = CliRunner()
    db_path = tmp_path / "skip_test.db"
    with patch("feedmem.cli.db.init_db") as mock_init:
        import aiosqlite

        from feedmem.db import SCHEMA, upsert_tweet

        async def init_with_existing(path: Path | None = None) -> aiosqlite.Connection:
            conn = await aiosqlite.connect(path or db_path)
            await conn.execute("PRAGMA synchronous = OFF")
            await conn.executescript(SCHEMA)
            # Pre-insert a tweet with richer data
            await upsert_tweet(
                conn,
                id="existing_id",
                author_id="rich_author",
                author_handle="rich_handle",
                content="Rich scraped version",
                created_at="2024-01-01T12:00:00+00:00",
            )
            await conn.commit()
            return conn

        mock_init.side_effect = init_with_existing
        result = runner.invoke(main, ["ingest", str(archive_path), "--username", "testuser"])

    assert result.exit_code == 0
    assert "1 skipped" in result.output


def test_search_no_results() -> None:
    runner = CliRunner()
    with patch("feedmem.db.get_default_db_path", return_value=Path(":memory:")):
        result = runner.invoke(main, ["search", "nonexistent"])
    assert result.exit_code == 0
    assert "No results found" in result.output


def test_search_with_results(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "456",
                "full_text": "Python is great for scripting",
                "created_at": "Tue Jan 02 10:00:00 +0000 2024",
            }
        }
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    runner = CliRunner()
    db_path = tmp_path / "search_test.db"
    with patch("feedmem.cli.db.init_db") as mock_init:
        import aiosqlite

        from feedmem.db import SCHEMA

        async def fast_init(path: Path | None = None) -> aiosqlite.Connection:
            conn = await aiosqlite.connect(path or db_path)
            await conn.execute("PRAGMA synchronous = OFF")
            await conn.executescript(SCHEMA)
            await conn.commit()
            return conn

        mock_init.side_effect = fast_init
        runner.invoke(main, ["ingest", str(archive_path), "--username", "pyuser"])
        result = runner.invoke(main, ["search", "python"])

    assert result.exit_code == 0
    assert "@pyuser" in result.output
    assert "Python" in result.output


@pytest.mark.parametrize("source", ["likes", "all"])
def test_scrape_requires_auth(tmp_path: Path, source: str) -> None:
    runner = CliRunner()
    with (
        patch("feedmem.scraper.AUTH_STATE_PATH", tmp_path / "nonexistent.json"),
        patch("feedmem.db.get_default_db_path", return_value=Path(":memory:")),
    ):
        result = runner.invoke(main, ["scrape", source])
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "Not logged in" in str(result.exception)


def test_list_multiline_tweet(tmp_path: Path) -> None:
    archive_path = tmp_path / "archive.zip"
    tweets_data = [
        {
            "tweet": {
                "id_str": "789",
                "full_text": "Line one\nLine two\nLine three",
                "created_at": "Wed Jan 03 10:00:00 +0000 2024",
            }
        }
    ]
    js_content = f"window.YTD.tweets.part0 = {json.dumps(tweets_data)}"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/tweets.js", js_content)

    runner = CliRunner()
    db_path = tmp_path / "multiline_test.db"
    with patch("feedmem.cli.db.init_db") as mock_init:
        import aiosqlite

        from feedmem.db import SCHEMA

        async def fast_init(path: Path | None = None) -> aiosqlite.Connection:
            conn = await aiosqlite.connect(path or db_path)
            await conn.execute("PRAGMA synchronous = OFF")
            await conn.executescript(SCHEMA)
            await conn.commit()
            return conn

        mock_init.side_effect = fast_init
        runner.invoke(main, ["ingest", str(archive_path), "--username", "testuser"])
        result = runner.invoke(main, ["list", "--limit", "1"])

    assert result.exit_code == 0
    assert "Line one\nLine two\nLine three" in result.output
