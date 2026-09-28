import re
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio

from discord_intel.config import Settings
from discord_intel.db import Database
from discord_intel.ingest import IncomingMessage, IngestionService
from discord_intel.web.app import LOGIN, SESSION, create_app
from discord_intel.web.discord_api import READ, DiscordAPI, DiscordUnavailable, public_permissions


class DiscordMock:
    def __init__(self):
        self.member = True
        self.down = False
        self.denied = False
        self.retry = False
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.down:
            return httpx.Response(503)
        if self.retry:
            return httpx.Response(429, headers={"Retry-After": "30"})
        path = request.url.path
        if path.endswith("/oauth2/token"):
            body = parse_qs(request.content.decode())
            assert body["redirect_uri"] == ["https://links.example/auth/callback"]
            assert body["grant_type"] == ["authorization_code"]
            return httpx.Response(200, json={"access_token": "oauth-secret"})
        if path.endswith("/users/@me"):
            assert request.headers["Authorization"] == "Bearer oauth-secret"
            return httpx.Response(200, json={"id": "300"})
        assert request.headers["Authorization"] == "Bot bot-secret"
        if path.endswith("/members/300"):
            return (
                httpx.Response(200, json={"user": {"id": "300"}})
                if self.member
                else httpx.Response(404)
            )
        if path.endswith("/roles"):
            return httpx.Response(200, json=[{"id": "100", "permissions": str(READ)}])
        if path.endswith("/channels"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "200",
                        "guild_id": "100",
                        "type": 0,
                        "parent_id": None,
                        "permission_overwrites": (
                            [{"id": "300", "type": 1, "deny": str(1 << 10), "allow": "0"}]
                            if self.denied
                            else []
                        ),
                    }
                ],
            )
        raise AssertionError(path)


def message(id, content, channel="200"):
    return IncomingMessage(
        guild_id="100",
        guild_name="Friends",
        channel_id=channel,
        channel_name="shared-links",
        channel_kind="text",
        author_id="300",
        author_display_name="Ada",
        author_username="ada",
        author_is_bot=False,
        message_id=str(id),
        content=content,
        created_at="2026-09-27T00:00:00.000000Z",
    )


@pytest_asyncio.fixture
async def site(tmp_path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "web.sqlite3",
        discord_guild_id="100",
        allowed_source_channel_ids=["200", "201"],
        web_visible_channel_ids=["200"],
        discord_bot_token="bot-secret",
        discord_oauth_client_id="400",
        discord_oauth_client_secret="oauth-client-secret",
        discord_oauth_redirect_uri="https://links.example/auth/callback",
        web_session_secret="a" * 32,
    )
    clock = [1_800_000_000.0]
    fake = DiscordMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as discord_client:
        app = create_app(settings, http_client=discord_client, clock=lambda: clock[0])
        async with app.router.lifespan_context(app):
            database = Database(settings.database_path)
            ingest = IngestionService(database, settings)
            await ingest.ingest_message(message(1, "Python tutorial https://example.com/shared"))
            await ingest.ingest_message(
                message(2, "PRIVATE_CANARY model https://example.com/private", "201")
            )
            await ingest.ingest_message(
                message(3, "PRIVATE_CANARY model https://example.com/shared", "201")
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://links.example",
            ) as browser:
                yield browser, fake, database, ingest, clock, settings


async def login(browser):
    start = await browser.get("/auth/login?next=https://evil.example")
    params = parse_qs(urlsplit(start.headers["location"]).query)
    assert params["scope"] == ["identify"]
    callback = await browser.get(
        "/auth/callback", params={"state": params["state"][0], "code": "code"}
    )
    return callback, params["state"][0]


@pytest.mark.asyncio
async def test_sign_in_scoping_search_and_details(site):
    browser, fake, database, _, _, _ = site
    assert (await browser.get("/links")).status_code == 303
    assert (await browser.get("/links/1")).status_code == 303
    assert "PRIVATE_CANARY" not in (await browser.get("/")).text
    callback, state = await login(browser)
    assert callback.status_code == 303 and callback.headers["location"] == "/links"
    cookie = callback.headers.get_list("set-cookie")[-1]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "oauth-secret" not in cookie
    result = await browser.get("/links", params={"q": "python", "category": "Tutorials"})
    assert result.status_code == 200
    assert "https://example.com/shared" in result.text
    assert "https://discord.com/channels/100/200/1" in result.text
    assert "PRIVATE_CANARY" not in result.text and "example.com/private" not in result.text
    assert "1 mention" in result.text
    assert result.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in result.headers["content-security-policy"]
    assert "No matching links" in (await browser.get("/links?q=PRIVATE_CANARY")).text
    assert "No matching links" in (await browser.get("/links?category=Models")).text
    assert (await browser.get("/links/2")).status_code == 404
    assert "PRIVATE_CANARY" not in (await browser.get("/links/1")).text
    assert (
        await browser.get("/auth/callback", params={"state": state, "code": "code"})
    ).status_code == 400
    async with database.connection() as connection:
        row = await (await connection.execute("SELECT * FROM web_sessions")).fetchone()
        assert row["session_hash"] != browser.cookies.get(SESSION)
        assert "oauth-secret" not in str(tuple(row))


