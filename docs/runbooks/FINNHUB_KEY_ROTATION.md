# Finnhub API Key Rotation Runbook

Status:      ACTIVE
as_of:       2026-08-19T12:02:14-04:00
Measured at: efcc51365 / not measured

**Why:** `data_source_health` recorded `finnhub` with `last_error: HTTP 401` — Finnhub is
actively rejecting the stored `FINNHUB_API_KEY`. A 401 is a credential failure, not a
transient ingestion stall: no producer retry can clear it, so the health agent now surfaces
it as a distinct `data_source_auth_failed` finding (`never_auto`), not a generic
`data_source_stale` auto-retry.

## Symptoms (what the operator sees)

- Health Agent → Data Quality: `data source 'finnhub' auth failed (HTTP 401)`.
- Finnhub news/enrichment lanes stop contributing articles (`symbol_enrichment.py`,
  `news_ingestion.py`).
- The older generic finding (`data source 'finnhub' stale: last success 393.0h ago`)
  was auto-retrying `external_market_data_ingest.py --quotes`, which never touches
  Finnhub — a no-op loop. That path is now gated off for auth failures.

## Resolution (operator action — requires a Finnhub account)

### 1. Get a new key
Finnhub dashboard (`https://finnhub.io/dashboard`) → API key → regenerate/copy a fresh
token. Finnhub free-tier keys can be re-issued from the same dashboard.

### 2. Store it (Bitwarden SM is source of truth)
Preferred — assisted rotate (prompts for the value via TTY, writes SM, re-renders, probes):

```bash
.venv/bin/python scripts/secrets/rotate.py FINNHUB_API_KEY
```

Alternative — edit the `FINNHUB_API_KEY` secret in the Bitwarden SM project
`trade-ai-prod` (web console or `bws secret edit`), then re-render:

```bash
.venv/bin/python scripts/secrets/render_env.py --now
```

### 3. Validate the new key live

```bash
.venv/bin/python scripts/secret_validators.py FINNHUB_API_KEY
# expect:  valid  FINNHUB_API_KEY  HTTP 200
```

### 4. Clear the stale finding
The `finnhub` health marker (`data_source_health.finnhub`) is reported by
`symbol_enrichment.pull_finnhub_news`, which runs inside the enrichment stage of
`trade_ai_orchestrator.py` — **not** `news_ingestion.py`. After rotating the key,
the marker clears automatically on the next enrichment/orchestrator cycle, so no
manual step is required. To force it immediately, run the orchestrator with a
time-appropriate `--run-label` (see `remediate_pipeline_failures.py` for the ET-hour
→ label map), e.g.:

```bash
flock -n /tmp/screener_pm.lock .venv/bin/python scripts/trade_ai_orchestrator.py \
  --run-label early --skip-market-check --no-llm --no-alerts --allow-underfilled
```

The next health-agent scan (≤ next cycle) drops the `data_source_auth_failed` finding.

## Verification

```bash
# Confirm the source is healthy again (last_success_at recent, last_error NULL):
.venv/bin/python -c "
import psycopg2, os
for line in open('.env'):
    if line.startswith('DB_PASSWORD='): pw = line.split('=',1)[1].strip()
conn = psycopg2.connect(host='localhost', user='trade_ai', password=pw, dbname='trade_ai')
cur = conn.cursor()
cur.execute(\"SELECT source_key, status, last_success_at, last_error FROM data_source_health WHERE source_key='finnhub'\")
print(cur.fetchone())
"
```

## Notes

- `scripts/secret_validators.py` calls Finnhub's `/quote?symbol=AAPL` — the cheapest
  authenticated endpoint, no quota consumed. A `quota_or_billing` result means the key is
  recognized but the plan is exhausted (different from 401).
- Do not commit the key. `.env` and `data/` are gitignored; the repo is public. Run
  `bash scripts/check_secret_exposure.sh` after any rotation as standing hygiene.
- The fix is operator-side only. The code path was correct — Finnhub uses a `token=`
  query parameter everywhere, and the key was present but rejected.
