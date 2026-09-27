-- 8-K exhibit text as dated primary evidence (2026-09-27).
--
-- Dell's 2026-09-01 8-K (Item 2.02) reached catalyst_events as a headline plus the
-- cover-page url only, so the symbol thesis and the options CIO packet said the
-- "$95B AI server backlog" / "$60.9B AI orders" had no Dell primary source while both
-- sit in exhibit 99.1 (the earnings press release) of that filing.
--
-- scripts/lib/sec_filing_documents.py stores one row per (accession, exhibit):
--   text   bounded plain text of the exhibit (60k chars)
--   facts  jsonb list of {category, sentence, amount_usd, amount_raw, figures}
-- Writer: scripts/sec_fundamentals_ingest.py --apply (F3 block).
-- Readers: symbol_thesis_evidence.retrieve_structured_sources (source_type sec_8k_ex99,
--          PRIMARY_REGULATORY) and options_cio_review.build_facts (primary_disclosures).
-- Additive only; the code probes for the table and treats its absence as "no documents".

CREATE TABLE IF NOT EXISTS sec_filing_documents (
    id           BIGSERIAL PRIMARY KEY,
    symbol       TEXT        NOT NULL,
    cik          TEXT        NOT NULL,
    accession    TEXT        NOT NULL,
    form         TEXT        NOT NULL,
    items        TEXT,
    exhibit      TEXT        NOT NULL,
    filing_date  DATE,
    doc_url      TEXT        NOT NULL,
    text         TEXT,
    facts        JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT sec_filing_documents_accession_exhibit_key UNIQUE (accession, exhibit)
);

CREATE INDEX IF NOT EXISTS sec_filing_documents_symbol_filed_idx
    ON sec_filing_documents (symbol, filing_date DESC);
