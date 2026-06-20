SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inbound_catalog (
    fingerprint TEXT PRIMARY KEY,
    remarks TEXT NOT NULL DEFAULT '',
    protocol TEXT NOT NULL DEFAULT '',
    network TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 0,
    security TEXT NOT NULL DEFAULT '',
    panel_inbound_id INTEGER,
    endpoint_index INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS balancers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL UNIQUE,
    remarks TEXT NOT NULL DEFAULT '',
    strategy TEXT NOT NULL DEFAULT 'roundRobin',
    scope TEXT NOT NULL DEFAULT 'disabled',
    scope_target TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS balancer_members (
    balancer_id INTEGER NOT NULL REFERENCES balancers(id) ON DELETE CASCADE,
    inbound_fingerprint TEXT NOT NULL,
    PRIMARY KEY (balancer_id, inbound_fingerprint)
);

CREATE TABLE IF NOT EXISTS client_index (
    sub_id TEXT PRIMARY KEY,
    group_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    enable INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_client_group ON client_index(group_name);

CREATE TABLE IF NOT EXISTS group_balancers (
    group_name TEXT PRIMARY KEY,
    balancer_tag TEXT NOT NULL REFERENCES balancers(tag) ON DELETE CASCADE
);
"""