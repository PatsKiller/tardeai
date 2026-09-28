# 05 · Platform Intelligence Governance Layer — every silo behaves identically

```
Status:      PROPOSED
as_of:       2026-09-27T18:00:00-04:00
Measured at: 8f2a178d5 (origin/main) / served 8f2a178d5-main-exact-phase2-20260927-171004.
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Nothing here is built.
Package:     cognitive_transformation_20260927 — read 00 first.
Answers:     operator brief §5 (silo governance: compliance scoring, conformance audits, automatic
             remediation, architecture-drift detection).
```

## 1. The problem stated precisely

"Some silos consume intelligence and others do not" `[DOC-CLAIM: 09-27 §3]` is a governance finding,
not an engineering one: nothing measures whether a silo follows the platform's standards, so a silo can
regress after it is fixed and nobody is told. The platform already has the *shape* of governance for
individual concerns — the lane registry with a shrink-only undeclared baseline `[CODE]`, the
`DataSourceAuthority@v2` approval row per writer `[CODE]`, chokepoint linters with ratcheting baselines
`[CODE: gateway-enforcement.md]`, the generated docs index with a drift check `[CODE]`, the maturity
catalog. What it lacks is one score that composes them **per silo** and one consequence when the score
falls.

## 2. Silos (the governed units)

A silo is a bounded set of lanes with its own stores and entry points. From the 09-27 service map and
the agent audit `[DOC-CLAIM]`, twelve:

CIO wake/decision · Hermes CIO research · Hermes external lanes · watchlist agents · holdings advisory ·
options desk · re-entry desk · analyst/research intelligence · portfolio review · risk/agent runtime
(Wave-3) · health/watchdog · desk bot (Telegram). Each silo maps to lane-registry rows (owner field
exists today `[CODE: lane_registry.json lanes[].owner]`).

## 3. Five standards, one contract — `PlatformConformance@v1`

| Standard | What "conforms" means | Measured from | Weight |
|---|---|---|---|
| **Identity** | every row/record the silo writes carries a registry GUID or `UNRESOLVABLE`; no ticker-string joins; no new key namespace | identity backfill coverage (`identity_status`), façade refusals (01), schema check of the silo's tables | 0.20 |
| **Memory** | read-before-act / write-after-act / deltas / freshness / contradiction touched (01 §6) | `MemoryCompliance@v1` | 0.30 |
| **Research** | no generation without a retrieval receipt; all writes through `accept_*`; DGR under threshold (03 §7) | retrieval receipts, LLM consumption log, delta writes | 0.20 |
| **Worker** | lease with owner/boot-id/TTL; `safe_flock`; heartbeat; lane row with `output_signal`; standard status vocabulary; idempotency key (09-27 §5 contract) | supervisor heartbeat table (06), lane registry, `check_cron_sanity`/unit linters | 0.15 |
| **Monitoring** | every lane has an SLA row, an output signal, and no silent-failure path (exit 0 with no artifact) | 06 SLA table, `report_alert_sla_status`, health agent | 0.15 |

```yaml
PlatformConformance@v1:
  silo_id, as_of, release_sha
  standards: {identity: 0..1, memory: 0..1, research: 0..1, worker: 0..1, monitoring: 0..1}
  score: weighted sum
  state: CONFORMANT (≥0.95) | DEGRADED (0.80–0.95) | NON_CONFORMANT (<0.80) | UNMEASURED
  findings: [{standard, measure, value, threshold, evidence_cmd, evidence_output_ref}]
  drift: [DriftFinding@v1]          # §5
  remediation: [{finding_ref, class: A|B|C, action, state}]
```

Each standard's sub-measures are queries whose commands are quoted in the report (AGENTS.md §4/§14).
`UNMEASURED` is a legal state and its count is the first thing the report prints.

## 4. Conformance audit — how and when

- **Lane** `platform-conformance-audit`, nightly (operator lane approval, 11), runs from the served
  release, writes `data/governance/platform_conformance_latest.json` and a dated copy under
  `docs/governance/` (the `governance_status_latest.*` pattern exists `[CODE]`).
- **Inputs:** 01 §6 compliance report, 03 receipts, 06 heartbeat/SLA tables, `check_lane_registry.py`,
  `check_data_source_authority.py`, chokepoint linters, `report_docs_inventory.py --check-index`,
  `check_unit_env_files.py` / `check_cron_sanity.py` (P1 linters, 09-26 `[DOC-CLAIM]`).
- **Surface:** one Command Center governance panel with the twelve silos, their scores, trend and open
  findings; one Telegram digest line per day (P1_DIGEST class, inside the 30/day budget `[CODE]`).
