-- SPDX-License-Identifier: EUPL-1.2
-- Initial schema (spec §7.2); `source_status` holds one row per shared collection. Times are UTC, `YYYY-MM-DDTHH:MM:SSZ`; JSON columns hold canonical JSON.

CREATE TABLE pairing (
    key_id      TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    secret      BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    revoked_at  TEXT
) STRICT;

CREATE TABLE collector_grant (
    key_id      TEXT NOT NULL REFERENCES pairing (key_id),
    collector   TEXT NOT NULL,
    allowed     INTEGER NOT NULL,
    PRIMARY KEY (key_id, collector)
) STRICT;

CREATE TABLE subscription (
    key_id      TEXT NOT NULL REFERENCES pairing (key_id),
    uid         TEXT NOT NULL,
    spec        TEXT NOT NULL,
    collection  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    origin      TEXT NOT NULL,
    team_name   TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (key_id, uid)
) STRICT;

CREATE TABLE source_status (
    id              TEXT PRIMARY KEY,
    collector       TEXT NOT NULL,
    last_attempt    TEXT,
    last_success    TEXT,
    error           TEXT,
    failing_since   TEXT
) STRICT;

CREATE TABLE item (
    collection  TEXT NOT NULL,
    key         TEXT NOT NULL,
    hash        TEXT NOT NULL,
    fields      TEXT NOT NULL,
    url         TEXT,
    fetched_at  TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    gone_at     TEXT,
    PRIMARY KEY (collection, key)
) STRICT;

CREATE TABLE reported (
    key_id          TEXT NOT NULL,
    uid             TEXT NOT NULL,
    key             TEXT NOT NULL,
    hash            TEXT NOT NULL,
    fields          TEXT NOT NULL,
    url             TEXT,
    fetched_at      TEXT NOT NULL,
    first_reported  TEXT NOT NULL,
    last_changed    TEXT NOT NULL,
    gone_at         TEXT,
    PRIMARY KEY (key_id, uid, key)
) STRICT;

CREATE TABLE package (
    key_id      TEXT NOT NULL,
    uid         TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    period_to   TEXT NOT NULL,
    data        BLOB,  -- NULL once purged (EF-45): the number stays known, and answers 410
    PRIMARY KEY (key_id, uid, seq)
) STRICT;

CREATE TABLE job (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    key_id      TEXT NOT NULL,
    uid         TEXT NOT NULL,
    argument    TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT,
    seq         INTEGER,
    result      BLOB
) STRICT;
CREATE INDEX job_lookup ON job (kind, key_id, uid, argument);

CREATE TABLE event (
    id      INTEGER PRIMARY KEY,
    at      TEXT NOT NULL,
    code    TEXT NOT NULL,
    params  TEXT NOT NULL
) STRICT;
