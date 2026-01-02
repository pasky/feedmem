"""Tests for CLI commands."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

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
        patch("feedmem.db.get_default_db_path", return_value=tmp_path / "test.db"),
    ):
        result = runner.invoke(
            main, ["ingest", str(archive_path), "--username", "testuser"]
        )
    assert result.exit_code == 0
    assert "Ingested 1 tweets" in result.output


def test_search_no_results(tmp_path: Path) -> None:
    runner = CliRunner()
    with patch("feedmem.db.get_default_db_path", return_value=tmp_path / "test.db"):
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
    with patch("feedmem.db.get_default_db_path", return_value=db_path):
        runner.invoke(main, ["ingest", str(archive_path), "--username", "pyuser"])
        result = runner.invoke(main, ["search", "python"])

    assert result.exit_code == 0
    assert "@pyuser" in result.output
    assert "Python" in result.output


def test_scrape_requires_auth(tmp_path: Path) -> None:
    runner = CliRunner()
    with (
        patch("feedmem.scraper.AUTH_STATE_PATH", tmp_path / "nonexistent.json"),
        patch("feedmem.db.get_default_db_path", return_value=tmp_path / "test.db"),
    ):
        result = runner.invoke(main, ["scrape", "likes"])
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "Not logged in" in str(result.exception)
