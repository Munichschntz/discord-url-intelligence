import json
from dataclasses import replace
from pathlib import Path

import pytest

from discord_intel.cli import main
from discord_intel.config import Settings
from discord_intel.db import Database
from discord_intel.ingest import IncomingMessage, IngestionService
from discord_intel.topics import TopicRules, TopicService


def message(id: str, text: str, channel: str = "200") -> IncomingMessage:
    return IncomingMessage(
        guild_id="100",
        guild_name="Guild",
        channel_id=channel,
        channel_name="Links",
        channel_kind="text",
        author_id="300",
        author_display_name="Ada",
        author_username="ada",
        author_is_bot=False,
        message_id=id,
        content=text,
        created_at="2026-09-27T00:00:00.000000Z",
    )


async def setup(tmp_path: Path):
    database = Database(tmp_path / "topics.sqlite3")
    await database.initialize()
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "topics.sqlite3",
        discord_guild_id="100",
        allowed_source_channel_ids=["200", "201", "202"],
        web_visible_channel_ids=["200", "201"],
    )
    return database, settings, IngestionService(database, settings)


async def visible(database: Database, *channels: str):
    async with database.connection() as connection:
        for channel in channels:
            await connection.execute(
                "UPDATE channels SET web_visible = 1 WHERE channel_id = ?", (channel,)
            )
        await connection.commit()


def test_defaults_multiple_topics_boundaries_and_fallback():
    rules = TopicRules.load()
    assert rules.classify("https://example.com/python-guide", ["Handy CLI tool"]) == (
        "Coding",
        "Tutorials",
        "Tools",
    )
    assert rules.classify("https://example.com/", ["COMFYUI for text-to-image models"]) == (
        "Image Generation",
        "Models",
    )
    assert rules.classify("https://example.com/remodeling", ["guidelines toolbox"]) == (
        "Uncategorized",
    )
    assert rules.classify("https://example.com/text%20to%20image", []) == ("Image Generation",)


def test_other_urls_and_separate_messages_do_not_create_topic_matches():
    rules = TopicRules.load()
    assert rules.classify("https://example.com/", ["Also https://github.com/owner/repo"]) == (
        "Uncategorized",
    )
    assert rules.classify("https://example.com/", ["stable", "diffusion"]) == ("Uncategorized",)


def test_custom_rules_and_example(tmp_path: Path):
    path = tmp_path / "topics.toml"
    path.write_text('[topics]\nAudio = ["speech", "tts"]\n', encoding="utf-8")
    assert TopicRules.load(path).classify("https://example.com/tts", []) == ("Audio",)
    assert TopicRules.load(Path("topics.example.toml")).categories == TopicRules.load().categories


@pytest.mark.parametrize(
    "rules",
    [
        {},
        {"Uncategorized": ["x"]},
        {"X": ["a"], "x": ["b"]},
        {" X": ["a"]},
        {"X": []},
        {"X": "keyword"},
        {"X": [" "]},
        {"X": [123]},
        {"X": ["***"]},
    ],
)
def test_invalid_rules_rejected(rules):
    with pytest.raises(ValueError):
        TopicRules(rules)


@pytest.mark.asyncio
async def test_cross_channel_categories_deduplication_and_filtering(tmp_path: Path):
    database, settings, ingest = await setup(tmp_path)
    await ingest.ingest_message(message("1", "Python https://example.com/a https://example.com/a"))
    await ingest.ingest_message(message("2", "Tutorial https://example.com/a", "201"))
    await ingest.ingest_message(message("3", "https://example.com/b"))
    await visible(database, "200", "201")
    service = TopicService(database, settings)
    page = await service.member_links("Coding")
    assert page.total == 1 and len(page.links) == 1
    assert page.links[0].categories == ("Coding", "Tutorials")
    assert page.links[0].message_count == 2
    assert page.counts["Coding"] == 1 and page.counts["Uncategorized"] == 1
    assert (await service.member_links("Uncategorized")).links[0].url.endswith("/b")
    assert len((await service.member_links(limit=1)).links) == 1
    assert len((await service.member_links(limit=1, offset=1)).links) == 1
    async with database.connection() as connection:
        assert (await (await connection.execute("SELECT count(*) FROM message_links")).fetchone())[
            0
        ] == 4


