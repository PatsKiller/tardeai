# Trade AI audit follow-up — 2026-09-28

Status: ACTIVE
as_of: 2026-09-28
Authority: READ_ONLY_ADVISORY
Follow-up to PR #1350. This document does not promote a release and does not change the options arm.

```
measured_at_utc: 2026-09-29T02:12:49Z .. 2026-09-29T02:16:00Z
measured_at_et: 2026-09-28 22:12:49 .. 22:16 EDT
clock: America/New_York EDT (UTC-4)
served_content_sha: 25afedb355108e11aa664c495081939aaaeb33b4
served_ui: 3.14+mulrnppm
built_at: 2026-09-28T21:35:33.090Z
process_pid: 723294
process_start_et: 2026-09-28 21:48:58 EDT
new_window_start_et: 2026-09-28 21:48:58 EDT
release_git_head: f306b5e6dadce417ba68ae33eba009982ecab23c
origin_main: f306b5e6dadce417ba68ae33eba009982ecab23c
pr_1350: OPEN, not merged, head ff911a4c350d2acd34ed3eebd38d786a0fe575f9
pr_1350_audit_commit: f36951b36a2b1e975efb4a7c71fe12045d071350
```

The 21:41 ET audit window does not describe this process. Same content SHA, new PID, new window.

---

## 1. Current pin and health receipt

| Check | Result |
|---|---|
| `CURRENT` | `/home/johnclaw/trade-ai-releases/portfolio-server/25afedb35-main-exact-phase2-20260928-173440` |
| `GET /v3/build-meta.json` | HTTP 200, 517 bytes, 0.001s. `git_sha` `25afedb355108e11aa664c495081939aaaeb33b4` |
| Process | user `portfolio-server`, PID 723294, cwd that release, `PYTHONPATH` that release's `scripts/` |
| Restart | `Restart=always`. `NRestarts` 5. `ActiveEnterTimestamp` 2026-09-28 21:48:58 EDT |
| Sockets on :7777 | 1 `CLOSE-WAIT`, 1 `ESTAB` at 22:12 ET. Process `poll_schedule_timeout`, 21 threads |
| `GET /api/v2/health` | HTTP 200, 38200 bytes, 0.017s. `ok` true. 8 critical, 18 warning, 20 info (46) |
| `GET /api/v3/cio/home` | HTTP 200, 229664 bytes, 1.79s |
| `GET /api/v2/overview` | HTTP 200, 0.06s. `today_change` −2412.59, `position_count` 10, `as_of` 2026-09-28 |
| `GET /api/v2/portfolio/book-map` | HTTP 200, 0.02s. `total_day_change` −2380.91, 25 rows, `securities_only` true |
| `GET /api/v2/options/proposals` | HTTP 000, 0 bytes, killed at 20s |
| `GET /api/v2/buy-ready/packets` | HTTP 200, 0.01s. `as_of` 2026-09-29T02:14:38Z. 7/7 `PACKET_UNVERIFIED` |
| `GET /api/v2/options/execution/status` | HTTP 200, 0.01s. `armed_for_execution` true, `options_execution_enabled` true, `policy_ENABLED_commit` true |
| Memory influence | `MEMORY_BEHAVIOR_INFLUENCE=0` on PID 723294. `GOVERNED_MEMORY_ADVISORY_INFLUENCE=SHADOW` |

No broker order, cancel, 2FA ceremony, Telegram send, schema migration, or arm change was performed.

### How HTTP came back

The hung PID 435701 from the audit ended at 2026-09-28 21:40:52 ET. systemd logged `Scheduled restart job, restart counter is at 4` and started a new process at 21:40:58 ET. That process ended at 21:48:52 ET (`Consumed` 1 min CPU over 8 min, memory peak 1.7G; `MemoryHigh` is 1.5G, `MemoryMax` is 2G). systemd started PID 723294 at 21:48:58 ET, counter 5. Kernel journal for 21:30–21:55 ET had no OOM line. The journal does not name a signal. Causation of the unread-socket stall is not proven. What is proven: `Restart=always` replaced the process twice, and the current process answers build-meta in about 1ms.

