# Operator TODO — after Stage 5

**Run ID:** 20260722-01 · Stage 5 state: **BLOCKED_CREDENTIAL_GATE** (offline
implementation GREEN and committed; live-data acceptance blocked on the Moomoo login).

## BLOCKING — Moomoo data login (do this to unblock the live portion)
A Moomoo lockout counter is now ACTIVE ("9 chances remained"). Automated retries were
STOPPED to avoid locking the account. Fix the value(s) in the vault, then request ONE
careful retry:
1. `MOOMOO_DATA_LOGIN_PASSWORD` must be your Moomoo **login** password (app/website
   sign-in) — NOT the trading PIN, NOT the word "test".
2. Consider setting `MOOMOO_DATA_LOGIN_ACCOUNT` to your **numeric Moomoo UID** or
   **phone** (`+1 5551234567`) instead of the email — OpenD login by email can be
   unreliable; the log shows the email was accepted but the password mismatched.
3. Moomoo may require a **trusted-device / SMS verification** the first time OpenD logs
   in from this machine. If the password is definitely correct, open the Moomoo app and
   clear any device-authorization / security prompt (or temporarily relax device-lock).
4. Do NOT create any MOOMOO_TRADE_*/unlock/TOTP/PIN secret — the trading PIN stays out
   of the data project entirely.
Then tell the controller "credentials updated — retry moomoo login" for one attempt.

## After a successful login (still Stage 5 scope on resume)
- authenticated data-only smoke (entitlement/quota/snapshot/subscribe QUOTE→K_1M→
  ORDER_BOOK→TICKER/unsubscribe/close);
- ≥30-minute continuous capture during an OPEN US RTH session;
- start the resumable five-RTH-session observation (Stage 9 hard gate).

## Carried forward (non-blocking)
- BF-1 VERDICT: UNPROVEN → live Moomoo scalping BLOCKED until a controlled
  submit+disconnect test (later authorized stage) proves broker-resident, disconnect-
  surviving protection for US equities.
- Prior-stage items: alpaca label mismatch; schwab market-hours read errors; alpaca
  taxable-live read creds intended?; default fallback allowlists review; Stage 0 hygiene.
- Production checkout: QUARANTINED, untouched again this stage.

## Note on machine-account name
The vault display name is **trade-ai-lab-code**; the v1.2 launcher text wrote
"trade-ai-lab-codex". bws CLI does not expose the machine-account ID, so identity is
taken from your vault action. Recorded as a display-name mismatch, no functional impact.
