# Protective-Stop Submit — Confirm Response Handling Fix (2026-06-21)

## Symptom
After typing the ticker / entering the 6-digit code, the NOC protective-stop modal "appeared unable to
submit" — it showed a generic failure and never reported what actually went wrong.

## Root cause (two distinct issues)

1. **Real failure (backend / external):** every NOC submit reached Schwab and was rejected by the
   Schwab OAuth layer:
   ```
   invalid_grant: "Refresh token is invalid, expired or revoked"
   ```
   The 2FA flow worked perfectly (both channels confirmed all three attempts); the order died at the
   Schwab transport because the refresh token had expired. **Fix is operator-side re-auth** —
   `python3 scripts/schwab_token_manager.py reauth-url schwab_taxable` + the manual browser OAuth login
   (Schwab requires a fresh login each cycle; it cannot be automated). NOT fixed in code.

2. **UI masked the cause:** on a submit error the confirm endpoint returns
   `{"ok": false, "stage": "submit", "status": "error", "result": {"error": "<real cause>"}, ...}` —
   the actual message is nested under `result.error`. The card only read top-level `r.error`/`r.reason`,
   so it fell through to a useless `⛔ confirmation failed`. **Fixed here.**

## Changes (UI + diagnostics only — NO 2FA bypass, NO transport change)

`apps/command-center-v3/src/components/PositionDecisionCard.tsx`
- `unwrapApi(j)` — tolerate both raw and `{ok,data}`-wrapped responses.
- `apiReason(j)` — surface the REAL reason, digging into `result.error` first.
- `_requestStop()` — unwraps; sets intent from `r.intent_id`; explicit blocker when `intent_id` is
  missing; shows `Intent <8> · expires Nmin · approve by ticker or 6-digit code · one channel is enough`.
- `_confirmStop()` — unwraps; guards on a missing intent; **strict** success (only a real
  `submitted`/`filled` + order id claims success); a `stage:submit` + `status:error` now shows
  `⛔ approved, but Schwab rejected the submit: <result.error>` instead of a fake success or a vague fail.
- Button text `place` → `approve + submit`; helper line: *"This still requires this typed ticker or
  6-digit code. No agent bypass."*

`scripts/verify_protective_stop_submit_flow.py` (new, read-only)
- Asserts `approval_service.REQUIRED_CHANNELS` (and flags an env override rather than silently weakening),
  exercises the pure `build_order_spec` / `order_summary` builders, and confirms `load_intent` is a safe
  no-op for a fake id. Never requests, confirms, or submits. JSON output via `--json`.

## Verifier output
```json
{"ok": true, "required_channels": 1, "required_channels_env_override": false,
 "order_spec_builds": true, "order_summary_works": true, "load_intent_safe_none": true,
 "no_submit_performed": true, "blockers": [], "warnings": []}
```

## Safety
Per-order 2FA is untouched: the operator must still type the ticker OR enter the 6-digit code; no
auto-confirm, no one-click live order, no change to `REQUIRED_CHANNELS`, no Schwab transport change, no
`.env` edit. A live submit was **not** tested in code (it would fail on the expired token anyway, and no
operator confirmation was given for a test order).
