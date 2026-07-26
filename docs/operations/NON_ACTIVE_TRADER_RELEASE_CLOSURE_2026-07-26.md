# Non–Active Trader Release-Closure Sprint — Closeout (2026-07-26)

Converts the four prepared lanes into exact-ref, conflict-tested, operator-deployable release
candidates — **and, with explicit per-step operator authorization, MERGES them into `main`.**
**Active Trader out of scope and untouched.** Nothing deployed/migrated/scheduled/activated/backfilled.

**FINAL STATE (2026-07-26): all lanes merged.** Base `main` `20a24027` → **`fc86150f`** via five
authorized merges (#184 → #163 → #182 → #181 → #180; RC #183 closed as integration proof, not merged). Post-merge
combined validator green; `main` CI green. See "Merge execution" below.

## CI status — RESOLVED (updated 2026-07-26, post-billing)
The earlier GitHub Actions **account billing block** (jobs died in ~4s: *"the job was not started
because recent account payments have failed…"*, on every branch incl. `main`) was **resolved by
upgrading the account to GitHub Pro**. Focused workflows now execute normally and are **green on every
lane**. Three real CI-env gaps surfaced once jobs actually ran and were fixed (workflow-only, no test
weakened): `psycopg2-binary` (#163), advisory `systemd-analyze verify` (#182/RC), and `PYTHONPATH` for
the Watch pytest step (#181/RC). Run IDs in "CI verification" below.

**RESOLVED — #184 merged first**, which cleared the pre-existing repo-wide `release-readiness` false
positive (metric-consistency scan flagging a *code comment*) at the source; `release-readiness` is now
green on `main` and on every subsequent lane as it inherited the fix.

---

## Phase 1 — red CI gates closed (each fix workflow/test-only, no product change)

| Lane | PR | Frozen → CI-green head | Red-state diagnosis | Fix | Local result |
|---|---|---|---|---|---|
| **A** read plane | #163 | `a65fd529` → **`eb21fe69`** | (6) billing block, then (3) missing `psycopg2` | evidence-hardened + `psycopg2-binary` | 215/9; contract tests, authority, frontend 11, tsc/vite, guards all pass |
| **D** SHADOW agents | #182 | `d4671a32` → **`81056b85`** | (3) missing `psycopg2`; runner systemd verify | `psycopg2-binary` + advisory `systemd-analyze` | 49 Lane D + 224/9; migration refusals 3/4/5; systemd verify; independence enforced |
| **B** Watch | #181 | `4472c9ca` → **`d4c9cfb9`** | (2) stale refs + (3) dep + `PYTHONPATH` | removed 6 unowned refs; **fixed 2 UI tests to the real sovereign/quality contract**; add `PYTHONPATH` | 173/1 (was 8 failed); 134 packet/API; guards pass |
| **C** Defense/Sectors | #180 | `2190c6ca` → **`eaa653f8`** | no focused workflow existed | added `defense-sectors-ci.yml` (lane-scoped) | 54/54; build green; switch-packet dry-run inert |

Each lane's evidence comment is posted on its PR. No substantive test was weakened or deleted.

### CI verification (post-billing, real runs 19s–2m4s — not the 4s billing failures)
| PR | Head | Focused CI | Run |
|---|---|---|---|
| #184 | `c3e95c02` | `release-readiness` ✅ | run 1332 |
| #163 | `eb21fe69` | `agentic-mvl-ci` ✅ + backend/frontend ✅ | run 85 |
| #182 | `81056b85` | `agentic-mvl-ci` ✅ | run 86 |
| #181 | `d4c9cfb9` | `watch-quality-governance-ci` ✅ + re-entry/options/ui-contract ✅ | (Watch focused green) |
| #180 | `eaa653f8` | `defense-sectors-ci` ✅ | run 2 |
| #183 RC | `46bad45c` | agentic ✅ + watch ✅ + defense ✅ + options/re-entry ✅ | 30213036351/366/371 |

`release-readiness` is green across the board: #184 fixed the pre-existing `main` false positive, and
each lane inherited it as `main` advanced. All five delivery PRs are **merged**; `main` = `fc86150f`.

---

## Phase 2 — conflict-tested release candidate (draft PR #183)

- **Branch** `codex/non-active-trader-release-candidate-v1`, from `main` `20a24027`, head **`cc3fd466`** (Phase 2) → **`8315a3a9`** (Phase 3) → **`46bad45c`** (current, after the post-billing CI-env workflow fixes).
- **Merge commits (order A→D→B→C):** `341df201` · `42b76781` · `1728dce9` · `d986badf` (normal non-force merge commits).
- **Conflict files — exactly two, both intentionally reconciled (no whole-file ours/theirs):**
  1. `.github/workflows/agentic-mvl-ci.yml` (A∩D) — real textual conflict, hand-folded: A provenance + teed compile/pytest/authority evidence **and** D `psycopg2-binary` + recursive (`rglob`) `agents/` scan + migration-refusal + systemd-verify + `if: always()` matrix.
  2. `scripts/api_v2.py` (B∩C) — git 3-way auto-merge (lanes edit different functions: B `_finviz_strip_map_compute`, C `_market_movers`/`_sectors_monitor`); verified exact union (106 insertions = 38 B + 68 C). **Watch preserved:** `pe/forward_pe/peg/pb/ps` passthrough, `valuation_source`, `fundamentals_as_of`, no fake PASS, no paid-review auto-call. **Defense/Sectors preserved:** `internals_scope` scope-truth, sectors data-quality ledger (`quarantine_stale_rows`/`recommendation_eligible`/`field_ledger`). `ROUTES` still maps all endpoints — **no route replaced.**
  - No other overlaps in CC pages/components, shared utilities, deploy scripts, config, tests, or build tooling.
- **Integration test:** `tests/test_api_v2_watch_defense_integration.py` — **7 passed** (both response shapes coexist; no route dropped).
- **Combined validation:** agent_runtime **264/9** · Watch **173/1** · Defense **54** · affected API **40** · authority scan PASS (29 files) · migration refusals 3/4/5 · deploy-boundary 2 · systemd verify exit 0 · `bash -n` 12 scripts OK · frontend build (design-token 256, chip-scope, tsc, vite 1276 modules) PASS.
- **Live Playwright route fixtures** (`vite preview`, API intercepted): `/v3/agents`, `/v3/watch?tab=watchlist`, `/v3/defense`, `/v3/sectors` — navOk, **0 page errors, 0px horizontal overflow, 20 nav links intact**; agents labeled SHADOW/STALE/fixture (not live); Defense/Sectors show RESEARCH WATCH / AVOID-REDUCE / NO DECISION; Watch one sovereign decision. Only console line is a **pre-existing** `/v3/cc-boot.js` 404 present at base — not an RC regression.

---

## Phase 3 — operator execution packets (prepare-only, nothing executed)

Under `scripts/operator_packets/` on the RC branch. Each: `set -euo pipefail`, exact-RC-SHA gate,
prints `PREPARE-ONLY`, refuses to mutate without an explicit `--execute`/`--apply`/`--run-shadow`
flag **and** a typed ack token; never prints password/DSN values.

| Packet | File | Key gates / behavior |
|---|---|---|
| **A1** LAB/SHADOW persistence | `packet_a1_lab_persistence.sh` | applies `0001`+`0002` to isolated LAB only; **rejects prod DB identity/port/host before any connection** (dbname `trade_ai`→exit 4, port 5432→4, `prod` substring→4, off-allowlist→4); writer/reader isolation proof; `--down` rollback; 0600 evidence log |
| **A2** read-plane deploy | `packet_a2_read_plane_deploy.sh` | SHADOW reader DSN only (writer/admin/prod DSN→exit 4); backup + atomic swap + one restart; **503-before / 200-after** smoke; `/v3/agents` browser smoke; auto backend+static rollback |
| **B** Watch deploy | `packet_b_watch_deploy.sh` | **four independent acks**: backfill / backend-reload / static-swap / packet-rebuild; 5-symbol + 200-card acceptance; restores dist on rollback; **never touches Watch schedules** |
| **C** Defense/Sectors deploy | `packet_c_defense_deploy.sh` | UI+API deploy, then breadth→v4 switch **only after payload validation**; **v10 hard-disabled** (enable attempt→exit 2); independent rollback of static / backend / breadth-producer / payload snapshot |
| **D** SHADOW acceptance | `packet_d_shadow_acceptance.{py,sh}` | default-disabled; ≥100 artifacts + ≥20 known-bad; full metric set; **promotion attempt raises `AuthorityViolation`**; reviewer≠producer, scorer≠producer in record constructors; non-prod SHADOW DSN enforced |

Validation: `bash -n` all 5 shells pass; `py_compile` runner passes; no-args → PREPARE-ONLY + non-zero;
wrong-SHA gate blocks; A1 prod-DB/port rejection fires before any connection; authority scan clean
(every broker/order/2FA string is a refusal guard or doc, never an invocation).

*Honest limitation:* Packet D's Python runner compiles and its guards are `--self-check`-verified, but
its concrete SHADOW population loop lazy-binds to the live persistence/Sentinel modules + SHADOW schema
at run time — prepared and guard-verified, **not runtime-exercised** (execution out of scope).

---

## Phase 4 — PR closeout

Evidence comment posted on each of #163, #182, #181, #180 and the RC #183. No PR marked ready.

### MERGE order — EXECUTED (2026-07-26, each with explicit operator authorization)
| Step | PR | Merge commit (`main` after) | Reconciliation / revalidation |
|---|---|---|---|
| 1 | **#184** | `8e395ebe` | release-readiness fix first → green on `main` |
| 2 | **#163** | `a9ec0d5d` | read plane; foundation, inert by default |
| 3 | **#182** | `32b32c47` | `agentic-mvl-ci.yml` conflict resolved with the validated A∩D fold; suite 264/9; migration refusals 3/4 |
| 4 | **#181** | `7a40eb35` | clean merge; Watch suite 244/1 |
| 5 | **#180** | `fc86150f` | `api_v2.py` clean 3-way; **composition test ported into `main`** (7/7 Watch+Defense coexist, no route dropped); Defense 54 |

Each lane was updated with advanced `main` in an isolated worktree, revalidated locally, and confirmed
green in CI (governance-contract / focused-quality-gate / defense-sectors-ci / backend / frontend /
release-readiness all pass) **before** merging. **RC #183 closed** — integration proof, never a merge path.

### Post-merge combined validator @ `fc86150f` (green)
agent_runtime **264/9** · api_v2 Watch+Defense composition **7/7** · Defense **54** · Watch sample
**139/1** · compileall OK · authority scan (.py) clean · migration refusals 3/4 · `main` CI:
`release-readiness` / `defense-sectors-ci` / `options-lifecycle-ci` **success**.

### Still NOT done (require separate operator authorization — the post-merge validator gate is now met)
Operator packets remain **prepare-only**; none run. No DB role/migration, DSN/secret, service/timer,
Defense breadth-producer switch, valuation backfill, deploy, or agent activation performed.

### Recommended DEPLOYMENT order (each operator-gated, separate authorization)
1. Isolated LAB/SHADOW schema + roles (Packet A1).
2. Read-plane backend/frontend on the SHADOW reader DSN (Packet A2).
3. Watch backend/frontend + separately-authorized valuation backfill (Packet B).
4. Defense/Sectors UI/API (Packet C step 1–2).
5. Defense breadth-producer switch to v4 (Packet C step 3; v10 stays disabled).
6. SHADOW acceptance population (Packet D).
7. Agent timers only after measured maturity-gate acceptance.

### Actions requiring operator authorization
All five delivery PRs are merged; **no further merge is pending.** Remaining operator-gated actions (none
performed): create/enable DB roles · apply migrations · provision the read/SHADOW DSNs + set the API
gate · run any packet `--execute`/`--apply`/`--run-shadow` · switch the Defense breadth producer · run
`watch_valuation_backfill.py` · enable agent systemd timers.
*(GitHub billing is already resolved — no longer a prerequisite.)*

---

## Final authority markers
```
production_database_write|NONE
production_service_change|NONE
production_schedule_change|NONE
provider_activation|NONE
valuation_backfill_execution|NONE
broker_or_order_action|NONE
approval_or_2fa_action|NONE
main_merge_action|5 PRs merged with per-step operator authorization (#184,#163,#182,#181,#180; #183 closed)
production_deployment_action|NONE
agent_operational_promotion|NONE
final_status|PASS_NON_ACTIVE_TRADER_RELEASE_MERGED — main=fc86150f, post-merge validator green
```
