"""Server-rendered, read-only link library for current Discord guild members."""

import hmac
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from discord_intel.config import Settings
from discord_intel.db import Database, transaction
from discord_intel.topics import TopicService
from discord_intel.web.auth import AuthStore, stamp
from discord_intel.web.discord_api import DiscordAPI, DiscordUnavailable

SESSION = "__Host-discord_intel"
LOGIN = "__Host-discord_login"
ASSETS = Path(__file__).parent


def validate_web_settings(settings: Settings) -> None:
    required = (
        "discord_bot_token",
        "discord_guild_id",
        "discord_oauth_client_id",
        "discord_oauth_client_secret",
        "discord_oauth_redirect_uri",
        "web_session_secret",
    )
    missing = [name.upper() for name in required if not getattr(settings, name)]
    if missing:
        raise ValueError("Configure " + ", ".join(missing) + " in your local .env")
    assert settings.web_session_secret is not None
    if len(settings.web_session_secret.get_secret_value()) < 32:
        raise ValueError("WEB_SESSION_SECRET must contain at least 32 random characters")


class RateLimit:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self.entries: dict[str, tuple[int, float]] = {}

    def allow(self, key: str, maximum: int) -> bool:
        now = self.clock()
        self.entries = {key: value for key, value in self.entries.items() if value[1] > now}
        count, expires = self.entries.get(key, (0, now + 60))
        if count >= maximum or (key not in self.entries and len(self.entries) >= 5000):
            return False
        self.entries[key] = (count + 1, expires)
        return True


