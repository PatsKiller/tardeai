# STAGE 12 LITMUS REVIEW — Active Trader (feat/active-trader-next @ ea0d6110)

> Produced by a fresh, write-denied read-only reviewer (Plan agent; Edit/Write/NotebookEdit
> unavailable). Recorded verbatim. Worktree `/home/johnclaw/worktrees/active-trader-next`.
> Production checkout never touched. No production DB/broker/login invoked.

## 1. Per-challenge verdicts (A–X)

| # | Challenge | Verdict | Evidence (personally checked) |
|---|-----------|---------|-------------------------------|
| A | /v3 unchanged | PASS | `git diff --name-only origin/main -- apps/command-center-v3` → empty; `git log origin/main..HEAD -- apps/command-center-v3` → empty |
| B | /v3-next separation | PASS | `apps/command-center-v3-next/vite.config.ts:6` `base:'/v3-next/'`; `:8` `outDir:'dist'`; v3 config unchanged at `base:'/v3/'` |
| C | Prod route isolation | PASS | grep of `apps/ backend/ server/ src/` for read_api/shadow/simulation → no imports; `read_api.py:5` stdlib http.server only, `:102-104` env-gated SHADOW/SIMULATION-only |
| D | Prod DB isolation | PASS (cautious) | `migrate.py:28` `PRODUCTION_DB_NAMES={'trade_ai'}`, `:29` ports {5432}; DSN from env, sentinel `UNSET__OPERATOR_REQUIRED` rejected `:43-44`. Production tables NOT independently measured (must not query prod); prod checkout untouched by this worktree |
| E | Migration guards trigger | PASS | `migrate.py:49-52` `_resolve_dsn` raises on db name/port; `:62-66` `_connect` re-checks `SELECT current_database()` and refuses |
| F | dev-write boundaries | PASS | `dev_write_api.py:4` header; `:25` `ALLOWED_ENVS=('SHADOW','SIMULATION')`; `:217-218` default-disabled (`ACTIVE_TRADER_DEV_WRITE_ENABLED` must=true); `:220-221` non-loopback refused; `:68-70` test-identity header required |
| G | CORS/rate/pagination/caps | PASS | `read_api.py:105` wildcard CORS forbidden; `:41-43` MAX_WARNINGS/SOURCES/`MAX_RESPONSE_BYTES=1_500_000`; `:67-74` RateLimiter 429; `:256-273` cursor pagination via MAX_LIMIT/parse_limit |
| H | Identifier masking | PASS | `discovery_alpaca.py:64,83` `masked_account_id="***"`/`mask_identifier`; `discovery_schwab.py:81` last-4 mask; `probe_brokers.py:15,91` masked ids, secrets never logged |
| I | Live flags OFF | PASS | ran `contracts`: 22 flags, `DEFAULTS['production']` all OFF, `active_trader_live_canary_enabled=FlagMode.OFF`; no non-OFF prod flags |
| J | Session hash / auth binding | PASS | `session_builder.py:149-153` canonical sha256 over authority-bearing fields only, versioned/immutable; `contracts.py:231-235` LIVE OrderIntent requires valid session_authorization; `:165-166` hash binds draft |
| K | Action contracts inactive | PASS | `authorization.py:180` `VALIDATED_INACTIVE`; `:216` `inactive:bool=True` "ALWAYS true — never executes"; `:280` returns validated-inactive |
| L | No real 2FA in code paths | **CONCERN** | `device_auth.py:1-7` performs REAL Moomoo SMS `input_phone_verify_code` via PTY. Scoped: this is data-gateway (OpenD) *device* authorization, operator-present one-time ceremony, NOT order 2FA; trade session-auth explicitly is-not-2FA (`contracts.py:148`). See §3 |
| M | No broker network shadow/sim | PASS | grep for socket/requests/urllib/moomoo/futu in `shadow_engine.py`+`simulation.py` → 0; `simulation.py:1-4` "in-process", `shadow_engine.py:5` fixtures/replay only |
| N | Deterministic replay / no lookahead | PASS | `shadow_engine.py:51-52` `contains_future_data` guard, `:81-82` `_no_lookahead` refuses; `replay.py:99` `num_rows==row_count` verified round-trip |
| O | Rate governors + reserves | PASS | `governor.py:42` PLACE(15,12,3), `:43` MODIFY_CANCEL(20,16,4), `:44` SNAPSHOT(60,48,12); `:36` invariant ordinary+reserve==ceiling; `:70-82` ordinary can never borrow reserve |
| P | Quote-right auto-grab off | PASS | `moomoo/secret_render.py:132` `<auto_hold_quote_right>0</auto_hold_quote_right>`; `:12` disables telnet/websocket/auto-grab |
| Q | Trade API statically unreachable | PASS | ran `ast_guard.scan_source` over full tree: 30 files, 0 findings; FORBIDDEN_NAMES cover place/modify/cancel/close/unlock + TrdEnv.REAL/SIMULATE `:11-17` |
| R | BF-1 unresolved | PASS | `stage-05/BF1_BROKER_RESIDENT_PROTECTION_EVIDENCE.md:39` "BF-1 VERDICT: UNPROVEN"; `:54` only affirmative flip test proves it |
| S | Agreement/smoke complete; observation pending; premarket L2 not overstated | PASS | `STAGE5_POST_AGREEMENT_DATA_SMOKE_ADDENDUM.md:34` ≥30-min capture PENDING, `:35` 5-session 0/5 PENDING, `:36` "Premarket Level 2 suitability — UNPROVEN", `:45` "proof only, not strategy-suitability proof" |
| T | Stage 9/10 promotion blocked | PASS | `simulation.py:8` "Promotion is BLOCKED"; `shadow_engine.py:8` "NOT promoted"; no promotion code path found |
| U | Darwin/Hermes no self-activate | PASS | `governance.py:3-5` proposal-only, no autonomous mutation; `:64-66` DarwinProposal requires human promotion; `:95-96` `applies_directly()` returns False |
| V | Drive/Gmail/Bitwarden safety | PASS | secret-value regex scan → 0 hits; `governance.py:135-150` Bitwarden registry metadata-only, `project_id_suffix`≤12, "store only a project-id SUFFIX, never the full id" |
| W | Moomoo units disabled | PASS | `systemctl --user list-unit-files` → 5 `trade-ai-lab-moomoo-*` units all `static` (no [Install], not enabled) |
| X | Stage 14 unreachable | PASS | live_canary flag OFF (see I); no live/canary execution path; OrderIntent LIVE branch unreachable without absent session authorization |

