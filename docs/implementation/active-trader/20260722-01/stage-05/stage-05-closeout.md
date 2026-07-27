# Stage 5 Closeout — Isolated Moomoo OpenD Data Foundation

**Run ID:** 20260722-01 · **Date:** 2026-07-23
**Branch:** feat/active-trader-next · **Start HEAD:** f070288e · PR #150 (draft)

## Result: BLOCKED_CREDENTIAL_GATE (offline implementation GREEN)

The full offline + integration implementation is complete, isolated, and green; the
authenticated Moomoo **data login is blocked by an operator credential value**, so
everything gated behind it (entitlement/quota, snapshot, live subscriptions, ≥30-minute
capture, five-RTH observation) could not run. This is committed honestly as blocked —
not mislabeled green — per launcher §27.

## What is GREEN (implementation acceptance)
- **Isolated install, hash-verified:** moomoo-api 10.9.6908 (sdist sha256 == launcher
  pin), pyarrow 25.0.0 into a dedicated Python-3.14 venv; official Ubuntu command-line
  OpenD 10.9.6908 (LOCAL_ARCHIVE_SHA256 e60713be…; official checksum UNAVAILABLE; newer
  10.9.6918 recorded as candidate, not installed); atomic versioned paths + `current`
  symlinks; archive safety clean; system Python + repo .venv + requirements untouched.
- **Static trade prohibition:** AST guard → 0 trade constructors / 0 trade methods
  reachable in any Stage 5 runtime module (injected trade-call + TrdEnv.REAL detection tested).
- **Credential wrapper:** MACHINE_ACCOUNT_REUSE_WITH_PROJECT_ALLOWLIST — pinned
  project ID (suffix 00375f2c), exact 3-name allowlist, read-only, rejects other
  projects/non-allowlisted names/sentinels/bad-mode/wrong-suffix; runtime never gets the
  lab or org token; trade-ai-prod not listed.
- **OpenD config + start mechanics PROVEN:** tmpfs XML 0600, md5-only (plaintext password
  never on disk/argv), loopback 11112, telnet/websocket off, auto_hold_quote_right=0,
  console=0; OpenD started, consumed the config, and reached Moomoo servers.
- **Single subscription owner** (states/priorities/quote-right-conflict-no-grab/quota),
  **bounded queues** (coalesce/ring-gap/overflow/control-never-drops), **event envelope**
  (null provider_sequence, first-push-not-fresh), **deterministic features** (replay
  equality), **WAL→verified-zstd-Parquet replay** (crash recovery, read-back verify,
  retain-until-verified, disk budget), **rate governors** (15/12/3, 20/16/4, 60/48/12,
  bucket+sliding-window, conservative restart, thread-safe) — all unit/integration tested.
- **Lab migration 0007** (10 md_* tables) cycle-tested in trade_ai_test only; Stage 4 read
  projections extendable additively; production DB untouched.
- 5 **disabled** user units (static, no [Install], no linger, hardened); no system units.

## What is BLOCKED (data-foundation observation)
Moomoo rejected the data login: first "Password does not match", then after an operator
update "The account and password you've entered don't match. 9 chances remained." A
lockout counter is active → automated retries STOPPED. No entitlement/quota/snapshot/
subscription/capture/observation ran. Market was also CLOSED (Thu 00:xx EDT), so even
with a working login only `GREEN_IMPLEMENTED_MARKET_VALIDATION_PENDING` would have been
reachable this session. DATA_FOUNDATION_VALIDATED is NOT claimed. Operator fix in
OPERATOR_TODO.md; on resume: one careful login retry → smoke → capture → 5 sessions.

## BF-1
UNPROVEN → LIVE MOOMOO SCALPING: BLOCKED (order types exist; no primary doc guarantee of
US-equity disconnect-surviving broker-resident protection; no runtime proof). Later
controlled submit+disconnect test defined in BF1_BROKER_RESIDENT_PROTECTION_EVIDENCE.md.

## Post-run safety
0 OpenD processes · 0 listeners on 11111/11112 · tmpfs config shredded · production schema
hash unchanged · repo venv/requirements unchanged · no trade context/unlock/order/2FA ·
quote rights never auto-grabbed · production checkout byte-identical.

## Checkpoint
```yaml
run_id: 20260722-01
current_stage: 5
state: BLOCKED_CREDENTIAL_GATE
last_green_stage: 4
implementation_acceptance: GREEN
data_foundation_observation: NOT_STARTED
updated_at: 2026-07-23
```

## Stop
Stage 5 offline implementation committed; live-data acceptance blocked. Do NOT start
Stage 6 (BLOCKED_CREDENTIAL_GATE does not authorize a Stage 6-11 prompt without Stage 5
resume). Resume Stage 5 after the operator corrects the Moomoo login.
