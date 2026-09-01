# Schwab Token Health Check — Re-auth Needed Up Front (2026-06-21)

Status:      HISTORICAL
as_of:       2026-06-21T21:20:56-04:00
Measured at: efcc51365 / not measured

## Why
The NOC protective stop failed at submit with `invalid_grant: "Refresh token is invalid, expired or
revoked"` — Schwab had revoked the refresh token server-side, but the DB freshness timestamp still read
"valid for ~2 days," so nothing warned the operator until *after* a failed live order. This adds a
ground-truth health check that flags re-auth **before** an order attempt.

## Root bug also fixed
`schwab_token_manager.health()` had `base["degraded"] = bool(degraded_flag) and False or False` — which
**always evaluates to False**, masking any persisted degraded flag whenever the timestamp looked valid.
That's the exact "green when dead" path. Now it honors the stored flag:
`base["degraded"] = bool(degraded_flag)`.

## Mechanism (three layers)

1. **Reactive marking** — `schwab_token_manager.mark_degraded()` + `is_auth_failure()` (matches
   `invalid_grant` / `unsupported_token_type` / "expired or revoked" / etc.). `schwab_transport.place_order`
   now calls `mark_degraded()` when a submit throws an auth failure, so a real rejection persists into the
   token row.
2. **Ground-truth probe** — `schwab_token_manager.live_probe()` exercises the SAME authenticated read path
   an order uses (`get_orders_raw` → schwab-py refresh via the manager hooks) WITHOUT placing an order. On
   an auth failure it marks degraded; on success it self-heals (`_clear_degraded`). No order is ever placed.
3. **Endpoint + UI** — `GET /api/v2/brokers/schwab/token-health` combines DB health with a **5-min cached**
   live probe (`?probe=1` forces fresh). The protective-stop card (`PositionDecisionCard`) fetches it when
   the Schwab stop panel opens and, if `needs_reauth`:
   - shows a red **"⚠ Schwab re-auth needed — orders will be rejected"** banner with the exact re-auth
     command, and
   - disables the request button (label flips to **RE-AUTH NEEDED**) so a doomed live request can't fire.

## Endpoint shape
```json
{"ok": false, "broker": "schwab", "token_key": "schwab_taxable", "needs_reauth": true,
 "degraded": true, "has_token": true, "refresh_valid": false, "days_to_reauth": 1.89,
 "last_error": "...invalid_grant...", "live_probe": {"probed": true, "live_ok": false, "needs_reauth": true},
 "reauth_command": "python3 scripts/schwab_token_manager.py reauth-url schwab_taxable",
 "message": "Schwab login expired/revoked — re-authenticate before placing live orders."}
```
(`canonical_token_key()` filters out degraded rows, so the endpoint falls back to the most-recent schwab
token row for a precise message + key once degraded.)

## The operator fix when it fires
```bash
python3 scripts/schwab_token_manager.py reauth-url schwab_taxable
```
…then complete the browser OAuth login. A successful re-auth (`seed_token`) clears the degraded flag and
the badge goes green again (the probe also self-heals on the next success).

## Safety
Read-only diagnostics: the probe issues a read, never an order; no 2FA change; no transport write surface
touched; no `.env`/secrets exposed. Per-order 2FA remains the gate on every real submit.
