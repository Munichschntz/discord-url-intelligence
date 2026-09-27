import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from discord_intel.cli import main
from discord_intel.config import Settings


def test_cli_without_arguments_displays_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: discord-intel" in capsys.readouterr().out


def test_discord_ids_remain_decimal_strings() -> None:
    settings = Settings(_env_file=None, discord_guild_id="123456789012345678")
    assert settings.discord_guild_id == "123456789012345678"


def test_web_visible_channels_must_be_allowlisted() -> None:
    with pytest.raises(ValidationError, match="Web-visible channels"):
        Settings(
            _env_file=None,
            allowed_source_channel_ids=["123"],
            web_visible_channel_ids=["456"],
        )


def test_oauth_redirect_requires_exact_https_callback() -> None:
    with pytest.raises(ValidationError, match="exact HTTPS"):
        Settings(_env_file=None, discord_oauth_redirect_uri="http://localhost/callback")


def test_web_and_mcp_must_bind_loopback() -> None:
    with pytest.raises(ValidationError, match="loopback"):
        Settings(_env_file=None, mcp_host="0.0.0.0")


def test_db_init_cli_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database_path = tmp_path / "cli.sqlite3"
    arguments = ["db", "init", "--database", str(database_path)]

    assert main(arguments) == 0
    assert main(arguments) == 0

    with sqlite3.connect(database_path) as connection:
        applied = connection.execute("SELECT count(*) FROM schema_migrations").fetchone()
    assert applied == (1,)
    assert "Database initialized" in capsys.readouterr().out