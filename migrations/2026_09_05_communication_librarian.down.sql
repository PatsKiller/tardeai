-- Down migration for Librarian retention (Phase 6).
DROP TABLE IF EXISTS communication_knowledge_candidates;
DROP TABLE IF EXISTS communication_tombstones;
DROP TABLE IF EXISTS communication_retention_decisions;
