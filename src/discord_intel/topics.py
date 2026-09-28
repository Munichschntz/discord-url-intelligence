"""Small, local topic rules and visibility-scoped category previews."""

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from discord_intel.config import Settings
from discord_intel.db import Database
from discord_intel.urls import extract_urls

UNCATEGORIZED = "Uncategorized"
DEFAULT_RULES = {
    "Coding": ["coding", "programming", "python", "javascript", "typescript", "github.com"],
    "Image Generation": [
        "image generation",
        "text to image",
        "stable diffusion",
        "comfyui",
        "midjourney",
    ],
    "Models": ["model", "models", "llm", "llms", "huggingface.co"],
    "Tutorials": ["tutorial", "tutorials", "guide", "walkthrough", "how to"],
    "Tools": ["tool", "tools", "cli", "utility", "utilities"],
}


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[^\W_]+", text.casefold())) + " "


def _prose(text: str) -> str:
    for occurrence in reversed(extract_urls(text)):
        text = text[: occurrence.start_offset] + " " + text[occurrence.end_offset :]
    return text


class TopicRules:
    def __init__(self, rules: object) -> None:
        if not isinstance(rules, dict) or not 1 <= len(rules) <= 30:
            raise ValueError("Topic rules must contain 1 to 30 categories")
        self._rules: dict[str, tuple[str, ...]] = {}
        names: set[str] = {UNCATEGORIZED.casefold()}
        for name, keywords in rules.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > 60
                or name != name.strip()
                or not name.isprintable()
                or name.casefold() in names
            ):
                raise ValueError("Category names must be unique, printable, and not Uncategorized")
            if not isinstance(keywords, list) or not 1 <= len(keywords) <= 100:
                raise ValueError("Each category needs 1 to 100 keywords")
            terms = []
            for keyword in keywords:
                if (
                    not isinstance(keyword, str)
                    or not 1 <= len(keyword) <= 100
                    or not keyword.isprintable()
                    or not _words(keyword).strip()
                ):
                    raise ValueError("Keywords must contain words and be at most 100 characters")
                terms.append(_words(keyword))
            self._rules[name] = tuple(terms)
            names.add(name.casefold())

    @classmethod
    def load(cls, path: Path | None = None) -> "TopicRules":
        if path is None:
            return cls(DEFAULT_RULES)
        with path.open("rb") as source:
            contents = tomllib.load(source)
        if set(contents) != {"topics"}:
            raise ValueError("Topic file must contain exactly one [topics] table")
        return cls(contents["topics"])

    @property
    def categories(self) -> tuple[str, ...]:
        return (*self._rules, UNCATEGORIZED)

    def classify(self, url: str, messages: Iterable[str]) -> tuple[str, ...]:
        evidence = [_words(unquote(url)), *(_words(_prose(text)) for text in messages)]
        matches = tuple(
            name
            for name, keywords in self._rules.items()
            if any(keyword in text for keyword in keywords for text in evidence)
        )
        return matches or (UNCATEGORIZED,)


@dataclass(frozen=True)
class Mention:
    channel: str
    author: str
    excerpt: str
    discord_url: str
    shared_at: str


@dataclass(frozen=True)
class TopicLink:
    link_id: int
    url: str
    categories: tuple[str, ...]
    message_count: int
    last_shared_at: str
    mentions: tuple[Mention, ...] = ()


@dataclass(frozen=True)
class TopicPage:
    counts: dict[str, int]
    links: tuple[TopicLink, ...]
    total: int


