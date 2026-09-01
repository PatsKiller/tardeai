# STALE_DATA_RCA_AND_REMEDIATION_PLAN_2026-09-01

Status: ACTIVE  
as_of: 2026-09-01T00:00:00Z  
Measured at: 9929a208e7269bf0ddc0f20747e2ade62ca41f58

Joint RCA for Trade AI empty scanner, Finviz screener staleness (~102h), and silent Telegram
scalp/momentum alerts. Authority: `docs/audits/overnight/BISECT_TRADE_REGRESSION_2026-09-01.md`,
`AGENTS.md` §13.6.

---

## Symptom summary

| surface | observation | as_of evidence |
|---|---|---|
| Command Center Trade AI / Market Opportunities Scanner | `ticker_count=0`, `stale=true`, `cached_at=2026-08-28` | [VERIFIED] live API bisect |
| `/api/v2/scalp/live` | `signals=[]`, `ws_available=false` | [VERIFIED] live API |
| Health `data_source_stale` finviz | last success ~102h; error "Zero rows — cookie may be expired" | [VERIFIED] `/api/v2/health` |
| Health `data_source_stale` social_scalp | last success ~78h; "0 candidates" | [VERIFIED] `/api/v2/health` |
| Fused signals | 50 rows live same day | [VERIFIED] `/api/v2/signals/fused` |

**Verdict:** Not a frontend bug. Upstream Finviz screener chain + social_scalp Finviz gate share
one credential failure mode; session heal masked staleness without restoring tickers.

---

## Root cause chain

1. **Screener CSV auth** — `finviz_ingestion.py` and `finviz_screener_runner.py` required
   `FINVIZ_COOKIE` only. When cookie expired or returned HTTP 200 without CSV header, runs exited
   with zero rows. `FINVIZ_API_TOKEN` was already used on enrichment/social paths but **not**
   tried on screener export URLs.

2. **False-positive health** — `finviz_health_check.py` probed cookie-only; zero rows surfaced
   as "cookie may be expired" even when token auth would work `[VERIFIED]` 2026-09-01 on Elite
   export with `&auth=`.

3. **Orchestrator partial failure** — `trade_ai_orchestrator.py` continued with stale cache or
   zero-ticker run summaries; `warm_caches` / `trade_ai(force=True)` wrote empty cache.

4. **Session heal trap** — `heal_trade_ai_session_cache.py` patched `run_date` to today with
   `preserved_tickers:0`, clearing `stale` while leaving scanner empty (see AGENTS.md §13.6).

5. **social_scalp separate gate** — `social_ingest.py` has no Finviz dependency; zero social_scalp
   candidates with live mentions indicates `fetch_finviz_base` failure, not ingest silence.

---

## Remediation plan

### P1 — Shipped this wave

| item | change | proof |
|---|---|---|
| Token screener fallback | `finviz_ingestion.py`, `finviz_screener_runner.py` retry export with `&auth=` when cookie fails or absent | `tests/test_finviz_token_screener_fallback.py` |
| Operator documentation | AGENTS.md §13.6 + §7/§8/§9 cross-refs | `tests/test_agents_data_producers.py` |
| This RCA | `docs/audits/STALE_DATA_RCA_AND_REMEDIATION_PLAN_2026-09-01.md` | header + measured-at sha |

### P2 — Operator / next wave

| item | owner | notes |
|---|---|---|
| Rotate `FINVIZ_COOKIE` if login-page confirmed after token fallback also fails | operator | credentials are operator-only §17 |
| Fix `finviz_health_check.py` token probe | engineering | false-positive "cookie expired" |
| Fix `credential_monitor.check_finviz` false positive | engineering | align with dual-auth probe |
| `GET /api/v2/data-sources/finviz/credential-health` + CC banner | engineering | surface which auth mode is live |
| `health_agent` `finviz_cookie_expired` classification | engineering | distinguish cookie vs token vs rate-limit |

### P3 — Verification after deploy

Run from **served release** (not worktree alone):

1. `curl -s localhost:7777/api/v2/data-source-health | jq '.sources[] | select(.name|test("Finviz"))'`
2. Confirm orchestrator run_summary `ticker_count > 0` on next scheduled window
3. Confirm `trade_ai_cache.json` `_cached_at` advances with non-zero tickers
4. Confirm `social_scalp` last_success within lane cadence once Finviz gate passes

Dry-run before any live heal: `.venv/bin/python scripts/heal_trade_ai_session_cache.py --dry-run`

---

## Auto-remediation rules (same store)

Per AGENTS.md §0 rule 5 and §13.6:

- Report divergent paths (canonical vs release-local) with hashes — never pick one silently.
- Health Agent commands in `config/health_agent_policy.json` must write the **same store** the
  detector evaluated.
- Session heal is allowlisted for `trade_ai_session_stale` only; it must not be used as a Finviz
  substitute.

---

## Unpublished / deferred

- Live pin verification after merge+promote (operator-only deploy boundary)
- DB row-level last-success dates for `trade_ai_scans` / `scalp_scan_results` (blocked on secret
  hook in bisect session — Grok/operator follow-up)
- Frontend `FinvizCookieBanner.tsx` (P3 UX — not in this commit)
