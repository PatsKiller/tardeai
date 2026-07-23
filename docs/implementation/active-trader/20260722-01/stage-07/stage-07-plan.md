# Stage 7 Plan — Session Builder, Account Checkboxes, Quick-Add, Feature Controls
**Run ID:** 20260722-01 · Dev/test-only. No 2FA, no order, no production write. Moomoo lockout honored.
Dev write plane `/api/v3/active-trader/dev` (separate app factory, loopback, default disabled,
SHADOW/SIMULATION only, trade_ai_test only, test identity, audit journal, optimistic versioning).
Session builder: CRUD/version/clone, draft fields, account roles (PRIMARY/FALLBACK/DISABLED with
capability gating), sizing (SHARES/DOLLAR_NOTIONAL/RISK_BASED, floor rounding + remainder),
quick-add (100/200/500/1000; SHARES/DOLLARS; same validation), feature controls (OFF/READ_ONLY/
SHADOW/SIMULATION; LIVE_CANARY rejected). Canonical authority-only draft hash.
