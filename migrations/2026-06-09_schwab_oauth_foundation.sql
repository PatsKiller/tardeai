-- 2026-06-09_schwab_oauth_foundation.sql — Schwab read-only foundation (Phase 1). ADDITIVE only.
-- No plaintext tokens ever. Encryption key lives outside the DB (config/broker_credentials.env, 0600).
-- Does NOT enable any write path; Schwab accounts stay conservative.

CREATE TABLE IF NOT EXISTS broker_oauth_tokens (
    id                 BIGSERIAL PRIMARY KEY,
    account_key        TEXT NOT NULL,
    broker             TEXT NOT NULL DEFAULT 'schwab',
    environment        TEXT NOT NULL DEFAULT 'live',
    access_token_enc   TEXT,                 -- Fernet ciphertext; NEVER plaintext
    refresh_token_enc  TEXT,                 -- Fernet ciphertext; NEVER plaintext
    access_expires_at  TIMESTAMPTZ,
    refresh_expires_at TIMESTAMPTZ,          -- GATE A: first-class state (Schwab ~7d, no prog. renewal)
    next_reauth_due_at TIMESTAMPTZ,          -- when a manual browser re-auth must happen
    token_version      INT DEFAULT 1,
    rotation_count     INT DEFAULT 0,
    degraded           BOOLEAN DEFAULT TRUE, -- fail-closed default until freshness is proven
    last_error         TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_key, broker, environment)
);

-- append-only; fingerprints/status ONLY, never token material
CREATE TABLE IF NOT EXISTS broker_oauth_token_audit (
    id            BIGSERIAL PRIMARY KEY,
    account_key   TEXT NOT NULL,
    broker        TEXT NOT NULL DEFAULT 'schwab',
    event         TEXT NOT NULL,            -- access_refresh | refresh_rotation | reauth | expiry | degrade | alert
    token_fingerprint TEXT,                 -- sha256 prefix of ciphertext, never the token
    status        TEXT,
    detail        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS schwab_account_links (
    id              BIGSERIAL PRIMARY KEY,
    account_key     TEXT NOT NULL UNIQUE,
    schwab_hash_enc TEXT,                    -- encrypted Schwab account hash; never plaintext
    account_type    TEXT,                    -- rollover_ira | roth_ira | taxable
    masked_last4    TEXT,                    -- display only, e.g. ****1234
    verified        BOOLEAN DEFAULT FALSE,
    last_verified_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- optional, size-limited, secret-redacted raw read payloads for audit/backfill
CREATE TABLE IF NOT EXISTS schwab_api_raw_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    account_key   TEXT,
    endpoint      TEXT,                      -- positions | transactions | quote | ...
    payload_redacted JSONB,                  -- account numbers/tokens redacted before store
    byte_size     INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- holdings basis-divergence flags (GATE B: flag, never overwrite tax-grade basis)
CREATE TABLE IF NOT EXISTS schwab_basis_divergence (
    id            BIGSERIAL PRIMARY KEY,
    account_key   TEXT,
    symbol        TEXT NOT NULL,
    api_avg_price NUMERIC,
    stored_basis  NUMERIC,
    divergence_pct NUMERIC,
    resolved      BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- degraded read-only sync status (GATE B: failed fetch -> NO-OP + degraded record)
CREATE TABLE IF NOT EXISTS schwab_sync_history (
    id            BIGSERIAL PRIMARY KEY,
    account_key   TEXT,
    status        TEXT NOT NULL,             -- ok | degraded_noop | rejected_sanity | rejected_postwrite
    reason        TEXT,
    position_count INT,
    total_value   NUMERIC,
    wrote_holdings BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