class TopicService:
    """Read current evidence; member entry point always applies visibility first.

    No category cache or persisted assignment needs invalidation. Intended for a
    small guild archive; no external search service is needed.
    """

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.rules = TopicRules.load(settings.topic_rules_path)

    async def member_links(
        self,
        category: str | None = None,
        *,
        limit: int = 20,
        offset: int = 0,
        query: str = "",
        verified_channels: set[str] | None = None,
    ) -> TopicPage:
        """Data scope only: web routes must also authenticate/check membership."""
        return await self._links(
            category, limit, offset, member=True, query=query, verified_channels=verified_channels
        )

    async def member_link(self, link_id: int, verified_channels: set[str]) -> TopicLink | None:
        page = await self._links(
            None, 1, 0, member=True, link_id=link_id, verified_channels=verified_channels
        )
        return page.links[0] if page.links else None

    async def owner_links(
        self, category: str | None = None, *, limit: int = 20, offset: int = 0
    ) -> TopicPage:
        return await self._links(category, limit, offset, member=False)

    async def _links(
        self,
        category: str | None,
        limit: int,
        offset: int,
        *,
        member: bool,
        query: str = "",
        verified_channels: set[str] | None = None,
        link_id: int | None = None,
    ) -> TopicPage:
        if category is not None and category not in self.rules.categories:
            raise ValueError("Unknown category; use one of: " + ", ".join(self.rules.categories))
        if not 1 <= limit <= 50 or not 0 <= offset <= 100_000:
            raise ValueError("Limit must be 1-50 and offset must be 0-100000")
        if len(query) > 200 or len(query.split()) > 20:
            raise ValueError("Search must be at most 200 characters and 20 words")
        terms = query.casefold().split()
        allowed = set(self.settings.allowed_source_channel_ids)
        if member:
            allowed &= set(self.settings.web_visible_channel_ids)
            if verified_channels is not None:
                allowed &= verified_channels
        counts = dict.fromkeys(self.rules.categories, 0)
        if not allowed or self.settings.discord_guild_id is None:
            return TopicPage(counts, (), 0)
        placeholders = ",".join("?" for _ in allowed)
        # Only placeholder counts and a fixed scope predicate enter SQL formatting.
        visibility = "AND c.web_visible = 1" if member else ""
        sql = f"""SELECT DISTINCT l.link_id, l.canonical_url,
                           m.message_id, m.content, m.created_at, c.channel_id, c.name,
                           a.display_name
                    FROM links l JOIN message_links ml ON ml.link_id = l.link_id
                    JOIN messages m ON m.message_id = ml.message_id
                    JOIN channels c ON c.channel_id = m.channel_id
                    JOIN authors a ON a.author_id = m.author_id
                    WHERE m.deleted_at IS NULL AND c.guild_id = ?
                      AND c.channel_id IN ({placeholders}) {visibility}
                      AND (? IS NULL OR l.link_id = ?)
                    ORDER BY l.link_id, m.created_at, m.message_id"""
        results: list[TopicLink] = []
        async with self.database.connection() as connection:
            async with connection.execute(
                sql, (self.settings.discord_guild_id, *sorted(allowed), link_id, link_id)
            ) as cursor:
                current_id: int | None = None
                url = ""
                messages: list[str] = []
                mentions: list[Mention] = []
                last_shared = ""

                def collect() -> None:
                    if current_id is None:
                        return
                    text = (url + "\n" + "\n".join(messages)).casefold()
                    if not all(term in text for term in terms):
                        return
                    topics = self.rules.classify(url, messages)
                    for topic in topics:
                        counts[topic] += 1
                    if category is None or category in topics:
                        results.append(
                            TopicLink(
                                current_id,
                                url,
                                topics,
                                len(messages),
                                last_shared,
                                tuple(reversed(mentions[-3:])),
                            )
                        )

                async for row in cursor:
                    if current_id != row["link_id"]:
                        collect()
                        current_id, url = row["link_id"], row["canonical_url"]
                        messages = []
                        mentions = []
                    messages.append(row["content"])
                    last_shared = row["created_at"]
                    mentions.append(
                        Mention(
                            row["name"],
                            row["display_name"],
                            row["content"][:300],
                            f"https://discord.com/channels/{self.settings.discord_guild_id}/"
                            f"{row['channel_id']}/{row['message_id']}",
                            last_shared,
                        )
                    )
                collect()
        results.sort(key=lambda link: (link.last_shared_at, link.link_id), reverse=True)
        return TopicPage(counts, tuple(results[offset : offset + limit]), len(results))
