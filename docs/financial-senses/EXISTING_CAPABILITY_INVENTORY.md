# Existing capability inventory (Phase 0)

Status:      ACTIVE
as_of:       2026-08-16T22:32:42-04:00
Measured at: efcc51365 / not measured

Inventory of what Trade AI already has, what this branch reuses, and what is
genuinely missing. This is the evidence that the SEC adapter is a facade over
the existing pipeline, not a second ingestion system.

## Git truth at branch creation

- `origin/main` (fresh, post PR #339 merge): `968dafb6beda21aa11aa4cedeb7c9c3920c3fec4`
- Branch: `feature/financial-senses-parallel-v1` (created from `origin/main`)
- Worktree: `/home/johnclaw/tardeai-financial-senses-parallel-v1`
- Other agent branch: `feature/agent-intelligence-foundation` (worktree
  `/home/johnclaw/tradeai-wt-cio-decision-truth`), 3 commits touching
  `docs/agent-intelligence/**`, `scripts/lib/agent_*.py`, `tests/test_agent_*.py`.

## Existing SEC capability

### Canonical ingestion

- `scripts/sec_data_ingest.py` — the single SEC ingestion path:
  - `_get_cik(symbol)` — ticker → CIK via `company_tickers.json`
  - `fetch_form4(symbol, limit)` — Form 4 fetch from `data.sec.gov/submissions/`
  - `ingest_form4(symbols, limit)` — writes `sec_form4` table
  - `get_sec_intel(symbol)` — reads `sec_form4` + `sec_13f` for agent prompt
  - User-Agent `TradeAI john@jwwhiting.com`, ~0.15s sleep rate limit

### Canonical store (PostgreSQL `trade_ai`)

- `sec_form4` — symbol, filer_name, filer_relation, transaction_type,
  filing_date, sec_url, strategy_tags, agent_tags (written by `ingest_form4`)
- `sec_13f` — institution, shares, value_thousands, change_pct, report_date,
  symbol (read by `get_sec_intel`)
- `sec_xbrl` — counted by `test()` but no writer found in `scripts/`

### Supporting modules

- `scripts/sec_form4_source_maturity.py` — read-only source-maturity scorer +
  pure insider-context classifier.
- `scripts/run_sec_form4_momentum_context.py` — scheduled wrapper (the canonical
  scheduler; NOT duplicated by this branch).

### Gaps (addressed by read-only extension, not a second pipeline)

- No company-facts (XBRL) reader.
- No filing-metadata reader.
- No deterministic filing-diff / compare-filing-facts.
- `sec_13f` / `sec_xbrl` population path not found in `scripts/` (treated as
  `NOT_INGESTED` when empty, never fabricated).

## Existing macro / identity / stress / factor / evidence

| Area | Existing | Reused / gap |
|---|---|---|
| FRED / ALFRED | none | gap — new read-only provider |
| Macro vintage | none | gap — vintage-aware provider |
| Instrument identity | `cio_identity_resolver.py` is **agent** identity (guardian/ledger), not instrument | gap — new `identity.py` |
| FIGI / CUSIP / ISIN | none | gap |
| Portfolio stress | `stress_test.json` is a Category-2 output; no reusable engine | gap — new `stress_engine.py` |
| Factor | `cio_reverse_factor_backfill.py` (reverse factor backfill) | candidate, not imported |
| Evidence | `cio_evidence_ref.py`, `cio_evidence_spine.py`, `cio_domain_evidence.py` | candidate, not imported (graph is new) |
| Claim graph | none | gap — new `evidence_graph.py` |

## AIF overlap

The other agent owns `docs/agent-intelligence/**`, `scripts/lib/agent_*.py`,
`tests/test_agent_*.py`, and the central MCP gateway. This branch does not touch
those paths. Collision plan: dedicated `financial_senses` namespace + a
provider manifest for later registration.