The proposals handler still returns nothing within 20s on this new process. A slow proposals request is not, by itself, the whole-server stall: build-meta stays fast while proposals sits. F-27 and F-03 are related candidates, not a demonstrated single cause.

---

## 2. F-01–F-27 disposition

States: `STILL_PRESENT`, `RESOLVED_WITH_PROOF`, `CHANGED_PIN_REMEASURE`, `NOT_MEASURED`, `FIX_READY_UNSERVED` (code in this follow-up PR, not on the served tree).

| ID | State | Evidence | Impact | Next safe action |
|---|---|---|---|---|
| F-01 | STILL_PRESENT | Status GET 22:14 ET, same SHA. DB arm not edited. No order id. | Standing arm since 2026-06-22 still reads as armed. | Operator retain-or-revoke. Section 3. Do not flip it in a deploy. |
| F-02 | STILL_PRESENT | Served `MAX_SPREAD_WIDTH_PCT = 15.0`. Desk cap remains 12. Not edited. | A 13% width can pass `evaluate()` and fail the desk. | Ship a reviewed tightening only after the operator accepts 12% as the execution cap. This order forbids a guardrail change, so no patch was merged here. |
| F-03 | STILL_PRESENT | Proposals GET, PID 723294, 20s, 0 bytes, 22:14 ET. | Options list can look empty. | Trace the handler on a copy. Do not restart the live process to "clear" it. |
| F-04 | STILL_PRESENT | Health critical `release_manifest_fail` still in the 22:12 ET payload. | Stale red critical. | Regenerate the manifest under a docs/ops change. Not done. |
| F-05 | STILL_PRESENT | One full dump: `~/db_backups/trade_ai_20260919_134639.sql.gz`, 3.3G, mtime 2026-09-19 14:06:44 ET. Age about 224h vs 26h. Nightly `pg_dump` fails. Disk 110G free. | No dump newer than 19 Sep. The file was not restore-tested. | Authorize a backup role that can copy `FORCE` RLS tables, then a restore check. Re-running the same script fails the same way. |
| F-06 | STILL_PRESENT | 8 criticals remain: manifest, 6 stuck paper tests, Hermes unclassified 5, DeepSeek 55/126, SIEM 8, scalp GO not converting, backup step, stale dump. Warnings 18 (was 17). | Board still loud. | Triage ids. Do not clear from the UI. |
| F-07 | STILL_PRESENT | Since 21:48 ET: Sentinel and Iris `total` 0, `leased` 0. Darwin one dispatch `total` 8, `REFUSED_STALE` 8, `COMPLETED` 0. | Runners fire and finish no review. | Leave SHADOW. Do not stuff the queue to score the board. |
| F-08 | STILL_PRESENT | `tradeai-agent-runtime@sentinel` `WorkingDirectory=CURRENT`, `PYTHONPATH` = rebuild `scripts/`. | Agent imports can leave the release. | One unit change in a reviewed ops PR. Not restarted here. |
| F-09 | STILL_PRESENT | No schema apply. Production absence and the August lab store are unchanged by this pass. | Three lesson stores. None is a live MVL. | Migration plan only. Section 6. No apply. |
| F-10 | NOT_MEASURED | 18:20 ET sweep was the audit's natural fire. No new sweep slot yet (next 2026-09-29 18:20 ET). | Prior scored 0 stands as last sample. | Read the next natural sweep. Do not run it by hand. |
| F-11 | CHANGED_PIN_REMEASURE | Nightly reflection 21:50:13 ET, exit 0, on `CURRENT/.../cio_nightly_reflection.py`. Blob `6365911c…` equals stamp `25afedb35`. `cases_seen` 3096, `scored` 2764, `proposal_count` 1, `auto_promotions` 0, `mutates_production` false. Iris leases still 0. | Reflection ran and did not promote. Ratification still absent. | Not a closed lesson loop. |
| F-12 | NOT_MEASURED | Heartbeat `release_sha` was not re-queried. | Pin of beats still unknown from this pass. | A later read of new rows. |
| F-13 | NOT_MEASURED | Outbox mtime was not re-read. | Prior dark outbox is not re-proven tonight. | A later file read. Do not send Telegram to test it. |
| F-14 | STILL_PRESENT | Release reflog: `merge origin/main: Fast-forward` to `25afedb35` at 17:34:39 ET, then to `f306b5e6d` at 20:26:24 ET. Checker exit 2 at 22:16 ET: five paths match the stamp blob, HEAD does not. Invoker not in the service journal. | `git rev-parse` in the release dir is #1339. The process loaded the stamp. | Use the checker. Do not fast-forward this live tree. Do not promote #1339 for that reason. |
| F-15 | STILL_PRESENT | `run_options_monitor.sh` sets `PROJECT_ROOT` to the rebuild tree and `cd`s there. Cron still starts from `CURRENT`. | Monitor code is not the release. | Point the launcher at `CURRENT` in an ops PR. Next natural slot 2026-09-29 12:00 ET. |
| F-16 | STILL_PRESENT | `tradeai-active-trader-motion` PID 2581033, cwd `.../active-trader/306f81799…`. Moomoo OpenD still the lab tree. | Those processes do not follow portfolio promote. | Operator names them served or lab. No mass restart. |
| F-17 | NOT_MEASURED | Registry versus timer recount was not repeated. | Audit's retired-but-enabled pair is the last full sample. | Recount before any timer edit. |
| F-18 | STILL_PRESENT | Funnel `as_of` 2026-09-29T02:15:01Z. `summary.cc_eligible` 3. `cc_by_status.CC_ELIGIBLE` 1. `holdings_scanned` 13. `put_eligible` 0. | Two eligible counts. | Label the denominators. Do not pick one in the UI without a test. |
| F-19 | STILL_PRESENT | Gate recompute 2026-09-29T02:15:22Z. Denominator 41009 actions (was 40022 at 01:19Z). Still 1 / 3 / 8. No SHA filter. | Population pass is the whole ledger. | Publish both denominators later. Do not hardcode. |
| F-20 | NOT_MEASURED | The four dark lanes were not re-statted. | Not a fresh outage claim. | Re-stat files before treating them as down. |
| F-21 | STILL_PRESENT | Packets `as_of` 2026-09-29T02:14:38Z. SWK, NYT, TDG, TSLA, PEW, AXTI, DXCM all `PACKET_UNVERIFIED`. DELL and SCHD `NO_PACKET` (63-byte GETs). | Withhold holds. #1339 `packet_view` blob `8df55f81…` is not the file on disk (`fae5af7f…`). | Leave the withhold. Promote only a clean tree of a reviewed SHA, then read a natural packet. |
| F-22 | STILL_PRESENT | Header −2412.59, book −2380.91, gap −31.68, same `as_of` 2026-09-28. | Two day P/L figures. | Label scope. The residual line is still unnamed. |
| F-23 | STILL_PRESENT | Overview `position_count` 10, book rows 25. Holdings count was not re-fetched. | Counts still differ. | Name the filters. |
| F-24 | STILL_PRESENT | Execution status says armed. Card `live_eligible` was not re-listed because proposals timed out. Prior pass: cards 0 eligible, execution path `live_eligible` true. | The word still spans two facts. | Additive label in a reviewed API change. Arm unchanged. |
| F-25 | NOT_MEASURED | Broker recon was not re-fetched. | 31 / 19 sample is the audit's, not a new break list. | Re-read before repair. No UI auto-repair. |
| F-26 | NOT_MEASURED | SCHD case store was not re-read. No chat seeded. No case recorder `--apply`. | Audit result stands: correction is not a wake input. | Persistence unproven. Section 6. |
| F-27 | CHANGED_PIN_REMEASURE | Build-meta 200 in 0.001s at 22:12 ET on PID 723294. Same SHA. Stall of PID 435701 ended by systemd restart, not by this follow-up. | Site answers again. The stall can return; proposals still hang. | Watch restart counter and proposals latency. Do not treat restart as an end-to-end fix. |

