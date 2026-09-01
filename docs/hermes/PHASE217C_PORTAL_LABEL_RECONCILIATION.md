# PHASE 217C — Portal Label Reconciliation (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T18:49:05-04:00
Measured at: efcc51365 / not measured

Updated `/api/v2/hermes/researcher-matrix` to read the canonical snapshot (no more stale hardcoded labels):
- Internal deep lane: was "designed (not enabled)" → now "**built + nightly-scheduled** (advisory/staging, operator-run)" + timer_enabled + next_run + model.
- External lanes now show LIVE status: Grok=live(headless ready); Codex=authed·unavailable (interactive-only on 0.16.0); Claude=authed·credits_required; Consensus=designed.
- serverops chat profile label: "HOLD — P1: 18 tools enabled, hardening required" (was "future").
- Added canonical_docs pointer. Read-only; no execution controls added; no v2 UI.