@pytest.mark.asyncio
async def test_login_state_bound_to_browser_and_expires(site):
    browser, fake, _, _, clock, _ = site
    start = await browser.get("/auth/login")
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    binder = browser.cookies.get(LOGIN)
    browser.cookies.clear()
    assert (
        await browser.get("/auth/callback", params={"state": state, "code": "x"})
    ).status_code == 400
    browser.cookies.set(LOGIN, binder, domain="links.example", path="/")
    clock[0] += 301
    assert (
        await browser.get("/auth/callback", params={"state": state, "code": "x"})
    ).status_code == 400
    assert fake.calls == []


@pytest.mark.asyncio
async def test_membership_removal_expiry_and_outage_fail_closed(site):
    browser, fake, _, _, clock, _ = site
    await login(browser)
    fake.member = False
    clock[0] += 300
    assert (await browser.get("/links")).status_code == 403
    assert (await browser.get("/links")).status_code == 303
    fake.member = True
    await login(browser)
    fake.down = True
    clock[0] += 300
    assert (await browser.get("/links")).status_code == 503
    fake.down = False
    clock[0] += 8 * 3600
    assert (await browser.get("/links")).status_code == 303


@pytest.mark.asyncio
async def test_nonmember_callback_denied(site):
    browser, fake, _, _, _, _ = site
    fake.member = False
    response, _ = await login(browser)
    assert response.status_code == 403
    assert browser.cookies.get(SESSION) is None


@pytest.mark.asyncio
async def test_visibility_revocation_and_outage_apply_immediately(site):
    browser, fake, _, _, _, settings = site
    await login(browser)
    assert "example.com/shared" in (await browser.get("/links")).text
    fake.denied = True
    assert "example.com/shared" not in (await browser.get("/links")).text
    assert (await browser.get("/links/1")).status_code == 404
    fake.denied = False
    assert "example.com/shared" in (await browser.get("/links")).text
    fake.down = True
    assert (await browser.get("/links")).status_code == 503
    fake.down = False
    settings.web_visible_channel_ids = []
    assert "example.com/shared" not in (await browser.get("/links")).text


@pytest.mark.asyncio
async def test_logout_requires_csrf_and_invalidates_session(site):
    browser, _, _, _, _, _ = site
    await login(browser)
    html = (await browser.get("/links")).text
    csrf = re.search(r'name="csrf" value="([^"]+)"', html)[1]
    assert (await browser.post("/logout", data={"csrf": csrf})).status_code == 403
    assert (
        await browser.post(
            "/logout", data={"csrf": "bad"}, headers={"Origin": "https://links.example"}
        )
    ).status_code == 403
    token = browser.cookies.get(SESSION)
    assert (
        await browser.post(
            "/logout", data={"csrf": "\u2603"}, headers={"Origin": "https://links.example"}
        )
    ).status_code == 403
    result = await browser.post(
        "/logout", data={"csrf": csrf}, headers={"Origin": "https://links.example"}
    )
    assert result.status_code == 303
    browser.cookies.set(SESSION, token, domain="links.example", path="/")
    assert (await browser.get("/links")).status_code == 303