Nothing in this table is `RESOLVED_WITH_PROOF`. A restart, a green unit test, and an open PR are not that state.

---

## 3. Options arm decision record

Current effective authority, re-read 2026-09-29T02:14Z on stamp `25afedb35`, PID 723294:

- Database `options_execution_enabled` is true. Status `updated_at` was 2026-06-22 on the prior read. This follow-up did not write the row.
- Served `options_execution_policy.ENABLED` is `True`. The docstring in that file still says the default is off.
- `GET /api/v2/options/execution/status` returns `armed_for_execution: true` when both are true. The note on the payload says both the DB flag and the commit flag are required for live submit.
- `evaluate()` also checks account allowlist, strategy, order type, contract count, notional, and credit-spread width at 15%. It does not check 2FA.
- Per-order 2FA is a separate function (`request_2fa` then `submit`). It was not called.
- Autonomous submit was false on the 01:26Z read of the live-trading gate (`PAPER_ONLY`, `all_gates_passed` false, `per_order_2fa_required` true). That gate was not re-fetched in this follow-up.
- Card-level `live_eligible` on the proposal list was 0 at 01:23Z. The list did not return again at 22:14 ET, so card eligibility was not re-measured.
- No live order was placed.

**Retain.** Leave the June 22 flag and `ENABLED = True`. Operators must keep reading `armed_for_execution` as a standing unlock, not as a fresh ceremony, and must not treat it as permission to skip per-order 2FA. Consequence: the status page stays armed; submit still has to pass policy `evaluate()` and the 2FA path that `submit()` calls. A misleading label can remain until a reviewed copy change.

