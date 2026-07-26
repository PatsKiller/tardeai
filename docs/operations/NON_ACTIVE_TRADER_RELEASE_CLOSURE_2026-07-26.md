# Non–Active Trader Release-Closure Sprint — Closeout (2026-07-26)

Converts the four prepared lanes into exact-ref, conflict-tested, operator-deployable release
candidates. **Active Trader out of scope and untouched.** No PR merged to `main`, none marked ready,
nothing deployed/migrated/scheduled/activated/backfilled. Base `main` = `20a24027`.

## Top operator prerequisite (blocks ALL CI)
**GitHub Actions account billing block on `PatsKiller`.** Every workflow (`agentic-mvl-ci`,
`options-lifecycle-ci`, `reentry-watch-operator-ci`, `release-readiness`, and the new
`defense-sectors-ci`) dies in ~4s with *"the job was not started because recent account payments have
failed or your spending limit needs to be increased"* — on **every branch including `main`**. This is
why the red gates had "no usable job logs." **All lane code validates green locally**; CI cannot turn
green until Billing is resolved (operator action, outside program authority).

---

## Phase 1 — red CI gates closed (each fix workflow/test-only, no product change)

| Lane | PR | Frozen → validated head | Red-state diagnosis | Fix | Local result |
|---|---|---|---|---|---|
| **A** read plane | #163 | `a65fd529` → **`785b9f6b`** | (6) billing block | evidence-hardened `agentic-mvl-ci.yml` | 215/9; contract tests, authority, frontend 11, tsc/vite, guards all pass |
| **D** SHADOW agents | #182 | `d4671a32` → **`b09424eb`** | (3) missing `psycopg2` dep | add `psycopg2-binary` + recursive scan | 49 Lane D + 224/9; migration refusals 3/4/5; systemd verify; independence enforced |
| **B** Watch | #181 | `4472c9ca` → **`dbdd7438`** | (2) stale path/test-list + (3) dep | removed 6 unowned refs (documented); **fixed 2 red UI tests to the real sovereign/quality contract** | 173/1 (was 8 failed); 134 packet/API; guards pass |
| **C** Defense/Sectors | #180 | `2190c6ca` → **`eaa653f8`** | no focused workflow existed | added `defense-sectors-ci.yml` (lane-scoped, evidence-preserving) | 54/54; build green; switch-packet dry-run inert |

Each lane's evidence comment is posted on its PR. No substantive test was weakened or deleted.

---

## Phase 2 — conflict-tested release candidate (draft PR #183)

- **Branch** `codex/non-active-trader-release-candidate-v1`, from `main` `20a24027`, head **`cc3fd466`** (Phase 2) → **`8315a3a9`** (Phase 3).
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

### Recommended MERGE order
1. **#163** (read plane) — foundation the others reference; inert by default.
2. **re-resolve #182 against advanced `main`, then #182** — layered on runtime already in `main`; stays default-disabled.
3. **#181** (Watch) — resolve nothing new; `api_v2.py` Watch hunks are function-local.
4. **merge advanced `main` into #180, revalidate the composed `api_v2.py`, then #180** — the one file both #181 and #180 touch; re-run `test_api_v2_watch_defense_integration.py` after.

*(The RC branch #183 is integration proof, not a merge path — merge the lanes individually in this order.)*

### Recommended DEPLOYMENT order (each operator-gated, separate authorization)
1. Isolated LAB/SHADOW schema + roles (Packet A1).
2. Read-plane backend/frontend on the SHADOW reader DSN (Packet A2).
3. Watch backend/frontend + separately-authorized valuation backfill (Packet B).
4. Defense/Sectors UI/API (Packet C step 1–2).
5. Defense breadth-producer switch to v4 (Packet C step 3; v10 stays disabled).
6. SHADOW acceptance population (Packet D).
7. Agent timers only after measured maturity-gate acceptance.

### Actions requiring operator authorization (NONE performed)
Resolve GitHub Billing · create/enable DB roles · apply migrations · provision the read/SHADOW DSNs +
set the API gate · run any packet `--execute`/`--apply`/`--run-shadow` · switch the Defense breadth
producer · run `watch_valuation_backfill.py` · enable agent systemd timers · mark any PR ready · merge.

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
main_merge_action|NONE
production_deployment_action|NONE
agent_operational_promotion|NONE
final_status|PASS_NON_ACTIVE_TRADER_RELEASE_CLOSURE
```
