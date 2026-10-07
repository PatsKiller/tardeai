#!/bin/sh
# PROPOSAL ONLY. Runs once on a fresh Postgres volume: a non-superuser owner for n8n's schema.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
CREATE ROLE n8n_app LOGIN PASSWORD '$N8N_APP_PASSWORD' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER SCHEMA public OWNER TO n8n_app;
GRANT ALL ON SCHEMA public TO n8n_app;
SQL
