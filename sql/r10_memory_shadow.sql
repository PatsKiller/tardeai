-- R10 M2 Postgres institutional-memory SHADOW schema.
-- DESIGNED / source only. Do NOT apply to production under this PR.
-- No Neo4j. No production RLS activation. tenant_id NOT NULL on every tenant-owned table.

-- Status: DESIGNED + IMPLEMENTED_SOURCE (DDL). Not MERGED as live. Not LIVE.

CREATE SCHEMA IF NOT EXISTS memory_r10_shadow;

CREATE TABLE IF NOT EXISTS memory_r10_shadow.memory_identity (
    memory_id          uuid PRIMARY KEY,
    tenant_id          text NOT NULL,
    namespace          text NOT NULL,
    subject_guid       text NOT NULL,
    predicate          text NOT NULL,
    created_at         timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_r10_shadow.memory_fact (
    memory_version_id  uuid PRIMARY KEY,
    memory_id          uuid NOT NULL REFERENCES memory_r10_shadow.memory_identity(memory_id),
    tenant_id          text NOT NULL,
    namespace          text NOT NULL,
    subject_guid       text NOT NULL,
    predicate          text NOT NULL,
    object_json        jsonb NOT NULL,
    category           text NOT NULL,
    valid_from         timestamptz NOT NULL,
    valid_to           timestamptz,
    tx_from            timestamptz NOT NULL,
    tx_to              timestamptz,
    status             text NOT NULL,
    confidence         text NOT NULL,
    source_type        text NOT NULL,
    source_id          text NOT NULL,
    source_as_of       timestamptz NOT NULL,
    asserted_by        text NOT NULL,
    trace_id           text,
    evidence_refs      jsonb NOT NULL DEFAULT '[]'::jsonb,
    contradiction_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    embedding_ref      text,
    created_at         timestamptz NOT NULL,
    CHECK (valid_to IS NULL OR valid_from < valid_to),
    CHECK (tx_to IS NULL OR tx_from < tx_to)
);

CREATE TABLE IF NOT EXISTS memory_r10_shadow.entity_identity (
    entity_guid        text PRIMARY KEY,
    tenant_id          text NOT NULL,
    kind               text NOT NULL,
    alias              text
);

CREATE TABLE IF NOT EXISTS memory_r10_shadow.relationship_candidate (
    candidate_relationship_id uuid PRIMARY KEY,
    tenant_id          text NOT NULL,
    source_entity_guid text NOT NULL,
    target_entity_guid text NOT NULL,
    relationship_hypothesis text NOT NULL,
    similarity         double precision,
    status             text NOT NULL,
    authoritative      boolean NOT NULL DEFAULT false
);

-- RLS is DESIGNED for SHADOW only. Do not ENABLE in production in this PR.
-- ALTER TABLE ... ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY tenant_isolation ON ... USING (tenant_id = current_setting('app.tenant_id', true));

COMMENT ON SCHEMA memory_r10_shadow IS 'SHADOW only. Writers not cut over. Neo4j not installed.';
