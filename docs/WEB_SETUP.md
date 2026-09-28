# Launch the member website

Run the collector and website on the same trusted Windows machine with the same local
SQLite database. Python and all packages remain inside this project. No AI, worker,
Docker, separate database server, or GitHub runner is needed.

## 1. Set up Discord and local configuration

Run `.\setup.ps1` to install the locked dependencies, including the website. Copy
`.env.example` to `.env` only if you do not already have one.

In the [Discord Developer Portal](https://discord.com/developers/applications), use an
application whose bot is installed in your server. Enable **Message Content Intent** on
the Bot page. Install with the bot scope and only **View Channels** and **Read Message
History** permissions in the selected channels. Never use a Discord user token.

In your local `.env`, configure:

```dotenv
DISCORD_BOT_TOKEN=replace-with-bot-token
DISCORD_GUILD_ID=123456789012345678
ALLOWED_SOURCE_CHANNEL_IDS=["234567890123456789"]
WEB_VISIBLE_CHANNEL_IDS=["234567890123456789"]
DISCORD_OAUTH_CLIENT_ID=replace-with-numeric-application-id
DISCORD_OAUTH_CLIENT_SECRET=replace-with-oauth-client-secret
DISCORD_OAUTH_REDIRECT_URI=https://your-public-host/auth/callback
WEB_SESSION_SECRET=replace-with-random-secret
WEB_HOST=127.0.0.1
WEB_PORT=4710
DATABASE_PATH=data/discord-intel.sqlite3
```

These are placeholders. Keep tokens/secrets on this machine, out of chat and Git. OAuth
client credentials come from the application's OAuth2 page; the bot token is separate.
Generate the session secret locally, then paste its output into `.env`:

```powershell
.\.venv\Scripts\python.exe -I -c "import secrets; print(secrets.token_urlsafe(48))"
```

Only designate channels the owner has approved for **every server member**. The website
also verifies Discord's current permissions before each data response. Both @everyone
View Channel and Read Message History must be allowed, with no role/member denial of
either permission. Parent categories must pass the same check. Role-gated channels,
threads, forums, and uncertain permissions are excluded. Do not loosen private-channel
permissions to get those links onto the site.

## 2. Choose the HTTPS address

Use an HTTPS reverse proxy/tunnel forwarding only to `http://127.0.0.1:4710`. Preserve the
public Host header and set `X-Forwarded-Proto: https`. Uvicorn trusts forwarded headers
only from a local proxy. Do not expose its port directly or proxy project/data directories.
Disable proxy caching and access logging of OAuth query strings and cookies.

For a short trial without a domain, install `cloudflared` from
[Cloudflare's official instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)
and start a [Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/):

```powershell
cloudflared tunnel --url http://127.0.0.1:4710
```

Keep that window running. Copy its generated `https://...trycloudflare.com` address.
Requests may fail until the website starts in the next step. Set
`DISCORD_OAUTH_REDIRECT_URI` to that address plus `/auth/callback`, and register the
**identical full URI** under OAuth2 Redirects in the Developer Portal. Save both settings.
Quick Tunnels are temporary testing tools; for ongoing friend access use a stable HTTPS
hostname/tunnel. Every hostname change requires updating both callback settings and
restarting the website. Do not override the tunnel's origin Host header to localhost.

## 3. Run and try it

First window, live collector:

```powershell
.\run.ps1 run
```

Second window, website:

```powershell
.\run.ps1 web
```

Open the public HTTPS address and choose **Continue with Discord**. Sign-in requests only
your Discord identity; the bot separately checks that you belong to this server. Members
can search current message text and URLs, combine search with a topic, and open original
links or messages. Each page holds 20 links. Search matches all entered terms literally,
ignoring case; it does not search the contents of linked websites.

For older messages, run once per source channel in another window:

```powershell
.\run.ps1 backfill --channel-id 234567890123456789
```

The collector, web process, and tunnel must stay running; sleeping/shutting down the host
makes them unavailable. Stop each with Ctrl+C. Run one web process and one collector per
database. Rerun setup after pulling dependency changes; restart processes after changing
`.env` or topic rules. Startup automatically applies the new session migration and leaves
existing messages, occurrences, and links intact.

## Controlled-server check before inviting friends

Status: **pending**. Offline tests use mocked Discord responses; they do not replace this
check with your bot, permissions, HTTPS proxy, and registered callback.

1. In a test server, designate one public channel and keep a second private channel out
   of the web-visible list. Post distinct links in each and one repeated across both.
2. Sign in as an ordinary member. Confirm only public links, counts, excerpts, topics,
   and mentions appear. Search a word used only in the private message: no result.
3. Search and filter together, use the original-message link, and check a phone layout.
   Edit/delete a public message with the collector running and confirm results update.
4. Restrict a designated test channel: its links must disappear on the next request.
   Do not perform this experiment on a real shared channel without its owner's agreement.
5. Try a nonmember account: sign-in must deny access. Remove a test member: existing
   access must stop within five minutes. Sessions expire after eight hours.
6. Sign out, then try reopening a detail page: it must require sign-in. Record the date
   and outcome in PLAN.md, without tokens, message contents, or other private data.

## Troubleshooting and backup

- **Invalid host / HTTPS required:** use the exact public HTTPS hostname and check proxy
  Host and forwarded-protocol settings. Plain localhost access intentionally cannot sign in.
- **Callback mismatch:** the portal and `.env` must match, including `/auth/callback`.
- **Empty library:** check collection/backfill, both channel lists, and the public permission
  rules above. Newly collected channels default to hidden until a successful web check.
- **Discord unavailable:** the site fails closed. Check connectivity and bot access; after
  a rate limit, wait before retrying. Shared URLs are never fetched by the application.
- **Sign-in denied:** the account must be a current member and have passed membership
  screening. Public deployment does not make the library public to nonmembers.
- **Backups:** stop both processes, then privately copy `.env`, any `topics.toml`, and the
  entire `data` directory (including any SQLite WAL/SHM files). Restore with processes
  stopped and the same compatible app version. Rotating the session secret signs everyone
  out. Never commit backups or expose them through the web proxy.