@pytest.mark.asyncio
async def test_private_evidence_never_affects_member_topics_counts_or_order(tmp_path: Path):
    database, settings, ingest = await setup(tmp_path)
    await ingest.ingest_message(message("1", "https://example.com/shared"))
    await ingest.ingest_message(message("2", "Python https://example.com/private", "202"))
    await visible(database, "200", "202")  # A DB flag alone cannot grant visibility.
    service = TopicService(database, settings)
    before = await service.member_links()
    await ingest.ingest_message(
        replace(
            message("3", "Python guide https://example.com/shared", "202"),
            created_at="2026-09-28T00:00:00.000000Z",
        )
    )
    assert await service.member_links() == before
    assert before.links[0].categories == ("Uncategorized",)
    assert (await service.owner_links("Coding")).total == 2
    assert (await service.member_links("Coding")).total == 0
    # Both the DB designation and current configuration must grant visibility.
    settings.web_visible_channel_ids = []
    assert (await service.member_links()).total == 0
    settings.web_visible_channel_ids = ["200"]
    settings.allowed_source_channel_ids = ["201", "202"]
    assert (await service.member_links()).total == 0
    settings.allowed_source_channel_ids = ["200"]
    settings.discord_guild_id = "999"
    assert (await service.member_links()).total == 0


@pytest.mark.asyncio
async def test_edits_deletes_and_rule_changes_apply_to_existing_links(tmp_path: Path):
    database, settings, ingest = await setup(tmp_path)
    original = message("1", "Python https://example.com/a")
    await ingest.ingest_message(original)
    await visible(database, "200")
    service = TopicService(database, settings)
    assert (await service.member_links("Coding")).total == 1
    await ingest.ingest_message(
        replace(original, content="Tutorial https://example.com/a"), reconcile_occurrences=True
    )
    assert (await service.member_links("Coding")).total == 0
    assert (await service.member_links("Tutorials")).total == 1
    path = tmp_path / "topics.toml"
    path.write_text('[topics]\nLearning = ["tutorial"]\n', encoding="utf-8")
    settings.topic_rules_path = path
    assert (await TopicService(database, settings).member_links("Learning")).total == 1
    await ingest.soft_delete_message("100", "200", "1")
    assert (await service.member_links()).total == 0
    async with database.connection() as connection:
        assert (await (await connection.execute("SELECT count(*) FROM links")).fetchone())[0] == 1


@pytest.mark.asyncio
async def test_removed_url_and_revoked_visibility(tmp_path: Path):
    database, settings, ingest = await setup(tmp_path)
    original = message("1", "Python https://example.com/a")
    await ingest.ingest_message(original)
    service = TopicService(database, settings)
    assert (await service.member_links()).total == 0  # Default database visibility is false.
    await visible(database, "200")
    assert (await service.member_links()).total == 1
    async with database.connection() as connection:
        await connection.execute("UPDATE channels SET web_visible = 0")
        await connection.commit()
    assert (await service.member_links()).total == 0
    await ingest.ingest_message(
        replace(original, content="Python without a URL"), reconcile_occurrences=True
    )
    assert (await service.owner_links()).total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "missing"},
        {"limit": 51},
        {"limit": 0},
        {"offset": -1},
        {"offset": 100001},
    ],
)
async def test_bounded_queries(tmp_path: Path, kwargs):
    database, settings, _ = await setup(tmp_path)
    with pytest.raises(ValueError):
        await TopicService(database, settings).member_links(**kwargs)


def test_cli_topics_is_local_and_returns_categories(tmp_path: Path, monkeypatch, capsys):
    settings = Settings(_env_file=None, database_path=tmp_path / "cli.sqlite3")
    monkeypatch.setattr("discord_intel.cli.load_settings", lambda: settings)
    assert main(["topics", "--member-view", "--category", "Coding"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["Coding"] == 0 and result["links"] == []
    with pytest.raises(SystemExit) as exc:
        main(["topics", "--limit", "51"])
    assert exc.value.code == 2
