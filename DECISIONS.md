# Architecture Decisions

## 2026-09-27: Scaffold boundaries

- Use Python 3.12+ and `uv`; the current development container has Python 3.14, which is within that range.
- Use Pydantic Settings for validated environment configuration and `SecretStr` for secret values.
- Use `argparse` for the minimal CLI so the scaffold adds no CLI framework dependency.
- Keep `.env` and local database state out of version control. Web-visible channel IDs must be a subset of configured source channels, and web/MCP listeners default to loopback.
- No external API integration has been implemented, so no API behavior has been inferred from the reference links.

## API discrepancies

None recorded. Recheck the official contract at the milestone where each integration is first implemented.