# Cross-Asset Decision Intelligence — Test Plan

Status: ACTIVE  
Owner: Agent A and independent QA; Parfit model owner, Halley independent model-risk reviewer
as_of: 2026-10-09T11:42:14-04:00
Measured at: isolated CADI-01 clone on base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`; fixtures only
Current ticket: **CADI-01 SOURCE REGISTRATIONS APPROVED; FINAL ACCEPTANCE PENDING**
Program readiness: **NOT READY**
Current results: **121 combined PASS; 80 core PASS (overlap); 15 adversarial PASS**; post-approval authority/full acceptance **PENDING**

### Source-approval checkpoint — 2026-10-09

John's explicit approval of both named stores and their sole writer is retained in the
[approval archive manifest](governance/CADI01_SOURCE_APPROVAL_ARCHIVE_MANIFEST_20261009.md#cadi01-source-approval-20261009).
The native authority gate and full acceptance will rerun after integrating latest main.
Older BLOCKED/exit-1 records below remain the before-state evidence, not current approval status
and not a passing acceptance receipt. No production activation or data-store mutation occurred.

## Current validation contract — 2026-10-09

The following matrix records the current CADI-01 fixture results against required cases.
September test counts and zero-signal replay records remain intact below; they do not validate
the current v2 migration. Only CADI-01 begins
now. No downstream branch starts before Agent A merges it; CADI-08 reviews evidence throughout.
Run isolated fixtures/temporary stores, not production writes, live providers or broker calls.
The coordinator registered the new suite in GATES, classified all four output schemas and
regenerated the authority documentation and INDEX. No production data was written.

### CADI-01 acceptance — must land alone

| ID | Required case | Pass evidence | Current result |
|---|---|---|---|
| V2-U1 | Adapt `cross_asset/symbol_decision_object.py` v1 | Eleven groups, preserved provenance/history, explicit missing values | PASS; full original payload and 100 audit entries retained |
| V2-U2 | Adapt incompatible `cross_asset_decision.py` v1 | Identity/action/evaluation references preserved; no ambiguous reinterpretation | PASS; heuristic winner not promoted |
| V2-U3 | v2 validation and round-trip | Reject invalid authority; preserve account context, source/availability times and model refs | PASS; malformed GUID/identity/time/authority refused; canonical model remains null |
| V2-U4 | Fifteen supported action classes and documented aliases | Explicit normalized action; no fabricated BUY or silent none | PASS; all 15 plus space/hyphen/case normalization |
| V2-U5 | Batch containing valid → unknown → valid actions | Both valid evaluations survive; bad row yields visible error receipt with symbol, raw value, source/event reference; batch reports partial failure | PASS; persisted errors survive reopen/idempotent retry |
| V2-U6 | Unknown/missing/malformed action in first/last/all rows | Error is recorded, not swallowed; remainder continues; all-error batch cannot claim completed decisions | PASS; six falsy legacy values and all-error batch covered |
| V2-P1 | Historical v1 ledger bytes before/after adapter reads | No mutation, deletion, reordering or rewrite of prior rows | PASS on fixtures; production ledgers not imported |
| V2-P2 | Repeated event/evaluation append | Exactly one durable evaluation for the idempotency key | PASS; differing content under same ID refused |
| V2-P3 | Concurrent append and restart | Complete non-interleaved records survive; latest views recover consistently | PASS; 24 concurrent duplicate requests; four processes; reopen (not a power-loss test) |
| V2-P4 | Rebuild latest projection from history | Equivalent projection; immutable ledger unchanged | PASS; out-of-order/offset/submillisecond ordering tested |
| V2-P5 | Malformed history row and interrupted/failed write | Visible diagnostics, valid history remains recoverable; no false success or truncation | PASS; forced SQL rollback, corrupt-history rebuild rollback, simulated disk error; hard-kill not run |
| V2-A1 | New history and every rebuildable projection store | Each registered in DSA with one writer, served/read path and real operator approval | APPROVED REGISTRATION; native authority rerun pending; one writer each, no activation |
| V2-A2 | New decision/projection/error output schemas | Classification registry covers all; payload-flow/authority guards pass | PASS on prior fixtures; all four classified, three audit record edges verified; post-approval full acceptance pending |
| V2-A3 | Account coverage and unknown quantities | Split accounts cannot fake a 100-share cover; missing cash/shares remains unknown | PASS; aggregate legacy cover reset to unknown; account-aware linking is CADI-02 |
| V2-A4 | Authority/refusal and dry-run | Advisory-only, no live/broker reach; dry-run cannot reach durable mutation | PASS; no DB created by dry-run; no production caller |
| V2-G1 | Legacy consumers and fixtures | Both v1 compatibility suites remain green; no unrelated source regression | PASS; 19 compatibility tests in targeted run; broader acceptance separate |

Gate outcomes must be quoted with exact command, cwd/base/head SHA, exit and actual assertions.
Failure counts are **NOT RUN**, not zero. An absent operator approval is BLOCKED; no fabricated
approval block, lowered baseline or skipped test may make authority green.

### Future phase acceptance (planned, not started here)

| Category / ticket | Required scenarios and proof |
|---|---|
| Unit / CADI-02/03 | Unknown/stale sources, unresolved identity, account-local positions; independent share/single-leg/spread/collar payoff cases; executable bid/ask and cost/assignment limitations |
| Integration / CADI-02/05 | Same sourced research reaches consumers; event receipt references source versions; out-of-order availability does not expose later information |
| Persistence / CADI-05/06 | Queue restart/retry/reclaim, dedupe/coalescing, lock contention, retained history and rebuildable latest views; no duplicate writer |
| CIO / CADI-02/07 | Current/historical decisions and changes traced; policy/CIO procedural blockers separated from liquidity/economic constraints |
| Research / CADI-02/05/07 | Completion/gaps/actual job id, priority, age and queue status linked; missing research is visible, not assumed from a completed receipt |
| Options routing / CADI-03 | All fifteen actions select required families or explain unavailable; same horizon/capital basis; no static rank presented as validated EV |
| Re-entry / Watchlist / CADI-02/03/05 | Original status/ownership and actual action preserved; re-entry is not assumed to become a CSP or stock fill; source update triggers a new evaluation |
| Scheduler / CADI-05 | Same-PR kind=n8n registry row and allowlist, fixed argv, dedicated safe_flock, real --dry-run, output_signal; forbidden command rejection and quoted cadence; no added cron/timer |
| Scheduler placeholder / CADI-05 | Expression remains placeholder until Agent A workflow plus granted operator import; temporary ORPHANED explicitly disclosed; first scheduler-shadow receipt reconciles id/status |
| Mode isolation / CADI-05/08 | scheduler-shadow=n8n dry_run versus decision-shadow=organic advisory persistence; receipt dimensions preserved; dry-run/manual/fixture receipts excluded from organic day totals |
| Retention packet / CADI-06 prerequisite | Read-only measured snapshot bytes/frequency/symbols/contracts/compression/index and peak space; actual pgvector reserve/floor; formulas and bounds reproducible; no values invented when unavailable |
| Retention authorization / CADI-06 | John names CADI_OPTIONS_ARCHIVE_RETENTION and approved budget/floor before ticket starts; PGVECTOR_DISK_FLOOR separate; unchanged policy/pruners pending approval |
| Forecast / CADI-04 | Parfit's artifact reproducible; Halley's independent review; chronological splits, purging, horizon embargo, date-clustered uncertainty and baseline metrics |
| Forecast freeze / CADI-04 | Config/preprocessing/cutoff/seeds/SHA frozen before held-out validation; minimum 504 sessions; horizons <=63; >=100 matured held-out forecasts on >=20 dates per horizon; changes force new version/untouched validation |
| Model authority / CADI-04 | Version/hash frozen per release; John promotes exact hash/supported scope; unapproved models cannot silently replace production artifact |
| Historical replay / CADI-06 | Real 30/60/90-calendar-day signals walked; then-available prices/quotes/research/events; no current-quote/revised-date/synthetic-premium backfill; repeats deterministic |
| Replay metrics / CADI-06 | Cohort denominators, reconstructed/priced/excluded/pending/matured counts and exclusion reasons; predicted EV vs illustrative scenario vs observed outcomes separated |
| Missed opportunity / CADI-06 | Missing proposal, correctly blocked alternative and demonstrated economic miss distinguished; actual decision known or unknown, not defaulted to shares |
| API/UI / CADI-07 | Cached source reconciliation, timestamps, stale/partial/no-winner labels, model version and lineage; desktop/mobile drill-through; page paint causes no research/fitting/replay |
| Regression / CADI-08 | Legacy research/identity/positions/options readers, authority/classification/payload-flow, no-broker tests and registered gates pass without production mutation |

### Readiness proof requirements

- `NO_PROVEN_WINNER` by default; change only with validated probabilities, complete economics,
  satisfied constraints and positive confidence bound on incremental net EV.
- `NOT READY` until targeted/regression/release-equivalent/authority acceptance and exact-SHA CI
  pass, independently reviewed forecast scope is operator-promoted, and real replay meets the
  historical proof requirements. Merely making signals_evaluated nonzero is not sufficient.
- At least **fourteen consecutive organic decision-shadow days**, with at least **99% eligible
  source events yielding evaluation/error receipts**. Include unknown-action error counts and
  failure/latency/coverage denominators; receipt coverage is not the same as successful economics.
- No untested critical/high-severity findings. A source being deployed or seven CI jobs passing
  does not substitute for these runtime proofs or operator release authorization.
- After an authorized release, independently verify served source/process/API/UI pin and rollback.
  Delivery checks compare all five Drive contents and actual email attachment/link receipts;
  a September status email is not a fresh package-delivery test.

### Current evidence log — documentation sidecar

| Date | Source base | Activity | Result |
|---|---|---|---|
| 2026-10-09 | `3b5c248569908adfad9a60ca895e0fa9b2aa2c49` | Read board/policies, inspect existing docs and source markers, revise five docs | Documentation/source inspection only |
| 2026-10-09 | Same base | Targeted / regression / release-equivalent / authority tests | **NOT RUN**; no current pass/fail count |
| 2026-10-09 | Same base | Replay / organic decision-shadow / model validation / release | **NOT RUN / NOT MEASURED**; no commit/PR/live proof claimed |

### Implementation evidence — supersedes the sidecar's NOT RUN entries

Worktree: `~/tradeai-wt-cadi01-20261009`; branch `wt/cadi01-canonical-decision-20261009`;
base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`. Interpreter is the existing primary repository's
`.venv/bin/python`, with cwd in the isolated clone. No environment file was copied or read.
Fixture stores are temporary SQLite files; no live data-store migration or broker calls.

