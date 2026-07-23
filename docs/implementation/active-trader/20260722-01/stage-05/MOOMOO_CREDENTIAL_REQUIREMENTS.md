# Moomoo Credential Requirements — Stage 5

## Design: MACHINE_ACCOUNT_REUSE_WITH_PROJECT_ALLOWLIST (plan-limit ruling)
Bitwarden is at its 3/3 machine-account limit; NO fourth account was created. The
existing machine account (vault display name **trade-ai-lab-code**; the v1.2 launcher
text says "trade-ai-lab-codex" — recorded display-name mismatch; bws CLI does not expose
the machine-account ID, so identity is verified by operator vault action) holds:
`trade-ai-lab` = read/write · `trade-ai-moomoo-data` = read · `trade-ai-prod` = NONE.
Dedicated access token `moomoo-data-stage5` at
`~/.openclaw/credentials/bws_moomoo_data_token` (0600). This is an acknowledged reduction
in isolation; the compensating controls below are mandatory and were proven in tests.

## Compensating controls (scripts/active_trader/moomoo/secret_render.py; tested)
- authenticates ONLY with the dedicated data token;
- pins the exact `trade-ai-moomoo-data` project ID (suffix 00375f2c) — wrong suffix rejected;
- allowlists exactly MOOMOO_DATA_LOGIN_ACCOUNT / _LOGIN_PASSWORD / _TEST_SYMBOLS;
- rejects any non-allowlisted or duplicate secret name, any secret from another project
  (incl. trade-ai-lab), any trade-ai-prod exposure, empty values, and the sentinel;
- read-only (no list/create/update/delete surface exposed); runtime never receives the
  lab or org token; no Stage 5 service touches trade-ai-lab.

## Required secrets (operator-entered directly in the vault; values never seen by Codex)
MOOMOO_DATA_LOGIN_ACCOUNT · MOOMOO_DATA_LOGIN_PASSWORD · MOOMOO_DATA_TEST_SYMBOLS (=US.AAPL)

## Forbidden in Stage 5 (never requested, never stored)
MOOMOO_TRADE_PASSWORD · MOOMOO_TRADE_UNLOCK_PASSWORD · MOOMOO_TRADE_UNLOCK_MD5 ·
MOOMOO_LIVE_ORDER_TOKEN · any trade TOTP/authorization/PIN secret. (The operator's
separate *trading PIN* must NOT be placed in any secret — it is the trade-unlock, out of
scope for the entire data phase.)

## CURRENT BLOCKER (BLOCKED_CREDENTIAL_GATE)
The credential *gate* (token + project + 3 non-sentinel secrets) is GREEN, but the
authenticated OpenD **data login is rejected by Moomoo**: first attempt "Password does
not match"; after the operator updated the value, "The account and password you've
entered don't match. 9 chances remained." A Moomoo lockout counter is now active, so
automated retries were STOPPED. Operator action required (see OPERATOR_TODO.md): verify
MOOMOO_DATA_LOGIN_PASSWORD is the Moomoo *login* password (not the trading PIN, not
"test"), and consider setting MOOMOO_DATA_LOGIN_ACCOUNT to the numeric Moomoo UID or
phone number rather than the email, then request exactly one careful retry.
