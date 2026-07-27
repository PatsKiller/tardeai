-- Active Trader Stage 5 · 0007 Moomoo market-data control tables (up)
-- Control + feature-snapshot state only. NO raw tick/book payload in PostgreSQL.
-- Applied to trade_ai_test ONLY.

CREATE TABLE md_subscription_state (
    subscription_id     UUID PRIMARY KEY,
    symbol              TEXT NOT NULL,
    stream_type         TEXT NOT NULL CHECK (stream_type IN ('QUOTE','K_1M','ORDER_BOOK','TICKER')),
    priority            TEXT NOT NULL CHECK (priority IN ('P0','P1','P2','P3')),
    state               TEXT NOT NULL CHECK (state IN ('REQUESTED','PENDING','ACTIVE','DEGRADED',
                          'ENTITLEMENT_MISSING','QUOTE_RIGHT_CONFLICT','QUOTA_DEFERRED','STALE',
                          'UNSUBSCRIBING','INACTIVE','FAILED')),
    reason              TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, stream_type)
);

CREATE TABLE md_entitlement_state (
    broker              TEXT NOT NULL DEFAULT 'MOOMOO',
    market              TEXT NOT NULL,
    tier                TEXT NOT NULL,
    entitled            BOOLEAN NOT NULL,
    evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (broker, market, tier)
);

CREATE TABLE md_data_quality (
    quality_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol              TEXT,
    stream_type         TEXT,
    state               TEXT NOT NULL CHECK (state IN ('HEALTHY','AGING','STALE','SEQUENCE_GAP',
                          'QUEUE_OVERFLOW','ENTITLEMENT_MISSING','QUOTE_RIGHT_CONFLICT',
                          'QUOTA_EXHAUSTED','RECONNECTING','MARKET_CLOSED','AUTHENTICATION_FAILED','DEGRADED')),
    detail              JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE md_feature_snapshot (
    snapshot_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol              TEXT NOT NULL,
    feature_version     TEXT NOT NULL,
    as_of_monotonic_ns  BIGINT NOT NULL,
    features            JSONB NOT NULL,
    input_refs          JSONB NOT NULL DEFAULT '{}'::jsonb,
    gap_state           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_md_feature_symbol ON md_feature_snapshot (symbol, as_of_monotonic_ns DESC);

CREATE TABLE md_replay_manifest (
    manifest_id         UUID PRIMARY KEY,
    utc_date            DATE NOT NULL,
    session             TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    stream_type         TEXT NOT NULL,
    schema_version      TEXT NOT NULL,
    row_count           BIGINT NOT NULL,
    min_ts              TIMESTAMPTZ,
    max_ts              TIMESTAMPTZ,
    wal_sha256          TEXT NOT NULL,
    parquet_sha256      TEXT,
    parquet_path        TEXT,
    verified            BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (utc_date, session, symbol, stream_type)
);

CREATE TABLE md_sequence_gap (
    gap_id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol              TEXT NOT NULL,
    stream_type         TEXT NOT NULL,
    reconnect_epoch     INTEGER NOT NULL,
    detail              JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE md_session_state (
    session_state_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market              TEXT NOT NULL,
    session             TEXT NOT NULL CHECK (session IN ('PRE','RTH','POST','CLOSED','OVERNIGHT')),
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE md_gateway_heartbeat (
    heartbeat_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opend_version       TEXT,
    sdk_version         TEXT,
    loopback_listening  BOOLEAN,
    logged_in           BOOLEAN,
    reconnect_epoch     INTEGER,
    trade_api_prohibited BOOLEAN NOT NULL DEFAULT true,
    detail              JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE md_observation_session (
    observation_id      UUID NOT NULL,
    session_date        DATE NOT NULL,
    symbols             JSONB NOT NULL DEFAULT '[]'::jsonb,
    events              BIGINT NOT NULL DEFAULT 0,
    gaps                INTEGER NOT NULL DEFAULT 0,
    reconnects          INTEGER NOT NULL DEFAULT 0,
    queue_overflows     INTEGER NOT NULL DEFAULT 0,
    wal_segments        INTEGER NOT NULL DEFAULT 0,
    parquet_segments    INTEGER NOT NULL DEFAULT 0,
    feature_equivalence BOOLEAN,
    disk_growth_bytes   BIGINT,
    verdict             TEXT NOT NULL DEFAULT 'PENDING' CHECK (verdict IN ('PENDING','PASS','FAIL')),
    evidence_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (observation_id, session_date)      -- no duplicate dates per observation
);

CREATE TABLE md_rate_governor_state (
    governor_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_scope       TEXT NOT NULL,
    action_class        TEXT NOT NULL CHECK (action_class IN ('PLACE','MODIFY_CANCEL','SNAPSHOT')),
    ceiling             INTEGER NOT NULL,
    ordinary            INTEGER NOT NULL,
    reserve             INTEGER NOT NULL,
    window_seconds      INTEGER NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ordinary + reserve = ceiling),
    UNIQUE (account_scope, action_class)
);