```bash
cd ~/tradeai-wt-cadi01-20261009
"$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python" -m pytest -q \
  tests/test_cadi01_canonical_v2.py \
  tests/test_cross_asset_decision_intelligence.py \
  tests/test_cross_asset_symbol_decision_object_20260929.py \
  --junitxml=/tmp/cadi01-evidence-ASaxWf/targeted.xml
```

Measured result: **84 passed, 0 failed, exit 0, 5.51s**. This is 65 new CADI-01 cases plus
19 existing compatibility cases, not 84 independently validated investments. JUnit is retained
under `~/cadi-evidence/cadi01-local-20261009/`; hashes are recorded at local checkpoint.
Earlier broader selection: **97 passed / 8 failed**, all eight in
`test_data_source_authority_20260913.py`: clean gate, complete grants, real approval reference,
four stripped-field negative controls, and missing-approval control. The two pending new-store
rows add genuine findings to those controls. Tests and approval policy were not weakened.

`bash scripts/ai_local_acceptance.sh` runs with the shared virtualenv on PATH and an isolated
test PostgreSQL database, not the production DB. Observed source release-equivalent **17/17 PASS**,
policy tests **11 PASS**, lane registry structurally clean. Its CIO run covers 341 parallel units
and 20 serial units. It exited **1**: `maturity_overnight_20260912` contained the same eight
authority failures; `cio_operator_artifacts_20261003` found three operator-relevant schemas
without audit-read edges. The latter was reproduced independently, then repaired: the existing
operator-artifacts reader projects history/error/latest records directly from the single CADI
store with no copies, bounded reads, source timestamps and visible failure status. Production
reads require both source approval and separate activation; no setting changed here.
The previously failing completeness test then passed, and a combined post-fix run recorded
**111 passed / 0 failed / exit 0 / 170.98s**. Two additional approval/activation negative controls
were added and passed independently (3 parameterized cases). Final scoped rerun follows at checkpoint.
This is **not** final green acceptance; the full run began before final review fixes, so a final
exact-tree acceptance rerun is required after source approval and before push.