- **Independence:** producer ≠ reviewer ≠ scorer (the 09-21 plan's gate-honesty rule `[DOC-CLAIM]`):
  the audit lane never edits what it measures, and its own lane is scored by the health agent, not by itself.

## 5. Architecture drift detection — `DriftFinding@v1`

Drift is a difference between what the registries say and what the host or code does. Detectors,
all read-only, all existing or thin wrappers:

| Detector | Compares | Exists today `[CODE]` |
|---|---|---|
| Schedule drift | `lane_registry.json` ↔ `crontab -l` + `systemctl --user list-timers` (incl. user-scope timers invisible to system listing `[DOC-CLAIM: memory 09-19]`) | `check_lane_registry.py --fail-on-new`, `discover_cron/discover_systemd` |
| Writer drift | `data_source_authority.json` ↔ observed writers of authoritative stores | `check_data_source_authority.py` (UNAPPROVED_SOURCE) |
| Chokepoint drift | linter baselines ↔ code | `check_provider_chokepoint`, `check_telegram_chokepoint`, + memory chokepoint (01 Ring 1) |
| Contract drift | hash of the five standard interfaces (`MemoryContext@v1`, `RetrievalReceipt@v1`, `IntelligenceEnvelope@v1`, worker contract, SLA row) ↔ the served release | new: `contract_manifest.json` with content hashes, checked at prepare time (`PRE_DEPLOY_STATE_GUARD.md` pattern) |
| Registry drift | three agent registries ↔ one (09-27 Wave 4) | `AGENT_SERVICE_MAP` registry-vs-host section |
| Docs drift | generated index ↔ tree; docs with runtime claims and no `Measured at` | `report_docs_inventory.py --check-index` |
| Release drift | served pin ↔ expected ↔ units bound to CURRENT (`TRADEAI_CURRENT_BOUND_UNITS`) | `release_grant_binding`, worker-pin check |
| Unit drift | `config/systemd/**` (117) ↔ `~/.config/systemd/user/` (259) | `check_unit_env_files.py`; the 118 host-only units are a known baseline `[DOC-CLAIM: 09-26 audit]` |

A drift finding names the registry that wins (ARCHITECTURE_INDEX precedence: DSA writer > lane owner >
catalog agent `[CODE]`) and never resolves it automatically when two candidate truths could destroy one
(AGENTS.md §0 rule 5).

## 6. Automatic remediation — three classes, by reversibility

| Class | Rule | Examples | Who acts |
|---|---|---|---|
| **A · additive, reversible, self-applied** | the fix adds a row/receipt/heartbeat or restarts what the sudoers allowlist already permits; nothing is overwritten | create a missing heartbeat row; re-queue a stranded lease; regenerate the docs index; mark a doc header `Measured at: not measured`; restart a unit in the allowlist (06 L1) | supervisory layer (06), same cycle |
| **B · proposal** | the fix edits code, config or a registry | declare a lane; add an `output_signal`; add a façade adapter; retire a duplicate cron; amend AGENTS.md | agent opens a PR + approval-package item (13); no host change |
| **C · operator-only** | AGENTS.md §17 or a divergent-truth case | new cron/timer; new writer; merging copies; deleting; MBI mode change; spend | operator via the approval package |

The audit tags every finding with its class; class A actions are logged as episodes (04) with a
`RemediationReceipt@v1`, and a class-A action that recurs more than N times in a week is escalated to
class B ("fix the cause, not the symptom" — the recurring-restart pattern from the 09-18 timer churn
`[DOC-CLAIM: AGENTS.md 1.2.3]`).

## 7. Consequences — what a low score does

- **Promotion gate.** `release_grant_preflight` `[CODE]` additionally reads the conformance report: a
  silo in `NON_CONFORMANT` cannot have its lanes promoted to the served release until the finding is
  addressed or the operator overrides in the approval package (recorded). Wave 5 (09) turns this on;
  before that the gate warns.
- **Mode gate.** A silo's memory-influence mode (08) cannot advance unless `memory ≥ 0.95` and
  `research ≥ 0.95`.
- **Budget gate.** A silo with `research < 0.8` (generating without retrieval) has its paid lane
  deferred to off-peak by `llm_deferral` policy until it conforms — cost follows conformance.
- **Visibility.** The daily digest names the lowest-scoring silo and its owner. Findings never
  disappear; they are closed by evidence.

## 8. Governance debt ledger

The first audit's `UNMEASURED` and `NON_CONFORMANT` counts are the governance debt baseline. Like the
lane registry's `undeclared_baseline` it may only shrink, and the trend is a Command Center number. The
09-27 report's operator-only list (DSN rotation, MBI flip, no-op timers, iris timer, `local_llm_compat`
`[DOC-CLAIM: §13]`) seeds the ledger.