@pytest.mark.asyncio
async def test_escaping_search_limits_pagination_and_lifecycle(site):
    browser, _, _, ingest, _, _ = site
    await ingest.ingest_message(message(4, '<script>alert("x")</script> https://example.com/xss'))
    for number in range(5, 28):
        await ingest.ingest_message(message(number, f"Tutorial https://example.com/item-{number}"))
    await login(browser)
    response = await browser.get("/links")
    assert response.text.count('class="link-card"') == 20
    assert "Next →" in response.text
    assert (await browser.get("/links?page=2")).text.count('class="link-card"') == 5
    result = await browser.get("/links?q=xss")
    assert "<script>" not in result.text and "&lt;script&gt;" in result.text
    assert (await browser.get("/links", params={"q": "x" * 201})).status_code == 400
    assert (await browser.get("/links?page=-1")).status_code == 400
    assert (await browser.get("/links/999999999999999999999999")).status_code == 404
    assert (await browser.get("/links?category=unknown")).status_code == 400
    assert (await browser.get("/links?q=%22OR%20*%20%25")).status_code == 200
    await ingest.ingest_message(
        replace(
            message(1, "Tools https://example.com/shared"), edited_at="2026-09-28T00:00:00.000000Z"
        ),
        reconcile_occurrences=True,
    )
    assert "No matching links" in (await browser.get("/links?category=Coding")).text
    await ingest.soft_delete_message("100", "200", "1")
    assert (await browser.get("/links/1")).status_code == 404


@pytest.mark.asyncio
async def test_rate_limit_and_discord_cooldown(site):
    browser, fake, _, _, _, _ = site
    await login(browser)
    fake.retry = True
    assert (await browser.get("/links")).status_code == 503
    count = len(fake.calls)
    assert (await browser.get("/links")).status_code == 503
    assert len(fake.calls) == count
    for _ in range(60):
        response = await browser.get("/")
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_host_and_https_required(site):
    browser, _, _, _, _, _ = site
    assert (await browser.get("/", headers={"host": "evil.example"})).status_code == 400
    assert (await browser.get("http://links.example/")).status_code == 400


def test_web_requires_complete_settings():
    with pytest.raises(ValueError, match="DISCORD_BOT_TOKEN"):
        create_app(Settings(_env_file=None))


@pytest.mark.parametrize("kind", [0, 1])
@pytest.mark.parametrize("denied", [1 << 10, 1 << 16])
def test_any_role_or_member_read_restriction_excludes_channel(kind, denied):
    channel = {
        "permission_overwrites": [
            {"id": "999", "type": kind, "deny": str(denied), "allow": str(READ)}
        ]
    }
    assert not public_permissions(channel, "100", READ)


def test_visibility_requires_complete_public_permissions():
    assert public_permissions({"permission_overwrites": []}, "100", READ)
    assert not public_permissions({}, "100", READ)
    assert not public_permissions({"permission_overwrites": []}, "100", -1)
    assert not public_permissions({"permission_overwrites": []}, "100", 1 << 10)
    everyone = {"id": "100", "type": 0, "allow": str(READ), "deny": "0"}
    assert public_permissions({"permission_overwrites": [everyone]}, "100", 0)
    assert not public_permissions({"permission_overwrites": [{"id": "100"}]}, "100", READ)


@pytest.mark.asyncio
async def test_parent_visibility_and_unknown_channel_types(site):
    *_, settings = site
    channels = [
        {"id": "200", "type": 0, "parent_id": "500", "permission_overwrites": []},
        {
            "id": "500",
            "type": 4,
            "permission_overwrites": [{"id": "999", "type": 0, "allow": "0", "deny": str(READ)}],
        },
    ]

    def respond(request):
        if request.url.path.endswith("/roles"):
            return httpx.Response(200, json=[{"id": "100", "permissions": str(READ)}])
        return httpx.Response(200, json=channels)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        api = DiscordAPI(settings, client)
        assert await api.visible_channels() == set()
        channels[1]["permission_overwrites"] = []
        assert await api.visible_channels() == {"200"}
        for kind in (2, 4, 10, 11, 12, 15, 16, 999):
            channels[0]["type"] = kind
            assert await api.visible_channels() == set()
        channels[0]["type"] = 0
        channels.pop()
        assert await api.visible_channels() == set()
        channels[0].pop("parent_id")
        assert await api.visible_channels() == set()


@pytest.mark.asyncio
async def test_discord_malformed_responses_and_timeout_fail_closed(site):
    *_, settings = site
    for data in ([], {}, {"user": {"id": "different"}}, {"user": {"id": "300"}, "pending": True}):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request, payload=data: httpx.Response(200, json=payload)
            )
        ) as client:
            api = DiscordAPI(settings, client)
            assert not await api.is_member("300")
            with pytest.raises(DiscordUnavailable):
                await api.identify("code")
            with pytest.raises(DiscordUnavailable):
                await api.visible_channels()

    def timeout(request):
        raise httpx.ReadTimeout("secret response", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(DiscordUnavailable) as error:
            await DiscordAPI(settings, client).is_member("300")
        assert "secret" not in str(error.value)