Independent read-only review cleared its scoped defects after repairs; final malformed actions
retain raw values and no longer become `NO_SIGNAL`. Ruff on new files, dark-contract, coverage,
source rendering and documentation gates must remain clean at the checkpoint. No remote push,
PR, merge, activation, production release, organic observation, model promotion, Drive sync or
email delivery is established by this evidence.

### Pre-final scoped validation — 2026-10-09 11:03 EDT

The final combined command uses the same interpreter/cwd as above:

```bash
"$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python" -m pytest -q \
  tests/test_cadi01_canonical_v2.py \
  tests/test_cross_asset_decision_intelligence.py \
  tests/test_cross_asset_symbol_decision_object_20260929.py \
  tests/test_cio_operator_artifacts_20261003.py \
  tests/test_cio_payload_flow_20261002.py \
  tests/test_cio_completeness_measurement.py \
  --junitxml=/tmp/cadi01-evidence-ASaxWf/targeted-final.xml --tb=short
```

**113 passed / 0 failed / exit 0 / 195.07s.** Includes the previously failing audit-read
completeness assertion plus approval, activation and wrong-writer negative controls. The latter
use deliberately constructed fixture approvals; no real approval block was changed.

Retained packet: `~/cadi-evidence/cadi01-local-20261009/`. JUnit `targeted-final.xml` SHA256:
`c196ced418620ffacbffc92317ddfb64fbccbb634dfbd5a1801a93e9d86fce8e`.
Earlier JUnit reports and the acceptance final tail are retained separately; the tail is **not**
a full transcript. Test-generated adversarial exports were moved there, not deleted.

