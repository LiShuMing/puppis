CREATE TABLE IF NOT EXISTS sources (
  source_id    TEXT PRIMARY KEY,
  connector_id TEXT NOT NULL,
  config_json  TEXT NOT NULL,
  status       TEXT NOT NULL,
  cursor_json  TEXT,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_objects (
  raw_id       TEXT PRIMARY KEY,
  source_id    TEXT NOT NULL REFERENCES sources(source_id),
  item_id      TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  uri          TEXT NOT NULL,
  fetched_at   TEXT NOT NULL,
  UNIQUE(source_id, item_id, content_hash)
);

CREATE TABLE IF NOT EXISTS items (
  item_id      TEXT PRIMARY KEY,
  source_id    TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  kind         TEXT NOT NULL,
  title        TEXT,
  body         TEXT NOT NULL,
  source_url   TEXT,
  captured_at  TEXT NOT NULL,
  ingested_at  TEXT NOT NULL,
  trust_level  REAL NOT NULL DEFAULT 1.0,
  provenance   TEXT NOT NULL DEFAULT 'platform',
  tombstone    INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  title, body, content='items', content_rowid='rowid'
);

-- Keep FTS5 external-content index in sync with items.
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, body)
    VALUES('delete', old.rowid, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, body)
    VALUES('delete', old.rowid, old.title, old.body);
  INSERT INTO items_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;
