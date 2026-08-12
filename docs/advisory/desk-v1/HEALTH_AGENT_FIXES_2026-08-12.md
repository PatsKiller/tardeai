# Health Agent Fixes — release manifest + Finnhub 401 (2026-08-12)

Two stale/unactionable health findings fixed in this sprint.

## 1. `release_manifest_fail` (stale false positive)

**Root cause:** `scripts/health_agent.py` mirrors the `Status:` line from
`docs/project/RELEASE_MANIFEST_LATEST.md`. That manifest was last generated
2026-08-10 while `validate_schwab_write_policy.py` reported `24/26 guards green`
(FAIL). The validator has since gone `27/27 guards green`, but the deploy script
blindly rsynced the stale `FAIL` manifest into every release.

**Fix:**
- Regenerated the canonical manifest — now `Status: WARN` (dirty runtime files
  only, no live-adjacent dirt), `validate_schwab_write_policy.py: 27/27 guards green`.
- `scripts/deploy_portfolio_server.sh` now has a `[4b/8]` step that copies the
  canonical (fresh) `RELEASE_MANIFEST_LATEST.md` over the rsync snapshot, so a
  release can never again serve a stale `FAIL`.

## 2. Finnhub `data_source_stale` (HTTP 401) — no-op auto-retry

**Root cause:** `FINNHUB_API_KEY` is invalid/expired (Finnhub returns HTTP 401).
The health agent classified this as a generic `data_source_stale` and auto-retried
`scripts/external_market_data_ingest.py --quotes` — a script that never touches
Finnhub — looping forever.

**Fix (code):** `collect_data_source_health` now emits a distinct
`data_source_auth_failed` finding (critical, `never_auto`) when `last_error`
contains 401/403, mirroring the existing `finviz_cookie_expired` pattern. The type
is added to `never_auto_remediate`, and the finding carries a `reauth_cmd`
(`rotate.py` / `render_env.py` + `secret_validators.py`). The operator rotates the
key; auto-retry can never clear a credential failure.

**Fix (operator):** see [FINNHUB_KEY_ROTATION.md](../../runbooks/FINNHUB_KEY_ROTATION.md).