| Tested source | SHA256 |
|---|---|
| `canonical_decision.py` | `0d36528f2c0f2a7453a1a8d72237545c4ccafbab6f3c76bbf56d4fb447c04ea8` |
| `decision_store.py` | `b6ced065cb7f78ca4643da9994b8d11b46464e57ef647f3a25f30b1f35df946a` |
| `cio_operator_artifacts.py` | `981aa420edc8a782f77050ded9f142ced5264cb46d510f2a585bc91d22492cc7` |
| `test_cadi01_canonical_v2.py` | `53720f37d081ac35d768d758a919ef4b084711176df97bb1cdc6ae585a2c8127` |

Measured hygiene: Ruff check (new and touched Python) and format check (new files) PASS;
secret scan staged/tree PASS; dark-contract NEW=0; coverage NEW-unlisted=0; host-path NEW=0;
line-ending churn none; source-of-truth render/check clean; SOP evidence digest validation PASS.
INDEX is regenerated after staging and checked at checkpoint. Markdown added-line whitespace
is corrected without changing historical findings.

Authority check still **exit 1**, exactly two `UNAPPROVED_SOURCE` findings, one writer each:
`cross_asset_evaluation_history` and `cross_asset_decision_projection`. Full acceptance on the
final source tree is **NOT RUN / BLOCKED pending actual approvals**; its prior exit 1 is not
relabeled green just because the focused regression is fixed. After approval, rerun the normal
full acceptance, commit any real approval provenance, request an exact-SHA git-push grant,
push through the normal hook once and submit CADI-01 only for Agent A review. No self-merge.

### Final reviewed local candidate — 2026-10-09 11:17 EDT

The same six-suite command with `--junitxml=/tmp/cadi01-evidence-ASaxWf/targeted-reviewed.xml`
completed **121 PASS / 0 FAIL / exit 0 / 551.41s** after the malformed-history/authority repairs.
The final batch-output raw-symbol safeguard and two additional cases were then covered by:

```bash
"$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python" -m pytest -q \
  tests/test_cadi01_canonical_v2.py --junitxml=/tmp/cadi01-evidence-ASaxWf/core-final.xml
"$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python" -m pytest -q \
  tests/test_cio_phase11_adversarial.py --junitxml=/tmp/cadi01-evidence-ASaxWf/adversarial-reviewed.xml
```

Results: **80 core PASS / 16.03s / exit 0** and **15 adversarial PASS / 12.54s / exit 0**.
Core overlaps the six-suite run; do not add 80 to 121 as independent cases. There are 123 unique
scoped cases across those two runs, plus the separately listed adversarial cases. These are
fixture tests, not organic outcomes or priced investment signals. The normal full acceptance
must still rerun after actual source approval; it is not reported green.

| Finding | Root cause | Repair and proof |
|---|---|---|
| CADI01-READ-001 | Three registered advisory schemas had no operator audit-read edge | Existing audit reader reads the single store directly; completeness assertion and record-edge checks pass; no copy/writer added |
| CADI01-READ-002 | Valid JSON could have invalid payload shape and disrupt legacy listings | Shared error/decision/projection validation, protected envelope construction; four parameterized corruption cases preserve legacy output |
| CADI01-READ-003 | Authority JSON top-level/domain types were unchecked | Protected structural validation, typed approval fields; four malformed-authority cases report AUTHORITY_UNAVAILABLE before production access |
| CADI01-BATCH-001 | Malformed legacy actions/raw symbols could be normalized or leave non-JSON wrapper fields | Raw action retained; six falsy cases refuse; two raw-symbol cases produce JSON-safe error receipts while good rows continue |
| CADI01-AUTH-001 | Two new authoritative stores lack John's named approval | Still BLOCKED, exactly two source findings; never fabricate approval, bypass the gate or activate the reads/writer |

