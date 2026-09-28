"""Fixed-destination Discord REST calls for identity and public channel checks."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from discord_intel.config import Settings

READ = (1 << 10) | (1 << 16)


class DiscordUnavailable(Exception):
    """Discord could not supply a trustworthy current authorization result."""


def public_permissions(channel: dict[str, Any], guild_id: str, base: int) -> bool:
    overwrites = channel.get("permission_overwrites")
    if base < 0 or not isinstance(overwrites, list):
        return False
    permissions = base
    try:
        for overwrite in overwrites:
            denied = int(overwrite["deny"])
            allowed = int(overwrite["allow"])
            if denied < 0 or allowed < 0 or overwrite["type"] not in {0, 1}:
                return False
            if denied & READ:
                return False  # Conservative: reject any role/member restriction.
            if overwrite["id"] == guild_id and overwrite["type"] == 0:
                permissions |= allowed
        return permissions & READ == READ
    except (KeyError, ValueError, TypeError):
        return False


class DiscordAPI:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings, self.client, self.clock = settings, client, clock
        self.retry_at = 0.0

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self.clock() < self.retry_at:
            raise DiscordUnavailable()
        headers = {"User-Agent": "DiscordIntel/0.1 (member link library)"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        elif data is None:
            assert self.settings.discord_bot_token is not None
            headers["Authorization"] = "Bot " + self.settings.discord_bot_token.get_secret_value()
        try:
            response = await self.client.request(
                method,
                "https://discord.com/api/v10" + path,
                headers=headers,
                data=data,
            )
        except httpx.HTTPError:
            raise DiscordUnavailable() from None
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", "30"))
            except ValueError:
                delay = 30.0
            self.retry_at = self.clock() + max(1.0, min(300.0, delay))
        return response

    @staticmethod
    def payload(response: httpx.Response) -> Any:
        if response.status_code != 200:
            raise DiscordUnavailable()
        try:
            return response.json()
        except ValueError:
            raise DiscordUnavailable() from None

    async def identify(self, code: str) -> str:
        assert self.settings.discord_oauth_client_secret is not None
        response = await self.request(
            "POST",
            "/oauth2/token",
            data={
                "client_id": str(self.settings.discord_oauth_client_id),
                "client_secret": self.settings.discord_oauth_client_secret.get_secret_value(),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": str(self.settings.discord_oauth_redirect_uri),
            },
        )
        try:
            token = self.payload(response)["access_token"]
            if not isinstance(token, str) or not token:
                raise ValueError()
            user = self.payload(await self.request("GET", "/users/@me", token=token))
            user_id = user["id"]
            if not isinstance(user_id, str) or not user_id.isascii() or not user_id.isdecimal():
                raise ValueError()
            return user_id
        except (KeyError, TypeError, ValueError):
            raise DiscordUnavailable() from None

    async def is_member(self, user_id: str) -> bool:
        response = await self.request(
            "GET", f"/guilds/{self.settings.discord_guild_id}/members/{user_id}"
        )
        if response.status_code == 404:
            return False
        data = self.payload(response)
        return (
            isinstance(data, dict)
            and isinstance(data.get("user"), dict)
            and data["user"].get("id") == user_id
            and not data.get("pending", False)
        )

    async def visible_channels(self) -> set[str]:
        guild_id = str(self.settings.discord_guild_id)
        configured = set(self.settings.web_visible_channel_ids)
        configured &= set(self.settings.allowed_source_channel_ids)
        if not configured:
            return set()
        roles = self.payload(await self.request("GET", f"/guilds/{guild_id}/roles"))
        channels = self.payload(await self.request("GET", f"/guilds/{guild_id}/channels"))
        try:
            if not isinstance(roles, list) or not isinstance(channels, list):
                raise ValueError()
            everyone = next(role for role in roles if role["id"] == guild_id)
            base = int(everyone["permissions"])
            by_id = {channel["id"]: channel for channel in channels}
            visible = set()
            for channel_id in configured:
                channel = by_id.get(channel_id)
                if (
                    channel is None
                    or channel.get("guild_id", guild_id) != guild_id
                    or channel.get("type") not in {0, 5}
                    or "parent_id" not in channel
                    or not public_permissions(channel, guild_id, base)
                ):
                    continue
                parent_id = channel.get("parent_id")
                if parent_id is not None:
                    parent = by_id.get(parent_id)
                    if (
                        parent is None
                        or parent.get("type") != 4
                        or not public_permissions(parent, guild_id, base)
                    ):
                        continue
                visible.add(channel_id)
            return visible
        except (KeyError, TypeError, ValueError, StopIteration):
            raise DiscordUnavailable() from None