def create_app(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    validate_web_settings(settings)
    database = Database(settings.database_path)
    assert settings.web_session_secret is not None
    auth = AuthStore(database, settings.web_session_secret.get_secret_value(), clock)
    client = http_client or httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=5),
    )
    discord = DiscordAPI(settings, client, clock)
    topics = TopicService(database, settings)
    templates = Jinja2Templates(directory=str(ASSETS / "templates"))
    origin_parts = urlsplit(str(settings.discord_oauth_redirect_uri))
    origin = f"https://{origin_parts.netloc}"
    limiter = RateLimit(clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await database.initialize()
        try:
            yield
        finally:
            if http_client is None:
                await client.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=ASSETS / "static"), name="static")

    @app.middleware("http")
    async def protect(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        ip = request.client.host if request.client else "unknown"
        cookie = request.cookies.get(SESSION, "")
        if request.headers.get("host", "").lower() != origin_parts.netloc.lower():
            response: Response = Response("Invalid host", status_code=400)
        elif request.url.scheme != "https":
            response = Response("Open the configured HTTPS address to sign in.", status_code=400)
        elif len(request.url.query) > 4096 or len(cookie) > 128:
            response = Response("Request too large", status_code=400)
        elif (
            not limiter.allow("ip:" + ip, 120)
            or (cookie and not limiter.allow("session:" + auth.digest(cookie), 60))
            or (request.url.path.startswith("/auth/") and not limiter.allow("login:" + ip, 20))
        ):
            response = Response(
                "Please wait a minute and try again.",
                status_code=429,
                headers={"Retry-After": "60"},
            )
        else:
            response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'self'; img-src 'self'; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            }
        )
        return response

    def render(
        request: Request, template: str, *, status_code: int = 200, **context: object
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name=template, context=context, status_code=status_code
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> Response:
        if error.status_code == 303:
            return RedirectResponse("/", status_code=303)
        return render(
            request, "error.html", status_code=error.status_code, message=str(error.detail)
        )

    @app.exception_handler(DiscordUnavailable)
    async def unavailable(request: Request, error: DiscordUnavailable) -> Response:
        return render(
            request,
            "error.html",
            status_code=503,
            message="Discord is unavailable. Please try again shortly.",
        )

    async def signed_in(request: Request) -> str:
        token = request.cookies.get(SESSION, "")
        session = await auth.read(token)
        if session is None:
            raise HTTPException(303, headers={"Location": "/"})
        if session["verified_at"] <= stamp(clock() - 300):
            if not await discord.is_member(session["user_id"]):
                await auth.delete(token)
                raise HTTPException(403, "This library is for current server members.")
            await auth.verified(token)
        return token

    async def visible() -> set[str]:
        # Never reuse a permission snapshot after a failed live check.
        channels = await discord.visible_channels()
        async with database.connection() as connection, transaction(connection):
            await connection.execute("UPDATE channels SET web_visible = 0")
            for channel_id in channels:
                await connection.execute(
                    "UPDATE channels SET web_visible = 1 WHERE channel_id = ? AND guild_id = ?",
                    (channel_id, settings.discord_guild_id),
                )
        return channels

    @app.get("/", response_class=HTMLResponse)
    async def landing(request: Request) -> Response:
        if await auth.read(request.cookies.get(SESSION, "")) is not None:
            return RedirectResponse("/links", status_code=303)
        return render(request, "login.html")

    @app.get("/auth/login")
    async def login(request: Request) -> Response:
        state, browser = await auth.begin()
        query = urlencode(
            {
                "client_id": settings.discord_oauth_client_id,
                "response_type": "code",
                "scope": "identify",
                "redirect_uri": settings.discord_oauth_redirect_uri,
                "state": state,
            }
        )
        response = RedirectResponse(
            "https://discord.com/oauth2/authorize?" + query, status_code=303
        )
        response.set_cookie(LOGIN, browser, max_age=300, secure=True, httponly=True, samesite="lax")
        return response

    @app.get("/auth/callback")
    async def callback(request: Request) -> Response:
        state, code = request.query_params.get("state", ""), request.query_params.get("code", "")
        if not await auth.consume(state, request.cookies.get(LOGIN, "")):
            raise HTTPException(400, "Login expired or invalid. Start sign-in again.")
        if not code or len(code) > 2048 or "error" in request.query_params:
            raise HTTPException(400, "Discord sign-in was not completed.")
        user_id = await discord.identify(code)
        if not await discord.is_member(user_id):
            raise HTTPException(403, "This library is for current server members.")
        await auth.delete(request.cookies.get(SESSION, ""))
        token = await auth.create(user_id)
        response = RedirectResponse("/links", status_code=303)
        response.delete_cookie(LOGIN, secure=True, httponly=True, samesite="lax")
        response.set_cookie(
            SESSION, token, max_age=8 * 3600, secure=True, httponly=True, samesite="lax"
        )
        return response

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        token = request.cookies.get(SESSION, "")
        if await auth.read(token) is None:
            raise HTTPException(403, "Session expired")
        if request.headers.get("origin") != origin:
            raise HTTPException(403, "Invalid form origin")
        body = bytearray()
        async for part in request.stream():
            if len(body) + len(part) > 1024:
                raise HTTPException(400, "Form too large")
            body.extend(part)
        fields = parse_qs(body.decode("utf-8", errors="replace"))
        if not hmac.compare_digest(fields.get("csrf", [""])[0].encode(), auth.csrf(token).encode()):
            raise HTTPException(403, "Invalid form token")
        await auth.delete(token)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(SESSION, secure=True, httponly=True, samesite="lax")
        return response

    @app.get("/links", response_class=HTMLResponse)
    async def library(request: Request) -> Response:
        token = await signed_in(request)
        q = request.query_params.get("q", "").strip()
        category = request.query_params.get("category") or None
        try:
            page_number = int(request.query_params.get("page", "1"))
            if not 1 <= page_number <= 5001:
                raise ValueError("Page must be between 1 and 5001")
            # Validate inputs before spending REST calls on visibility.
            if len(q) > 200 or len(q.split()) > 20:
                raise ValueError("Search is limited to 200 characters and 20 words")
            if category is not None and category not in topics.rules.categories:
                raise ValueError("Unknown topic")
            data = await topics.member_links(
                category,
                query=q,
                offset=(page_number - 1) * 20,
                verified_channels=await visible(),
            )
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

        def page_url(number: int) -> str:
            return "/links?" + urlencode({"q": q, "category": category or "", "page": number})

        return render(
            request,
            "library.html",
            page=data,
            q=q,
            category=category or "",
            csrf=auth.csrf(token),
            categories=topics.rules.categories,
            previous=page_url(page_number - 1) if page_number > 1 else None,
            following=(
                page_url(page_number + 1)
                if page_number < 5001 and page_number * 20 < data.total
                else None
            ),
        )

    @app.get("/links/{link_id}", response_class=HTMLResponse)
    async def detail(request: Request, link_id: int) -> Response:
        token = await signed_in(request)
        if not 0 < link_id <= 2**63 - 1:
            raise HTTPException(404, "Link not found")
        link = await topics.member_link(link_id, await visible())
        if link is None:
            raise HTTPException(404, "Link not found")
        return render(request, "detail.html", link=link, csrf=auth.csrf(token))

    return app
