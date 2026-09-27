-- Reverse of 2026_09_27_sec_filing_documents.sql. Drops stored exhibit text and facts;
-- the ingest re-fetches them from sec.gov on the next --apply run.
DROP INDEX IF EXISTS sec_filing_documents_symbol_filed_idx;
DROP TABLE IF EXISTS sec_filing_documents;
