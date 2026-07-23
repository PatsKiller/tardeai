# Stage 3 Plan — Rejection Classifier, Notifications, Fallback Policy

**Run ID:** 20260722-01 · **Start HEAD:** 520e8d3b6c7afc8fa4d01f4beab3e419dca8adbd
**Branch:** feat/active-trader-next · PR #150 (draft)
**Mode:** mocks + synthetic fixtures ONLY — zero live broker calls; zero real alerts.

## Steps
1. Verify continuation point (HEAD 520e8d3b, clean).
2. Migration 0006 (additive enrichment columns on broker_rejection_events +
   active_trader_notification_events; paired down; lab-only application).
3. `rejections.py`: redaction (headers/tokens always; digit runs in free text only, so
   structured broker codes survive), RawBrokerEvent (provenance-labeled), deterministic
   4-tier rule pipeline (exact code → bounded broker patterns → structural → UNKNOWN
   fallback), Classification with safety invariants (UNKNOWN never retryable;
   RATE_LIMITED retryable only with bounded backoff), capability-evidence proposals
   (RESTRICTED-only, scoped, idempotent), idempotent lab persistence with occurrence
   counting.
4. `notifications.py`: NotificationEvent + severity model (INFO/WARNING/ACTION_REQUIRED/
   CRITICAL with explicit DB mapping), deterministic channel routing, NotificationCenter
   (dedupe/no-flood, changed-fill update, escalation, ack, resolve, expiry), TEST sinks
   only (in-memory, mock Telegram, mock Gmail, lab-DB).
5. `fallback.py`: FallbackPolicy + pure evaluator (source-finality first gate;
   envelope-membership second; class allowlist; eligibility; synthetic market/risk state;
   duplicate-exposure arithmetic with floor rounding; 6 decisions with reason codes),
   unapproved-alternate state projection (§16F.9).
6. Fixtures: 24 provenance-labeled (9 schwab + 10 alpaca SYNTHETIC; 5 moomoo
   SYNTHETIC_FUTURE_ADAPTER).
7. Tests: 28 pure + 5 lab-DB + full prior-stage regression.
8. Proofs, artifacts, commit, push, PR, Drive + hashes, checkpoint, email, stop.

## Non-goals
No session 2FA, no session-amendment endpoint, no broker submission, no real alert
wiring, no Moomoo install, no read API (Stage 4), no production change of any kind.
