---
Status: MEASURED
as_of: 2026-09-28T12:30:00-04:00 (pin timeline corrected; first measurement 10:58–11:00 ET)
Measured at: served a328a88177833e4b121cf6fec6724f8fbfe2075c at 10:58 ET, then e2dcfce1afdd06535d21a489800aa171c5e7cb3b from 10:59 ET (another session promoted during Phase 0); code HEAD for inspection e2dcfce1a (origin/main = served after 10:59)
Campaign: LIVEPROOF-20260928
---
# 00 — Served baseline (read-only, Phase 0.1)

Every row below was read from the host on 2026-09-28 between 10:58 and 11:00 ET. No process was started, stopped or raced; no secret value was displayed. Release directories carry no git checkout; identity comes from the stamp files. Code inspection uses the clean worktree `~/tradeai-wt-liveproof-20260928` at `e2dcfce1a`.

| Item | Value | Evidence |
|---|---|---|
| Host | `ms01-openclaw` | `hostname` |
| Clock | UTC `2026-09-28T14:58:57+00:00` · ET `2026-09-28T10:58:57-04:00` | `date -u -Is`, `TZ=America/New_York date -Is` |
| CURRENT | `/home/johnclaw/trade-ai-releases/portfolio-server/a328a8817-main-exact-phase2-20260928-101406` | `readlink -f CURRENT` |
| Release GIT_SHA / BUILD_SHA / SOURCE_COMMIT | `a328a88177833e4b121cf6fec6724f8fbfe2075c` (all three agree) | stamp files in CURRENT |
| Release provenance | merge of PR #1332 (`ui-options-cards-pr4-20260928`); promoted 2026-09-28 14:14:47Z; ancestor of origin/main | `git log -1 a328a8817`, `merge-base --is-ancestor` |
| EXPECTED_RELEASE / ACTIVE_RELEASE | both = CURRENT | pin files |
| Code HEAD (inspection) | `e2dcfce1a` = origin/main (adds PR #1337 on top of served) | `git rev-parse origin/main` |
| portfolio-server.service (API :7777) | active, PID 2008504, started 10:14:48 EDT, exe `/usr/bin/python3.14`, cwd = CURRENT dir, ExecStart `.venv/bin/python scripts/portfolio_server.py` (dev-tree venv, served tree code) | `systemctl --user show`, `/proc/<pid>/{exe,cwd}` |
| tradeai-cio-telegram.service (bot) | active, PID 2009271, started 10:14:59 EDT, cwd = CURRENT dir, ExecStart `.venv/bin/python CURRENT/scripts/cio_telegram_bot.py --loop` | same |
| tradeai-health-agent.service | active, started 10:14:51 EDT, WorkingDirectory `CURRENT` | same |
| cio-governed-bridge.service (:8766) | active, started 10:14:56 EDT, WorkingDirectory `CURRENT` | same |
| API health | `/api/v2/health` → `ok: true`, `overall_score 66`, `status degraded`, `mode advisory` (captured 14:54:09Z) | curl |
| API version endpoint | `/api/v2/version` → HTTP error page (no such route) — API pin is the release stamp, not an endpoint | curl |
| Frontend build | `apps/command-center-v3/dist/assets/index-MP1ud_bZ.js`; `dist/build-meta.json` written by the deploy script | ls |
| DB migrations | 125 `.sql` files under `migrations/` in the served tree; latest `2026_09_27_intelligence_v1.sql`, `2026_09_27_sec_filing_documents.sql`; no migrations table — application is proven by schema presence (intelligence.* 11 tables, memory_r10_m2 views + functions: parity check PR #1337) | ls, PR #1337 |
| Served memory policy (`config/memory_influence_policy.json`) | ring2: all 5 surfaces SHADOW (incl. `context:persistent-wake`, rolled back 2026-09-27); influence: all 7 surfaces SHADOW; write_path adapters: hermes-external LIVE, hermes-cio-worker LIVE, four others SHADOW | file in CURRENT |
| `MBI_BEHAVIOR` | `= 0` (`scripts/lib/cio_instrument_record.py:33`, unconditional raise) | grep |
| Schedulers (today's counts) | user crontab **476** non-comment lines; user systemd timers **93**; running user services **24** (the historical 467 / 90 / 188 figures are superseded by these) | `crontab -l`, `list-timers --all`, `list-units --state=running` |
| Maturity bar M1–M5 on the served SHA | M1 OBSERVED_PRE_DEPLOY, M2 OBSERVED_PRE_DEPLOY, M3 OBSERVED_PRE_DEPLOY, M4 PARTIAL (bridge soak stale 201 h), M5 OBSERVED on served (14:55:06Z) → **1/5 observed on the served SHA** | `report_maturity_bar_m1_m5.py` 14:59:23Z |

## Release moved during Phase 0 (recorded, not hidden)

At 10:59:24 ET a different session promoted `e2dcfce1a-main-exact-phase2-20260928-105924` (merge of PR #1337; also carries PR #1336, the earnings-gate fix). Rows above measured before 10:59 name `a328a8817`; every observation after 10:59 names `e2dcfce1a`. The M1–M5 report at 14:59:23Z (10:59:23 ET) ran one second before the flip and is attributed to `a328a8817`; it must be re-run for the new pin (its verdicts predate promotion by construction).

## Controlling documents (found / not found)

| Named in the work order | On disk | Note |
|---|---|---|
| `TRADE_AI_CIO_AUTONOMY_MATURITY_DUE_DILIGENCE_2026-09-02.md` | **not found** (repo, worktrees, `~/trade-ai-audits`, Gmail, Drive — searched 2026-09-27 and again today) | The description ("header September 27, served release `eb09dcf10`") matches `docs/architecture/PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md`, the only document containing `eb09dcf10`. That file is used as the due diligence; its §§2.3, 2.4, 7, 8, 11 diagrams are the ledger's sources. Recorded as a conflict, not silently resolved. |
| `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md` | `docs/architecture/` | plus `V3_3_IMPLEMENTATION_STATUS_2026-09-27.md` |
| `CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md` | `docs/prompts/` (v1_0, v1_1, v1_2 exist) | v1_1 used as named; v1_2 noted as newer |
| `ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md` | `docs/prompts/` | |
| Prior 12-gate board | `docs/ops/CIO_OVERNIGHT_AUTONOMY_SCOREBOARD_2026-09-02.md` (+ closeouts under `docs/ops/`) | preserved verbatim in `03-maturity-board.md` |

## Access and blockers

- Read-only DB access exists through `db_adapter` (role `trade_ai`, no bypassrls) and the guard's read scopes; no write grant is used in Phase 0.
- The permission classifier in this session refuses `gh pr merge` and guard grant minting; merges and grants are operator steps (recorded in every closeout since 2026-09-27).
- The served release is one merge behind main; every "served" observation below names `a328a8817`, every code citation names `e2dcfce1a`.


## Pin timeline (corrected 2026-09-28 12:30 ET — three promotions during the campaign)

Read from `/home/johnclaw/trade-ai-releases/portfolio-server` (directory mtimes = `prepare`; CURRENT symlink mtime and
`report_maturity_bar_m1_m5.py promoted_at` = `promote`). Every evidence row in this campaign names the pin that was
served when it was taken; "served" never means "merged".

| Release dir (prepare mtime, ET) | Promoted → CURRENT | Observed by this session | Notes |
|---|---|---|---|
| `f677855fa-…-20260927-224302` (09-27 22:43) | yes (predecessor) | no | last pin before the 09-28 waves |
| `72ce23e0e-…-20260928-074513` (07:45) | not observed | no | prepared by another session |
| `9309ffca7-…-075936 / -080924 / -081219` (07:59, 08:09, 08:12) | yes (the operator's repeated promote re-shipped the same SHA three times) | no | Waves 1–2 closeout |
| `c1c531500-…-081744` (08:18) | yes | yes (Waves 3–5 live) | three cron-started daemons still run from this dir (LP-DEF-21) |
| `a328a8817-…-101406` (10:14) | **yes, 14:14:47Z** | **yes — the 10:20 ET AXTI packet was produced on this pin**; M1–M5 14:59:23Z and the 12-gate 14:35:01Z rows belong here | merge of PR #1332 |
| `e2dcfce1a-…-105924` (10:59) | **yes, 14:59:24Z** | yes — code HEAD for Phase 0 inspection; the 15:35:01Z 12-gate row belongs here | merge of PR #1337 (+ #1336 earnings set) |
| `914dcb5ab-…-121052` (12:10) | **yes, 16:11:41Z** (symlink 12:11:42 ET) | yes — **served pin at 12:30 ET**; M1–M5 re-run 16:24:10Z belongs here | merge of PR #1342 (lifecycle lock) + #1338 #1340 #1341 |

Served at the moment of each evidence row: 10:20 ET AXTI packet → `a328a8817`; 14:35Z 12-gate → `a328a8817`;
14:59:23Z M1–M5 → `a328a8817`; 15:35Z 12-gate → `e2dcfce1a`; 16:24Z M1–M5 → `914dcb5ab`. PR #1339's code
(`wt/live-proof-20260928`) is served on none of them: every C1/C4/C5 claim is INSTALLED-in-a-branch until a promote
that names this PR's merge SHA.