## 2. Procedural-deviation classification — VISIBLE / BENIGN

Confirmed both SHAs exist: `5c8bc5af` = "Stage 5 Moomoo device-auth tooling (telnet method)"; `69285d4e` = "Stage 5 drive manifest (17/17 hash-verified)". The Stages 6–11 controller started at `5c8bc5af` — exactly one commit ahead of the originally-pinned `69285d4e` — because additive Stage 5 device-auth work advanced the branch. This is documented openly in-repo, not hidden: `STAGES_06_TO_11_DRIVE_MANIFEST.json:4` (`start_head:5c8bc5af`), `STAGES_06_TO_11_COMMIT_MANIFEST.md:2` ("one ahead of launcher's 69285d4e, explained"), `stage-06-plan.md:3-4`, `stage-06-changes.txt:2` ("ALL additive; /v3 untouched; no production change"). The intervening commit is additive device-auth tooling only; no production boundary, DB target, flag default, or live authority was expanded. **Classification: visible and benign; owner-accepted retroactively.**

## 3. CONCERN detail

**L — real 2FA present (scoped, not a boundary breach).** `moomoo/device_auth.py` genuinely handles a real Moomoo SMS verification code (`input_phone_verify_code`) inside a PTY for one-time OpenD *device* trust. Adversarially, the literal claim "no real 2FA anywhere" is imprecise. However it is correctly bounded: (a) it authorizes the **data-only gateway** device, not any trade/order surface (no trade surface exists — challenge Q, 0 AST findings); (b) it is an operator-present one-time ceremony with `console=1` reverting to `console=0` (`device_auth.py:7-11`); (c) the verify code is read out-of-band from a `0600` file, never on a command line or in logs (`:6`); (d) LIVE order authorization is a separate hash-bound session mechanism that is explicitly NOT 2FA and remains inactive (`contracts.py:148`, `authorization.py` VALIDATED_INACTIVE). No live authority is conferred. Recommend restating the invariant as "no real *order/trade* 2FA is wired; the only real 2FA is one-time operator-present data-gateway device authorization." Not blocking.

All other challenges PASS. No FAILs.

## 4. FINAL VERDICT

**CONDITIONAL_PASS** — the read-only/data-only isolation, production preservation, flag-off posture, static trade-API unreachability, and governance/authorization inactivity all hold under independent inspection. Ceiling is CONDITIONAL_PASS because live-enabling data/observation/promotion gates remain legitimately open.

Remaining conditions before any promotion beyond this stage:
1. ≥30-minute continuous open-session capture (PENDING)
2. Five-RTH-session observation (0 of 5, PENDING)
3. Premarket Level 2 suitability (UNPROVEN — needs qualifying open-session L2 evidence)
4. Stage 9 scored-fire corpus, including the 60-sample floor where required (BLOCKED)
5. Stage 10 multi-broker simulation review (BLOCKED)
6. BF-1 broker-resident protection proof (UNPROVEN — needs affirmative OpenD-down trigger test)
7. Stage 14 live-canary exact-SHA authorization (BLOCKED; live_canary flag OFF)

## 5. Write-safety attestation

The reviewer made **no writes**. Every operation was read-only (git diff/log, grep, sed-view, Read, in-process python running the repo's own `ast_guard`/`contracts` for inspection, and read-only `systemctl --user list-unit-files` / `gh pr view`). No file was created, edited, moved, or deleted; no migration, broker call, login, or production-DB query was run. Edit/Write tools were not available in the reviewer session.