**Revoke.** Operator uses the existing revoke phrase in the product (not printed here). Consequence: `armed_for_execution` becomes false on the next status read, `updated_at` moves, and `evaluate()` may still be reachable in code but the arm conjunction fails. Rollback is the existing approve phrase, which is a new ceremony, not a git revert.

This follow-up does neither. The flag stays as it was.

---

## 4. Dependency plan

| Order | Item | Safety | Owner | Effort |
|---|---|---|---|---|
| 1 | Backup role that can `COPY` `FORCE` RLS tables, then a restore of the new dump into a scratch database | Data safety. Not a trading change. Needs a DB privilege grant. | Operator plus whoever holds the Postgres role | One cadence, then a restore check |
| 2 | Stop fast-forwarding the live release worktree. Next promote is a new directory from a reviewed SHA | Prevents F-14 | Release operator | Use the existing exact-main prepare/promote. Do not `git merge` inside `CURRENT` |
| 3 | Arm decision (section 3) | Changes who can submit | Operator only | One phrase, or an explicit retain |
| 4 | Proposals handler timeout and a named error (F-03) | Usability. No order path | Desk | A PR, then a natural GET under 5s after promote |
| 5 | Execution spread cap aligned to desk 12% (F-02) | Tightens, does not loosen. Still a guardrail change | Operator accepts, then a PR | Hermetic 13% case |
| 6 | Sentinel `PYTHONPATH` and options-monitor `PROJECT_ROOT` point at the release | Stops dev code on served timers | Ops, one unit at a time | Not 117 timers |
| 7 | Memory loop, influence still 0 | No schema apply until a reviewed plan | Architecture | Section 6 |
| 8 | #1339 only as its own exact promote after cio-hardening is green | Options packets | Release operator | New window after that SHA is the process |

---

## 5. What this follow-up changed in git

`scripts/check_release_pin_integrity.py` compares a release directory's build stamp, `git HEAD`, and the blobs of five paths. It does not checkout or merge.

