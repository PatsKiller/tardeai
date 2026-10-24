-- OPERATOR REVIEW/APPLY ONLY. Existing CIO store/table, no new authority or store.
-- Fact-only InstrumentRecords carry identity + research and no fabricated judgment.
-- The normal prospect branch retains every required judgment/expiry validation.
-- Source release may use flag-off JSONL. PG-enabled fact writes fail before append
-- until this capability is present. Never run this file from a lane or a test.
BEGIN;
ALTER TABLE cio_prospect ALTER COLUMN issuer_guid DROP NOT NULL;
ALTER TABLE cio_prospect ALTER COLUMN stage DROP NOT NULL;
ALTER TABLE cio_prospect ALTER COLUMN stance DROP NOT NULL;
ALTER TABLE cio_prospect ALTER COLUMN conviction DROP NOT NULL;
ALTER TABLE cio_prospect ALTER COLUMN evidence_at DROP NOT NULL;
ALTER TABLE cio_prospect ALTER COLUMN expires_at DROP NOT NULL;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='cio_prospect'::regclass
                 AND conname='cio_prospect_record_kind_ck') THEN
  ALTER TABLE cio_prospect ADD CONSTRAINT cio_prospect_record_kind_ck CHECK (
   (coalesce(provenance->>'record_kind','PROSPECT')='FACTS_ONLY' AND stage IS NULL AND stance IS NULL AND conviction IS NULL
    AND evidence_at IS NULL AND expires_at IS NULL AND stage_changed_at IS NULL AND stage_evidence IS NULL
    AND next_action IS NULL AND next_trigger IS NULL AND catalyst_grade IS NULL
    AND coalesce(jsonb_typeof(research->'company_facts'),'null')='object'
    AND coalesce(research->'company_facts'->>'schema','')='CIOCompanyFacts@v1'
    AND coalesce(research->'company_facts'->>'security_guid','')=security_guid::text)
   OR
   (provenance->>'record_kind' IS DISTINCT FROM 'FACTS_ONLY' AND issuer_guid IS NOT NULL AND stage IS NOT NULL AND stance IS NOT NULL
    AND conviction IS NOT NULL AND evidence_at IS NOT NULL AND expires_at IS NOT NULL)
  );
 END IF;
END $$;
COMMENT ON CONSTRAINT cio_prospect_record_kind_ck ON cio_prospect IS
 'FACTS_ONLY identity/research rows are not prospects; judged records still require all original fields.';
COMMIT;
