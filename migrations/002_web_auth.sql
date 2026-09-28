CREATE TABLE web_sessions (
    session_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    verified_at TEXT NOT NULL
);
CREATE INDEX web_sessions_expiry_idx ON web_sessions(expires_at);

CREATE TABLE web_login_states (
    state_hash TEXT PRIMARY KEY,
    browser_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX web_login_states_expiry_idx ON web_login_states(expires_at);