Hermetic tests: `tests/test_check_release_pin_integrity.py`, 3 passed (clean match, HEAD moved with stamp bytes kept, tampered file). The first remote `cio-hardening` run failed because that file was not on the CI allowlist (`tests/test_ci_test_coverage_gate.py`, run 36511932034). The corrective commit registers it on the existing `release_pin_and_validator` gate. That registration is not a served install, and this document does not call the second run green until GitHub says so.

Live read-only run against the served directory, stamp `25afedb35`:

- Exit **2**
- `head` `f306b5e6d`, `head_matches_stamp` false
- All five paths `match: true` against the stamp blob, including `buy_ready_options_alternatives.py` `fae5af7f…` (the #1339 blob is `8df55f81…`)

That run is detection, not a served install. The script is **FIX_READY_UNSERVED** until this PR is merged and a release actually contains it. Merging the PR does not put it on the portfolio-server process.

The corrective commit also edits `scripts/run_cio_hardening_ci.py` so the new test is collected. F-02, the arm, the schema, and the cron table were left alone.

---

## 6. Memory, gates, MVL

12-gate recompute at 2026-09-29T02:15:22Z, `cio_gate_measurement_bridge.py --json` only (no `--write-measurements`, no `--update-catalog`). Root is the live release. `memory_behavior_influence` in the output is 0.

| | 01:19Z audit | 02:15Z this pass |
|---|---|---|
| Actions in the ledger denominator | 40022 | 41009 |
| Passing | 1 (population ≥ 100) | 1 |
| Failing | provenance 0, review coverage 0, score coverage ~0.19% | same three, now 0/41009 reviews and 78/41009 scores |
| Not yet measured | 8 | 8 |
| Promotable | false | false |

The extra ~987 actions are ledger growth, not a new gate design. F-19 stands: the pass is lifetime population.

M1–M5 were not re-read from the jsonl stores in this pass. The audit's dated historical proofs (M1 2026-09-25T00:03:26Z, M2 2026-09-25T14:01:24Z, M3 2026-09-24T22:10:24Z) stay `OBSERVED_HISTORICAL`. They are not promoted because the PID changed. A fresh M1–M3 sample on PID 723294 is **NOT_MEASURED**. M4's header-versus-book gap was re-measured and is still −31.68. M5's influence flag on the new PID is 0.

v3.3 MVL acceptance is not met. The one new natural row is the 21:50 ET reflection: 3096 cases seen, 2764 scored, 1 proposal, 0 auto-promotions, `mutates_production` false. That is a producer fire with an explicit non-mutation. It is not 100 reviewed Watch artifacts, not a 95% score rate, and not a ratified lesson cited later.

Schema: do not point readers at `trade_ai_agentic_lab`. Do not apply `migrations/agentic_runtime/0001_mvl.up.sql` to production to grow a count. A future migration needs its own grant, a down migration that is not a table drop, a dual-read proof, and a reader that names one store. That plan is not implemented.

SCHD (F-26): this pass did not run the case recorder and did not seed a chat. Agent persistence of the correction remains unproven. The audit's evidence stands until a case id exists in `cio_production_cases.jsonl` and a later retrieval cites it with influence 0.

---

## 7. API and options parity (this window)

| Surface | HTTP | Time | State |
|---|---:|---:|---|
| Build meta | 200 | 0.001s | WORKING as an identity stamp. SHA matches the process cwd. Git HEAD does not. |
| Health | 200 | 0.02s | DEGRADED. Score still carries 8 criticals. |
| CIO home | 200 | 1.8s | WORKING as a read. Authority remains advisory. |
| Overview header | 200 | 0.06s | DEGRADED beside the book (−2412.59 vs −2380.91). |
| Book map | 200 | 0.02s | Matches performance 1D from the audit's pair. 1D was not re-fetched. |
| Execution status | 200 | 0.01s | Armed. Not a fill. |
| Buy-ready packets | 200 | 0.01s | 7 withheld. Containment holds. |
| Symbol DELL, SCHD | 200 | <0.01s | `NO_PACKET`. No 520/500 row to age. |
| Proposals | 000 | 20s | DEGRADED. Same failure mode as F-03, new PID. |
| Holdings funnel | 200 | <1s | DEGRADED. 3 vs 1. |
| Chain click, payoff, narrow viewport | — | — | NOT_MEASURED. No browser. |
| Supervised one-lot | — | — | NOT_MEASURED. Not performed. |

Telegram was not sent. A same-timestamp alert-versus-queue comparison was not made.

---

## 8. Natural-fire calendar (ET)

| When | What would count | What would not |
|---|---|---|
| Already, 2026-09-28 21:50 | Reflection JSON above. Recorded. | auto_promotions 0 is not ratification |
| 2026-09-29 02:30 | Backup cadence. A new `trade_ai_*.sql.gz` over 1.5GB plus a scratch restore | Another RLS `COPY` error, or exit 0 with `portfolio_backup FAILED` |
| 2026-09-29 09:00 | Orchestrator log whose path is this release | A log left in an older release dir |
| 2026-09-29 12:00 | Options monitor log. Then a proposals GET | A log under the rebuild tree |
| 2026-09-29 18:20 | Sweep `scored` and the unfalsifiable count | A manual `--apply` |
| 2026-09-29 18:50 | Belief writer, influence still 0 | A behavior-sized key |
| After any exact promote | New build-meta SHA, new PID, checker exit 0, fresh window | A fast-forward of this directory's git HEAD |

---

## 9. Rollback and monitoring

- This PR rolls back by not merging. The served process does not contain the checker.
- Do not restart portfolio-server as a rollback. The current PID is the recovered process.
- Watch: `NRestarts` on `portfolio-server` (now 5), proposals latency, backup.log for `row-level security`, and `git -C $CURRENT rev-parse HEAD` versus build-meta. A HEAD move without a new PID and a new stamp is F-14 again.
- Influence stays 0. Desk spread cap stays 12%. Credit floor stays 0.25. The June 22 arm stays until section 3 is answered.
- #1339 (`f306b5e6d`) stays on `origin/main` and stays off the process until a separate promote receipt names that SHA and the checker then exits 0 on a new directory.

---

## 10. Operator decisions still open

1. **June 22 options arm.** Retain or revoke, using section 3. This follow-up did not choose.
2. **Backup privilege.** Authorize a dump role that can copy `FORCE` row-level security tables (`memory_r10_m2.adjudication_receipt` failed every night 21–27 Sep; `intelligence.embedding` failed on 28 Sep), then verify a restore. Do not treat a re-run of `run_pg_backup.sh` as protection.
3. **Schema.** Do not promote `agentic_runtime` into production `trade_ai` to change the gate board.
4. **#1339.** Do not fast-forward the live tree onto it. A later promote is a new release directory, a green cio-hardening, and a new observation window.

---

## 11. Closeout mail

The operator recipient is the address already set in `scripts/email_notifier.py`. The mechanism is `gog` 0.12.0 `gmail send` on that same account. This is not a resend of the 21:41 ET audit (`1a0ead357fe6e329`).

Sent after the report commit `e2f29d4dc` was opened as PR #1351. Gmail accepted the message. The attached markdown is that commit, so it does not contain this section.

| Field | Value |
|---|---|
| Status | SENT (labels `UNREAD`, `SENT`, and `INBOX` on a later get) |
| message id | `1a0eaf4807b36fef` |
| thread id | `1a0eaf4807b36fef` |
| Date header | Tue, 29 Sep 2026 02:18:07 +0000 |
| UTC | 2026-09-29T02:18:07Z |
| ET | 2026-09-28 22:18:07 EDT |
| Subject | Trade AI audit follow-up 2026-09-28 — pin still 25afedb35 — arm decision |

An attempted send is not this row. The row is a Gmail message id that a later get returned with label `SENT`.
