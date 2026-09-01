Status:      HISTORICAL
as_of:       2026-06-05T12:04:01-04:00
Measured at: efcc51365 / not measured

---
## 202F-REVISED — diff is EVIDENCE ONLY (does NOT authorize bundled scheduling)
Ran `compare_portfolio_maintenance_outputs.py` against the completed bundled apply:
- **Output reproduction: PASS** (controller produced the legacy output set) — db backup ~996 MB
  `.sql.gz` (fresh), `portfolio_live.html` 544 KB (fresh), `holdings.json` 189 KB (fresh);
  `price_cache` + `db_retention` correctly EXCLUDED_NOT_RUN.
- **One FAIL:** `secrets_state_backup` rc=2 — controller-call arg bug (missing `{env|data}`), not a
  backup failure; fixed in the cadence redesign.
- **advisory-draft outputs observed: YES** (portfolio_orchestrator → recommendation/action-queue drafts).
- **LLM analyst step observed: YES** (portfolio_ai_analyst; monthly 15.6 min).
- **Deterministic vs non-deterministic:** backups/holdings deterministic (modulo timestamp); reports
  contain LLM-generated advisory text (non-deterministic).
- **Cadence mismatch blocker remains: YES.**
- **Safe to schedule bundled controller: NO.**
- **Safe to retire legacy lines: NO.**

This diff confirms the steps *run and reproduce outputs*, but per Option B the bundled controller is
NOT scheduled. Migration proceeds only via the cadence-aware controller (202G-REDESIGN), backup
cadence first.
