-- Operator <-> agent conversation, tagged to the identity spine.
--
-- Supersedes the first cut, `inbound_operator_questions`, which stored only the
-- operator's half. A question and its answer are ONE exchange: storing the
-- question alone loses what the agent actually said about the issuer, which is
-- most of the value — an agent reading its own past answers is the point of
-- persistent memory, and an operator's follow-up ("no, I meant the weekly") is
-- meaningless without the turn it replies to.
--
-- GRAIN: one row per (turn, resolved entity).
-- A turn resolving to two symbols writes two rows; a turn resolving to none
-- still writes ONE row with null guids, because an unresolvable turn is the
-- measurement of what the spine cannot reach.

CREATE TABLE IF NOT EXISTS operator_conversation_turns (
    id                  BIGSERIAL PRIMARY KEY,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- who spoke. Without this the corpus is unreadable: an agent cannot tell its
    -- own words from the operator's, and would learn from its own output.
    role                TEXT        NOT NULL CHECK (role IN ('operator', 'agent')),

    channel             TEXT        NOT NULL DEFAULT 'telegram',
    chat_id             TEXT,
    message_id          BIGINT,

    -- thread linkage. `thread_id` is the message_id of the exchange's ROOT, so
    -- every turn in one back-and-forth shares it and the whole conversation is a
    -- single WHERE clause rather than a reconstruction.
    thread_id           TEXT,
    reply_to_message_id BIGINT,
    turn_index          INTEGER,

    text                TEXT        NOT NULL,

    -- identity, from the spine. NULL means unresolved, not zero.
    symbol              TEXT,
    subject_guid        UUID,
    issuer_guid         UUID,
    identity_status     TEXT,
    matched_via         TEXT,
    matched_text        TEXT,

    topics              TEXT[]      NOT NULL DEFAULT '{}',
    unresolved_mentions TEXT[]      NOT NULL DEFAULT '{}',

    schema_version      TEXT        NOT NULL DEFAULT 'OperatorConversationTurn@v1',
    authority           TEXT        NOT NULL DEFAULT 'READ_ONLY_ADVISORY'
);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oct_issuer_guid  ON operator_conversation_turns (issuer_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oct_subject_guid ON operator_conversation_turns (subject_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oct_thread       ON operator_conversation_turns (thread_id, turn_index);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oct_occurred     ON operator_conversation_turns (occurred_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oct_topics       ON operator_conversation_turns USING GIN (topics);

-- Carry the first cut forward rather than dropping it: those rows are real
-- operator questions and deleting them to tidy a schema would lose evidence.
INSERT INTO operator_conversation_turns
    (occurred_at, role, channel, chat_id, message_id, thread_id, text,
     symbol, subject_guid, issuer_guid, identity_status, matched_via,
     matched_text, topics, unresolved_mentions)
SELECT received_at, 'operator', channel, chat_id, message_id,
       message_id::text, question_text,
       symbol, subject_guid, issuer_guid, identity_status, matched_via,
       matched_text, topics, unresolved_mentions
FROM inbound_operator_questions
WHERE NOT EXISTS (
    SELECT 1 FROM operator_conversation_turns t
     WHERE t.message_id = inbound_operator_questions.message_id
       AND t.role = 'operator');
