# SearXNG Phase 17A — Manual Query Wrapper Architecture

**Date:** 2026-05-31
**Status:** APPROVED — manual-only, file-only

---

## Purpose

A controlled operator-invoked wrapper that queries the local SearXNG instance and saves sanitized results to files. This is the first interface between Trade AI project tooling and SearXNG.

---

## Wrapper Scope

| Property | Value |
|----------|-------|
| Script | `scripts/searxng_manual_query.py` |
| Invocation | Manual CLI only |
| SearXNG endpoint | http://127.0.0.1:18888/search |
| Output format | JSON + Markdown summary |
| Output directory | `data/searxng_queries/` |
| DB writes | NONE |
| Embeddings | NONE |
| Ingestion | NONE |
| Promotion | NONE |
| Autonomous use | PROHIBITED |
| Scheduled use | PROHIBITED |

---

## Allowed Query Types

- General market research queries
- Architecture / technology questions
- Strategy research (non-personal)
- Financial instrument factual lookups

## Prohibited Query Types

- Personal financial data (accounts, SSN, tax ID)
- Broker credentials or API keys
- Internal passwords or secrets
- Other personally identifiable information

---

## Output Format

Per query, 3 files are created in `data/searxng_queries/<timestamp>/`:

1. **query_summary.md** — Human-readable markdown with query, result count, top results
2. **query_results_sanitized.json** — Sanitized result list (title, url, snippet only)
3. **query_metadata.json** — Query string, timestamp, engines used, result count, SearXNG version

---

## Sanitization Rules

Stripped from output:
- HTTP headers / cookies
- User tokens / session IDs
- IP addresses (server or client)
- Raw HTML content
- SearXNG internal engine errors/debug
- Any string matching secret patterns (sk-, AKIA, ghp_, etc.)

Preserved:
- Result title
- Result URL
- Result snippet (truncated to 500 chars max)
- Engine name
- Category

---

## Query Privacy Policy

- Queries are forwarded to upstream search engines by SearXNG (Google, DDG, Bing, etc.)
- No query logging to Trade AI database
- No query history committed to git
- Output files in `data/searxng_queries/` are gitignored
- No Drive sync of query outputs

---

## No-Ingestion Boundary

The wrapper MUST NOT:
- Call any Trade AI API endpoint
- Write to any database table
- Call Hermes gateway or chat proxy
- Create embeddings
- Trigger any pipeline
- Import or use any Trade AI module that writes state

---

## Future Gates

| Gate | Enables | Status |
|------|---------|--------|
| 17B+ | Manual wrapper implementation | THIS PHASE |
| 18A | hermes_browse_proxy SearXNG backend | NOT APPROVED |
| 19A | Source discovery dry-run (no ingestion) | NOT APPROVED |
| 20A | Automated research with ingestion | NOT APPROVED |
| 21A | Tailscale/FQDN exposure | NOT APPROVED |
