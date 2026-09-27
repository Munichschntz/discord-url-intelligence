# Official API Contracts

This scaffold contains no external API integration. These official references are starting points only; verify current behavior, SDK imports, versions, and required permissions when implementing each adapter, then record the exact contract used. Discord account/permission references used for Milestone 0 were checked for reachability on 2026-09-27.

| Integration | Official references | Status |
|---|---|---|
| Discord Gateway, intents, messages | [Gateway events](https://docs.discord.com/developers/events/gateway), [message resource](https://docs.discord.com/developers/resources/message), [Gateway intents](https://docs.discord.com/developers/events/gateway#gateway-intents) | Verify for Milestone 4 |
| Discord channel history and rate limits | [Get channel messages](https://docs.discord.com/developers/resources/channel#get-channel-messages), [rate limits](https://docs.discord.com/developers/topics/rate-limits) | Verify for Milestone 5 |
| Discord OAuth and guild membership | [OAuth2](https://docs.discord.com/developers/topics/oauth2), [Get Current User](https://docs.discord.com/developers/resources/user#get-current-user), [Get Guild Member](https://docs.discord.com/developers/resources/guild#get-guild-member) | Setup references checked for Milestone 0; verify endpoint permissions for Milestone 10A |
| GitHub REST | [API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions), [repositories](https://docs.github.com/en/rest/repos/repos), [repository contents](https://docs.github.com/en/rest/repos/contents), [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) | Verify for Milestone 7 |
| Hugging Face Hub | [HfApi](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api), [model cards](https://huggingface.co/docs/huggingface_hub/guides/model-cards), [Hub API](https://huggingface.co/docs/hub/api/) | Verify for Milestone 8A |
| Hacker News | [Official Firebase API](https://github.com/HackerNews/API) | Verify for Milestone 8B |
| SQLite FTS5 and backup | [FTS5](https://www.sqlite.org/fts5.html), [online backup API](https://www.sqlite.org/backup.html) | Verify for Milestones 2, 9, and 16 |
| LM Studio local endpoints | [OpenAI-compatible API](https://lmstudio.ai/docs/developer/openai-compat), [structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [embeddings](https://lmstudio.ai/docs/developer/openai-compat/embeddings) | Verify for Milestones 12 and 13 |
| MCP Python SDK v2 | [Official SDK docs](https://py.sdk.modelcontextprotocol.io/), [SDK repository](https://github.com/modelcontextprotocol/python-sdk), [run/deployment](https://py.sdk.modelcontextprotocol.io/run/) | Verify v2 API and transport for Milestone 11 |