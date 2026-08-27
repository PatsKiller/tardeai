# ATM Pre-ACTIVE: Three Fixes Before Flipping Live

**Date:** 2026-05-22
**Session:** Dashboard visibility fixes for operator confidence

## Fix 1 (CRITICAL): Queue Preview PREDICTED column blank

**Root cause:** The API code was correct (committed earlier in the day) but the
portfolio_server process (PID 9083, started 09:19) was running the old code.
The server needed a restart to load the updated `api_v2.py`.

**Fix:** Restarted `tradeai-portfolio-server.service` via kill + user-level restart.
No code change required — the prediction logic was already working.

**Verification:** `curl /api/v2/atm/queue-preview` now returns `predicted_decision`
and `predicted_reason` for all 8 proposals. Sample:
- ARM, NWG, NVDA, AGNC, BCS, CMCSA: `would_approve` (all gates pass)
- MUD, SHMD: `would_defer` (B-1 bucket2 observation active)

## Fix 2 (HIGH): ATM page not in menu

**Status:** Already done. ATM is in the System menu as "ATM" at line 91 of
`Shell.tsx`: `{ to: '/automated-trade-mode', label: 'ATM' }`. Route registered
in `App.tsx` line 174. No change needed.

## Fix 3 (HIGH): Activity tiles don't reflect dry-run activity

**Root cause:** The tile computation only counted `approved`/`rejected` decisions,
ignoring `dry_run_approved`/`dry_run_rejected`. In DRY_RUN mode, the tiles
showed 0 for everything, even though ATM produced 36 dry_run_approved and
6 dry_run_rejected decisions today.

**Fix:**
- In DRY_RUN mode: "Would approve" counts `dry_run_approved`, "Would reject"
  counts `dry_run_rejected`, "Deferred" shown separately
- Each tile shows "dry run" suffix text and subtle amber border
- Hover tooltip: "DRY_RUN mode — these are decisions ATM would have made if ACTIVE"
- In ACTIVE mode: tiles unchanged (count approved/rejected as before)

**Commit:** `c106159`

**Current tile values (DRY_RUN mode, 2026-05-22):**
- Proposals seen: 56
- Would approve: 36 (dry run)
- Would reject: 6 (dry run)
- Deferred: 14 (dry run)
- Queue: 8

## Safety Verification
- Holdings: $1,200,388 / 47 positions (unchanged)
- ATM remains in DRY_RUN — not flipped
- min_classifier_health unchanged at 0.0
- No hardcoded broker names in changed files
