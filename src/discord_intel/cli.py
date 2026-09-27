"""Command-line entry point for Discord Intel."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from discord_intel.config import load_settings
from discord_intel.db import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discord-intel",
        description="Index and search links shared in configured Discord channels.",
    )
    database_parser = parser.add_subparsers(dest="command")
    database_command = database_parser.add_parser("db", help="Database commands")
    database_actions = database_command.add_subparsers(dest="db_action", required=True)
    initialize_parser = database_actions.add_parser("init", help="Apply pending SQL migrations")
    initialize_parser.add_argument(
        "--database",
        type=Path,
        help="Database file path (defaults to DATABASE_PATH)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not arguments:
        parser.print_help()
        return 0
    parsed = parser.parse_args(arguments)
    if parsed.command == "db" and parsed.db_action == "init":
        database_path = parsed.database or load_settings().database_path
        asyncio.run(Database(database_path).initialize())
        print(f"Database initialized: {database_path}")
        return 0
    parser.print_help()
    return 0