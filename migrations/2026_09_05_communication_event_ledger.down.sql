-- Down migration for CommunicationEvent ledger v1.
DROP TABLE IF EXISTS communication_entity_links;
DROP TABLE IF EXISTS communication_outbox;
DROP TABLE IF EXISTS communication_events;
