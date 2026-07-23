# Stage 5 Resume Requirements — run 20260722-01
Stage 5 remains BLOCKED_CREDENTIAL_GATE (offline implementation GREEN). To resume:
1. Resolve the Moomoo website/login lockout (operator via moomoo recovery/support).
2. Complete the moomoo OpenAPI regulatory questionnaire + agreement (ProgramStatusType_UnAgreeDisclaimer).
   (Device SMS verification is already COMPLETE — this machine is a trusted device.)
3. Reply "moomoo agreement done — retry"; controller runs ONE login via device_auth_telnet.py.
4. On success: data-only smoke → >=30-min RTH capture → resumable five-RTH-session observation.
Only after five RTH sessions PASS do Stage 9 acceptance and Stage 10 promotion unblock. BF-1 (UNPROVEN)
independently blocks any live scalp. Stage 14 live canary stays BLOCKED. Do NOT retry login otherwise.
Resume branch tip after Stages 6-11: feat/active-trader-next (see final closeout for exact SHA).

---

## UPDATE 2026-07-23 (additive): credential/agreement gate CLEARED; observation harness BUILT
Steps 1-3 are DONE (agreement complete, data-only smoke PASS — see MOOMOO_DATA_SMOKE_SUCCESS.md /
STAGE5_POST_AGREEMENT_DATA_SMOKE_ADDENDUM.md). Step 4's observation launcher — previously ABSENT — is
now IMPLEMENTED (GREEN_OBSERVATION_HARNESS_READY): exchange calendar (2026-27), 07:00-10:05 ET
controller, P1-R2 windows, extended-hours subscription request, Level 2 metrics, representative-symbol
selector, WAL/Parquet/replay, dry-run scheduler renderer, and a live path that refuses without an owner
authorization marker. See PREMARKET_OBSERVATION_HARNESS_CLOSEOUT.md. STILL PENDING: the ≥30-min
continuous capture and the five qualifying RTH sessions (0/5), each requiring an open session AND a
separately-issued owner authorization marker. Stage 9/10 promotion, BF-1, and Stage 14 remain BLOCKED.