Both independent reviewers cleared their identified code defects. No undefined finding was
converted into a success label. SOURCE_APPROVAL_REQUIRED/NOT_ACTIVATED/STORE_READ_FAILED/
IDENTITY_CONFLICT remain explicit reader states; raw signal time is never labeled append time.

Final tested source hashes (supersede the pre-final table):

| Source | SHA256 |
|---|---|
| `canonical_decision.py` | `8d0b08ef52ff43a50c523b10daa5715887e97578fecc4c277b35e09747ac7b39` |
| `decision_store.py` | `e761271ceacfe7c7b4d328da8206e784b669cdaa236986614e465eecfbdd2070` |
| `cio_operator_artifacts.py` | `59b4402728fa8cfd840f35da403bbc816cff422f8f0cbe0763ce896e6d12bce6` |
| `test_cadi01_canonical_v2.py` | `01f9ddd10d355a45fcea5d260100896a6c9347f553d5955c7ab16939ad96a34c` |

Retained `core-final.xml` SHA256: `bd7c75d1965c283001d4b956d1bbdf8daa08008396ba313afc0d04cd39f95319`.
Retained `adversarial-reviewed.xml` SHA256: `22a1716c8802288e4c95116635a8aecd2a769be60b01f56ccd1a490deec801dc`.
The six-suite reviewed JUnit is retained in the same local packet. No Drive/email delivery is
claimed; local Git checkpoint/head and board entry provide the implementation commit trail.

---

## Historical test plan and evidence — 2026-09-29 (preserved)

Status: ACTIVE
as_of: 2026-09-29  
Authority: Implementation Plan + Backlog CADI-*  

## Unit Tests

| ID | Case | Pass |
|---|---|---|
| U1 | `new_symbol_decision` has all field groups | keys present |
| U2 | `validate_symbol_decision` rejects missing identity.symbol | raises/returns ok=False |
| U3 | persist + load_latest roundtrip | equal symbol |
| U4 | assemble NFLX fixture sets research_state from Hermes result | result_id linked |
| U5 | Buy signal routes shares+long_call+CSP+debit_spread | four families |
| U6 | Hold routes covered_call+protective_put; collar unavailable | honest status |
| U7 | Reentry routes shares+CSP+spread | three families |
| U8 | Sell routes sell_shares+protective_put; collar unavailable | honest |
| U9 | Shadow flag off → event hook no ledger write | no file growth |
| U10 | Missed opportunity when chosen≠top | ledger row |

## Integration Tests

| ID | Case | Pass |
|---|---|---|
| I1 | Shadow cycle dry-run over 2 symbols returns ranked objects | ok |
| I2 | Assemble with empty stores still validates | incomplete but valid |

## Scheduler Tests

| ID | Case | Pass |
|---|---|---|
| S1 | CLI exit 0 dry-run | documented; timer not installed until Phase 8 READY |

## Persistence Tests

| ID | Case | Pass |
|---|---|---|
| P1 | Append never truncates prior rows | line count +1 |
| P2 | Corrupt line skipped on load_latest | no raise |

## CIO / Research / Options / Re-entry / Watchlist

| ID | Case | Pass |
|---|---|---|
| C1 | cio_state passthrough on assemble | equals fixture |
| R1 | hermes result_id / research_id on research_state | linked |
| O1 | options_state embeds packet schema name when provided | OptionsDecisionPacket@v2 |
| E1 | reentry signal_kind drives CSP candidates | present |
| W1 | watch provenance → identity.subject_guid when present | linked |

## Historical Replay

| ID | Case | Pass |
|---|---|---|
| H1 | 30d with no archive → metrics `data_quality=INSUFFICIENT_DATA` | honest |
| H2 | 60d/90d same honesty path until archives wired | honest |

## Regression

| ID | Case | Pass |
|---|---|---|
| G1 | Existing options_strategy_matrix tests unaffected | green |
| G2 | No broker import in cross_asset package | grep gate |

## Evidence log

| Date | Suite | Result | Commit |
|---|---|---|---|
| 2026-09-29 | unit CADI (8 tests) | **8 passed** | bc9b38c1d |
| 2026-09-29 | shadow dry-run NFLX buy | ok=true top=shares ranked=4 | CLI |
| 2026-09-29 | historical 30/60/90 | INSUFFICIENT_DATA (honest) | `/tmp/cadi_hist_metrics.json` |
| 2026-09-29 | broker import grep on cross_asset | clean | — |
