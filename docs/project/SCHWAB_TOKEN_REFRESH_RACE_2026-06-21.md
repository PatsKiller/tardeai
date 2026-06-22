# Schwab Token Revoked Early — Concurrent-Refresh Race (2026-06-21)

## Symptom
The Schwab refresh token died with `invalid_grant` ("refresh token invalid, expired or revoked") even
though the DB nominal expiry said ~2 days remained. The NOC protective stop fully passed 2FA but every
submit was rejected at the broker.

## What was actually happening (and why it looked "automatic")
Schwab uses **rotating refresh tokens**: every ~30-min access-token refresh mints a NEW refresh token and
**resets the 7-day clock**. From 2026-06-09 → 06-16 the token rotated 131 times (~every 26–30 min) and
rolled its own 7-day window forward — so it never needed a manual login. That's the "auto re-auth every 7
days" behavior; it's really continuous rotation, not a scheduled re-login.

## Root cause — concurrent refresh race
Multiple independent processes share the ONE canonical Schwab token (`canonical_token_key`):
- `schwab_transaction_ingest.py` — cron `*/15 9-16 * * 1-5`
- `schwab_position_sync.py` — cron `*/15 9-16 * * 1-5` (**same minutes**)
- `portfolio_server.py` / `api_v2` live reads — on dashboard polling
- stream daemon + activity/recon watchers

They woke on the same `*/15` cadence and refreshed the shared token with **no serialization**. Audit smoking
gun: **2026-06-16 14:00:06 — three different refresh-token fingerprints minted within <1 second**
(`0a38e77d`, `1ef47ab8`, `6a49d572`). Three processes read the same token T1 and refreshed concurrently;
the first got T1′ and invalidated T1, the others presented the now-superseded T1, and Schwab's reuse-
detection **revoked the whole token family**. Rotations stopped at 18:44 that day and never recovered. The
failure wasn't written back as degraded (separate bug, fixed earlier), so it stayed hidden until the NOC
order days later.

## Fix (operator-approved: advisory lock + stagger crons)

1. **Cross-process refresh lock** (`scripts/schwab_token_manager.py`): a Postgres advisory lock
   (`pg_advisory_lock`, key = stable hash of broker+env) on a DEDICATED connection serializes refreshes
   across ALL processes.
   - `read_oauth_token` takes the lock ONLY when a refresh is imminent (access token stale/expiring) and
     NOT degraded; then RE-READS so a peer's just-rotated token is picked up (and schwab-py skips its own
     refresh). Released in `write_oauth_token` after the rotation persists.
   - Best-effort + self-freeing: `statement_timeout=20s` (never blocks a read indefinitely) and
     `idle_session_timeout=60s` (auto-frees a leaked lock); reentrant per thread; skips the lock for a
     known-degraded token so a dead token can't stall peers.
   - Verified: a second connection's `pg_try_advisory_lock` returns False while held, True after release;
     a degraded-token read returns in ~0.18s holding no lock.

2. **Stagger the crons** (live crontab, backed up to `backups/crontab/crontab_pre_stagger_20260621.txt`):
   `schwab_position_sync` moved from `*/15` → `7,22,37,52 9-16 * * 1-5` with a `sleep $((RANDOM % 20))`
   jitter, so it no longer fires on the same minute as `schwab_transaction_ingest` (`*/15`).

## Net effect
Only one process can refresh the rotating token at a time; the others wait briefly and reuse the freshly
rotated token instead of racing — eliminating the reuse-detection family revocation. The lock degrades
safely (timeouts) and never blocks a read path. After re-auth the token should again roll its 7-day window
forward indefinitely without manual logins.

## Note
This does NOT restore the current token — the family is already revoked. A one-time manual re-auth is still
required: `python3 scripts/schwab_token_manager.py reauth-url schwab_taxable` → login → `exchange-code`.
