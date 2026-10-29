# Postgres Main Enospc 2026-09-18

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 1955-2023 -->
## Moved from AGENTS.md (25.0.1 lines 1955-2023)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

# Postgres ENOSPC → Command Center false-green (2026-09-18)

Moved from AGENTS.md 25.0.1 §8 (lines 1955–2023) by the 26.0.0 rewrite. Note: the 'Release reclaim goes through `disk_hygiene_enforcer`' bullet is superseded by AGENTS.md §24.12 — only `scripts/disk_hygiene.py` may reclaim release trees, and `disk_hygiene_enforcer.py` removes nothing.

## What 2026-09-18 taught — Postgres ENOSPC → Command Center false-green `[VERIFIED]` (PR #1068)

The host filled the root volume; main Postgres panicked and stayed down; Command Center kept serving.
Empty SETUPS and a PARTIAL badge looked like a scanner bug. They were not.

### Symptoms (what the board showed)
- **SETUPS · LATEST RUN:** `0 GO · 0 WAIT · 0 NOGO`, `PARTIAL`, `0 classified / 0 scanned` while a run
  label (e.g. `0700` / `0900`) still appeared finished.
- **Universe chips** could still show NO-GO / AWARE rows (overlay / alternate path) while the latest-run
  contract was empty — do not treat chip counts as proof the primary scan DB is healthy.
- **Regime** blank or unavailable (`risk-regime/latest` empty) while VIX might still render from a
  side channel.
- **Health:** criticals including DB / kill-switch unavailability (`kill_switch_db_unavailable` class).
- **Prices DEGRADED** / Finviz after-hours thin; portfolio **clock divergence** warnings.
- **`/api/health` stayed `ok: true`.** A green process health check is not evidence that
  `postgresql@17-main` is up or that `trade_ai_scans` is writable.

### Root cause (ordered)
1. **Disk pressure on `/`.** Portfolio-server immutable releases and large Postgres logs filled the
   volume. Early canary: `tradeai-portfolio-backup-cadence` failed with `No space left on device`
   (~02:30 ET).
2. **Postgres hit ENOSPC** in `pgsql_tmp`, then **WAL PANIC** (observed during
   `DELETE FROM schwab_stream_book`) and the cluster shut down — unit `postgresql@17-main` on **:5432**
   failed (~04:10 ET). Lab Postgres on **:5433** is a separate instance; do not diagnose the main
   outage against it.
3. **`disk_hygiene_enforcer` reclaimed space (~41GB) and did not restart Postgres.** Free disk ≠
   recovered database. CC kept running against caches / run summaries while `trade_ai_scans` was
   unreachable.
4. **Orchestrator slots that ran while Postgres was down** wrote `run_summary` with
   `ticker_count > 0` and **zero** primary scan rows → honesty
   `count_integrity=PARTIAL` (`primary(0) vs alternate(N)`). That PARTIAL is the contract telling the
   truth, not a stale UI bug after Postgres returns.

### Fix (immediate + lasting)
- **Immediate restore:** `sudo systemctl start postgresql@17-main`, confirm `systemctl is-active` and
  `:5432` listen, then warm caches (`scripts/warm_caches.py` from the served tree) and re-check
  `/api/v2/trade-ai` (`setup_run_summary`) plus regime. Truncate huge Postgres logs with
  `sudo bash -c ': > /var/log/postgresql/…'` (plain `truncate` may hit permission denied); vacuum
  journals with `sudo journalctl --vacuum-size=…` when reclaiming disk.
- **Do not "heal" PARTIAL by overwriting `run_label`.** After DB is back, either wait for the next
  scheduled slot or re-run the affected orchestrator label so `trade_ai_scans` refills. A PARTIAL
  badge with `primary(0) vs alternate(N)` after an outage is expected until that happens.
- **Lasting controls (PR #1068):** `scripts/lib/postgres_main_health.py`,
  `scripts/remediate_postgres_main.py` (disk floor → allowlisted `systemctl start` only), health-agent
  `postgres_main_down` / disk findings, and user timer
  `tradeai-postgres-main-watchdog.timer` → `remediate_postgres_main.py --apply`.
- **`tradeai-health-agent` cannot start Postgres itself** (`NoNewPrivileges=true`). Auto-start needs
  the **separate user watchdog** plus passwordless sudoers
  `linux_launchers/sudoers/tradeai-postgres-main-start` installed under `/etc/sudoers.d/`.
- **Sudoers must allow both `/bin/systemctl` and `/usr/bin/systemctl`.** Ubuntu resolves `systemctl`
  via `/usr/bin`; a drop-in that lists only `/bin/…` still demands a password for `sudo -n systemctl …`.
- **Soft remediate outcomes exit 0** (`already_active`, `cooldown`, `needs_sudoers`) so the watchdog
  timer does not flap `failed` every interval while waiting on operator install.
- **Release reclaim goes through `disk_hygiene_enforcer`** (protects `CURRENT` /
  `EXPECTED_RELEASE` and live process cwds). Default `keep_n` can leave several ~13GB pins in place;
  a lower `keep_n` one-shot needs explicit operator approval. Ad-hoc `rm` of release trees is not the
  path. Installing/editing the sudoers drop-in or the watchdog user unit remains operator-gated
  (§17 / scheduler install rules).

### Quick verify
```bash
systemctl is-active postgresql@17-main
ss -ltn | grep 5432
curl -sS http://127.0.0.1:7777/api/health
curl -sS http://127.0.0.1:7777/api/v2/system-health   # served_sha
# trade-ai honesty: setup_run_summary.count_integrity / scanned_count
.venv/bin/python scripts/remediate_postgres_main.py    # status / disk floor
systemctl --user status tradeai-postgres-main-watchdog.timer
```
