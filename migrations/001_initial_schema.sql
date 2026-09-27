CREATE TABLE guilds (
    guild_id TEXT PRIMARY KEY CHECK (length(guild_id) > 0 AND guild_id NOT GLOB '*[^0-9]*'),
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE channels (
    channel_id TEXT PRIMARY KEY CHECK (length(channel_id) > 0 AND channel_id NOT GLOB '*[^0-9]*'),
    guild_id TEXT NOT NULL REFERENCES guilds(guild_id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    web_visible INTEGER NOT NULL DEFAULT 0 CHECK (web_visible IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX channels_guild_id_idx ON channels(guild_id);
CREATE INDEX channels_web_visible_idx ON channels(web_visible, channel_id);

CREATE TABLE authors (
    author_id TEXT PRIMARY KEY CHECK (length(author_id) > 0 AND author_id NOT GLOB '*[^0-9]*'),
    display_name TEXT NOT NULL,
    username TEXT NOT NULL,
    is_bot INTEGER NOT NULL DEFAULT 0 CHECK (is_bot IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE messages (
    message_id TEXT PRIMARY KEY CHECK (length(message_id) > 0 AND message_id NOT GLOB '*[^0-9]*'),
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE RESTRICT,
    author_id TEXT NOT NULL REFERENCES authors(author_id) ON DELETE RESTRICT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    edited_at TEXT,
    deleted_at TEXT,
    has_links INTEGER NOT NULL DEFAULT 0 CHECK (has_links IN (0, 1)),
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX messages_channel_created_id_idx
    ON messages(channel_id, created_at, message_id);
CREATE INDEX messages_author_created_idx ON messages(author_id, created_at);

CREATE TABLE links (
    link_id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    first_original_url TEXT NOT NULL,
    host TEXT NOT NULL,
    domain TEXT NOT NULL,
    provider TEXT,
    resource_type TEXT,
    title TEXT,
    description TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    metadata_fetched_at TEXT,
    metadata_checked_at TEXT,
    enrichment_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (enrichment_state IN ('pending', 'running', 'succeeded', 'failed')),
    CHECK (first_seen <= last_seen)
);

CREATE INDEX links_host_idx ON links(host);
CREATE INDEX links_domain_idx ON links(domain);
CREATE INDEX links_provider_resource_idx ON links(provider, resource_type);

CREATE TABLE message_links (
    occurrence_id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    link_id INTEGER NOT NULL REFERENCES links(link_id) ON DELETE RESTRICT,
    occurrence_index INTEGER NOT NULL CHECK (occurrence_index >= 0),
    raw_url TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset > start_offset),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (message_id, occurrence_index)
);

CREATE INDEX message_links_link_message_idx ON message_links(link_id, message_id);
CREATE INDEX message_links_message_link_idx ON message_links(message_id, link_id);

CREATE TABLE link_metadata (
    link_id INTEGER PRIMARY KEY REFERENCES links(link_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    readable_text TEXT,
    etag TEXT,
    last_modified TEXT,
    fetched_at TEXT,
    checked_at TEXT,
    content_hash TEXT
);

CREATE TABLE jobs (
    job_id INTEGER PRIMARY KEY,
    link_id INTEGER REFERENCES links(link_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    available_at TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    started_at TEXT,
    finished_at TEXT,
    last_error TEXT,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX jobs_available_idx ON jobs(status, available_at, job_id);
CREATE UNIQUE INDEX jobs_outstanding_dedupe_idx ON jobs(dedupe_key)
    WHERE status IN ('pending', 'running');
CREATE UNIQUE INDEX jobs_outstanding_link_kind_idx ON jobs(link_id, kind)
    WHERE link_id IS NOT NULL AND status IN ('pending', 'running');

CREATE TABLE channel_checkpoints (
    channel_id TEXT PRIMARY KEY REFERENCES channels(channel_id) ON DELETE CASCADE,
    last_message_id TEXT,
    updated_at TEXT NOT NULL,
    backfill_state TEXT NOT NULL DEFAULT 'idle'
        CHECK (backfill_state IN ('idle', 'running', 'complete', 'failed'))
);

CREATE TABLE tags (
    tag_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE link_tags (
    link_id INTEGER NOT NULL REFERENCES links(link_id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('manual', 'provider', 'LLM')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (link_id, tag_id, source)
);

CREATE INDEX link_tags_tag_id_idx ON link_tags(tag_id, link_id);

CREATE TABLE search_documents (
    document_id INTEGER PRIMARY KEY,
    link_id INTEGER NOT NULL UNIQUE REFERENCES links(link_id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE search_fts USING fts5(
    title,
    description,
    tags,
    body,
    context,
    content='search_documents',
    content_rowid='document_id',
    tokenize='unicode61'
);

CREATE TRIGGER search_documents_ai AFTER INSERT ON search_documents BEGIN
    INSERT INTO search_fts(rowid, title, description, tags, body, context)
    VALUES (new.document_id, new.title, new.description, new.tags, new.body, new.context);
END;

CREATE TRIGGER search_documents_ad AFTER DELETE ON search_documents BEGIN
    INSERT INTO search_fts(search_fts, rowid, title, description, tags, body, context)
    VALUES ('delete', old.document_id, old.title, old.description, old.tags, old.body, old.context);
END;

CREATE TRIGGER search_documents_au AFTER UPDATE ON search_documents BEGIN
    INSERT INTO search_fts(search_fts, rowid, title, description, tags, body, context)
    VALUES ('delete', old.document_id, old.title, old.description, old.tags, old.body, old.context);
    INSERT INTO search_fts(rowid, title, description, tags, body, context)
    VALUES (new.document_id, new.title, new.description, new.tags, new.body, new.context);
END;

CREATE TABLE web_search_documents (
    document_id INTEGER PRIMARY KEY,
    link_id INTEGER NOT NULL UNIQUE REFERENCES links(link_id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE web_search_fts USING fts5(
    title,
    description,
    tags,
    body,
    context,
    content='web_search_documents',
    content_rowid='document_id',
    tokenize='unicode61'
);

CREATE TRIGGER web_search_documents_ai AFTER INSERT ON web_search_documents BEGIN
    INSERT INTO web_search_fts(rowid, title, description, tags, body, context)
    VALUES (new.document_id, new.title, new.description, new.tags, new.body, new.context);
END;

CREATE TRIGGER web_search_documents_ad AFTER DELETE ON web_search_documents BEGIN
    INSERT INTO web_search_fts(web_search_fts, rowid, title, description, tags, body, context)
    VALUES ('delete', old.document_id, old.title, old.description, old.tags, old.body, old.context);
END;

CREATE TRIGGER web_search_documents_au AFTER UPDATE ON web_search_documents BEGIN
    INSERT INTO web_search_fts(web_search_fts, rowid, title, description, tags, body, context)
    VALUES ('delete', old.document_id, old.title, old.description, old.tags, old.body, old.context);
    INSERT INTO web_search_fts(rowid, title, description, tags, body, context)
    VALUES (new.document_id, new.title, new.description, new.tags, new.body, new.context);
END;