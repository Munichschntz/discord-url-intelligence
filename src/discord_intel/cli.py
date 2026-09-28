"""Command-line entry point for Discord Intel."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from discord_intel.config import Settings, load_settings
from discord_intel.db import Database
from discord_intel.discord import DiscordCollector
from discord_intel.ingest import IngestionService
from discord_intel.topics import TopicService


async def _preview_topics(
    settings: Settings, category: str | None, member_view: bool, limit: int, offset: int
) -> str:
    database = Database(settings.database_path)
    service = TopicService(database, settings)
    await database.initialize()
    read = service.member_links if member_view else service.owner_links
    page = await read(category, limit=limit, offset=offset)
    return json.dumps(asdict(page), indent=2, ensure_ascii=True)


async def _run_collector(settings: Settings, backfill_channel_id: str | None = None) -> int | None:
    database = Database(settings.database_path)
    await database.initialize()
    collector = DiscordCollector(
        settings,
        IngestionService(database, settings),
        backfill_channel_id=backfill_channel_id,
    )
    try:
        return await collector.run_bot()
    finally:
        await collector.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discord-intel",
        description="Index and search links shared in configured Discord channels.",
    )
    commands = parser.add_subparsers(dest="command")
    database_command = commands.add_parser("db", help="Database commands")
    database_actions = database_command.add_subparsers(dest="db_action", required=True)
    initialize_parser = database_actions.add_parser("init", help="Apply pending SQL migrations")
    initialize_parser.add_argument(
        "--database",
        type=Path,
        help="Database file path (defaults to DATABASE_PATH)",
    )
    commands.add_parser("run", help="Start the allowlisted Discord collector")
    commands.add_parser("web", help="Start the member website on loopback")
    backfill_parser = commands.add_parser("backfill", help="Backfill one allowlisted channel")
    backfill_parser.add_argument("--channel-id", required=True)
    topics_parser = commands.add_parser(
        "topics", help="Preview topic categories locally (owner-only)"
    )
    topics_parser.add_argument("--category", help="Filter by an exact category name")
    topics_parser.add_argument(
        "--member-view", action="store_true", help="Use only explicitly web-visible sources"
    )
    topics_parser.add_argument("--limit", type=int, default=20)
    topics_parser.add_argument("--offset", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not arguments:
        parser.print_help()
        return 0
    parsed = parser.parse_args(arguments)
    if parsed.command == "web":
        import uvicorn

        from discord_intel.web.app import create_app

        settings = load_settings()
        try:
            app = create_app(settings)
        except ValueError as error:
            parser.error(str(error))
        uvicorn.run(
            app,
            host=settings.web_host,
            port=settings.web_port,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1,::1",
            access_log=False,
        )
        return 0
    if parsed.command == "topics":
        try:
            result = asyncio.run(
                _preview_topics(
                    load_settings(),
                    parsed.category,
                    parsed.member_view,
                    parsed.limit,
                    parsed.offset,
                )
            )
        except (ValueError, OSError) as error:
            parser.error(str(error))
        print(result)
        return 0
    if parsed.command == "db" and parsed.db_action == "init":
        database_path = parsed.database or load_settings().database_path
        asyncio.run(Database(database_path).initialize())
        print(f"Database initialized: {database_path}")
        return 0
    if parsed.command in {"run", "backfill"}:
        settings = load_settings()
        if settings.discord_bot_token is None:
            parser.error("DISCORD_BOT_TOKEN is required for collector commands")
        if settings.discord_guild_id is None:
            parser.error("DISCORD_GUILD_ID is required for collector commands")
        if not settings.allowed_source_channel_ids:
            parser.error("ALLOWED_SOURCE_CHANNEL_IDS must include at least one channel")
        backfill_channel_id = getattr(parsed, "channel_id", None)
        if backfill_channel_id is not None and backfill_channel_id not in (
            settings.allowed_source_channel_ids
        ):
            parser.error("--channel-id must be in ALLOWED_SOURCE_CHANNEL_IDS")
        backfill_count = asyncio.run(_run_collector(settings, backfill_channel_id))
        if backfill_channel_id is not None:
            print(f"Backfill complete: {backfill_count or 0} messages")
        return 0
    parser.print_help()
    return 0
