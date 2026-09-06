-- Identity tags on the research corpus.  ADDITIVE ONLY — no column is dropped,
-- renamed or rewritten, and nothing existing changes meaning.
--
-- Why each column exists:
--   subject_guid      this specific security (registry `subject_guid`)
--   issuer_guid       the ISSUER — survives ticker reassignment, share-class
--                     splits and re-listings. This is the join an agent uses for
--                     "everything about this company", and the reason tagging on
--                     `symbol` alone was never sufficient.
--   gics_sector       GICS sector, its OWN column. `category_sector` holds a
--                     thesis vocabulary (ai_chips, ai_datacenter, defense) that
--                     does not map onto GICS; merging them would collide two
--                     vocabularies in one field.
--   identity_status   CONFIRMED / CANDIDATE / UNRESOLVED — a CUSIP-confirmed tag
--                     and a bare-ticker-alias tag are not equal evidence.
--   identity_tagged_at  enables re-tagging as the registry improves. Without it a
--                     tag written today could never be distinguished from one
--                     written before the entity was confirmed.
--
-- ADD COLUMN IF NOT EXISTS still takes ACCESS EXCLUSIVE. Run it once, off-peak,
-- not from a recurring job — that is exactly how taxonomy_tagger took the table
-- down on 2026-07-02 (9 recorded LockNotAvailable failures against live readers).

SET lock_timeout = '5s';

ALTER TABLE hermes_research_intelligence
  ADD COLUMN IF NOT EXISTS subject_guid       UUID,
  ADD COLUMN IF NOT EXISTS issuer_guid        UUID,
  ADD COLUMN IF NOT EXISTS gics_sector        TEXT,
  ADD COLUMN IF NOT EXISTS identity_status    TEXT,
  ADD COLUMN IF NOT EXISTS identity_tagged_at TIMESTAMPTZ;

-- taxonomy_tagged_at gives the `no_match` sentinel a shelf life. Without it the
-- sentinel is permanent: taxonomy_tagger selects `WHERE category_content IS NULL`,
-- so a row marked no_match is never reconsidered, by any classifier, ever.
-- ADD COLUMN with no default is a metadata-only change on PG11+ even on the
-- 846,787-row content_embeddings, so this is cheap despite the table size.
ALTER TABLE hermes_research_intelligence
  ADD COLUMN IF NOT EXISTS taxonomy_tagged_at TIMESTAMPTZ;
ALTER TABLE content_embeddings
  ADD COLUMN IF NOT EXISTS taxonomy_tagged_at TIMESTAMPTZ;

ALTER TABLE news_articles
  ADD COLUMN IF NOT EXISTS subject_guid       UUID,
  ADD COLUMN IF NOT EXISTS issuer_guid        UUID,
  ADD COLUMN IF NOT EXISTS gics_sector        TEXT,
  ADD COLUMN IF NOT EXISTS identity_status    TEXT,
  ADD COLUMN IF NOT EXISTS identity_tagged_at TIMESTAMPTZ;

-- The three access paths an agent actually uses. CONCURRENTLY so building them
-- does not block the readers this corpus exists to serve.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hri_issuer_guid  ON hermes_research_intelligence (issuer_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hri_subject_guid ON hermes_research_intelligence (subject_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hri_gics_sector  ON hermes_research_intelligence (gics_sector);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_issuer_guid ON news_articles (issuer_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_gics_sector ON news_articles (gics_sector);
