# A4 Wave 2b — UNKNOWN retirement reasons

**Status:** ACTIVE  
**as_of:** 2026-08-31T13:26:22Z  
**Measured at:** `77433ef548da4c2bbdaa9eb3b0fb1d064eede9f5` (`origin/main` tip at branch cut) / worktree `/home/johnclaw/tradeai-wt-a4-unknown-retirements`  
**Authority:** READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · MBI_COGNITION=1  
**Writer:** sole owner of `config/lane_registry.json` for this wave  
**Rails:** never invent a reason; honest UNKNOWN is a finding; do not touch crontab/systemd enablement

---

## Summary

| Metric | Before | After |
|---|---:|---:|
| `reason_confidence=UNKNOWN` (non-ACTIVE) | **6** | **3** |
| Resolved from evidence this wave | — | **3** (all ESTABLISHED) |
| Remain UNKNOWN after re-investigation | — | **3** |
| `MAX_UNKNOWN_LANES` ratchet | 6 | **3** |
| `undeclared_baseline` shrink | — | **not applied** (Agent 2a still running; no solid promotions consumed) |

Agent 2a (`A4_2A_UNDECLARED_CENSUS`) was still in progress when this pass wrote; baseline shrink deferred per wave instructions.

---

## Method

For each of the six UNKNOWN lanes left by PR #722:

1. Re-read the seeded `reason_evidence` / `state_reason`.
2. Search git log / blame / PR bodies, `docs/ops/lane_retirement_annotations.proposed.txt`, live `crontab -l` comments, CHANGELOG, phase closeouts, and systemd journal/enablement.
3. Upgrade `reason_confidence` **only** when evidence meets the ESTABLISHED or CORRELATED bar from `scripts/lib/lane_registry.py` (quote the evidence in both this doc and the registry fields).
4. When the dig finds nothing new that clears the bar, keep UNKNOWN and extend `reason_evidence` with what was searched so the next reader does not repeat the dig.

Confidence bars (canonical):

- **ESTABLISHED** — cause proven from evidence quoted in `reason_evidence`.
- **CORRELATED** — strong evidence; causation NOT proven; must say "do not treat as covered" / "not verified" / equivalent.
- **UNKNOWN** — genuinely not established. An honest entry, and itself a finding.

---

## Resolved → ESTABLISHED (3)

### 1. `tradeai-operator-readiness` (was NEVER_SCHEDULED/UNKNOWN → RETIRED/ESTABLISHED)

**Prior claim (#722):** "No successor unit found by name, and no commit or document records an intent to retire it."

**That claim is false.** PHASE201 documents the retirement explicitly; #722 missed those docs.

**Evidence quoted:**

- `docs/architecture/PHASE201C_GOVERNANCE_TIMER_RETIREMENT_DECISION_GATE.md`:
  > ALL CONDITIONS PASS → APPROVED to retire the 4 redundant PHASE41 governance timers (201D): `tradeai-governance-facts.timer`, `tradeai-governance-status.timer`, `tradeai-maturity-board.timer`, `tradeai-operator-readiness.timer`.
- `docs/architecture/PHASE201D_PHASE41_GOVERNANCE_TIMER_RETIREMENT_REPORT.md` — stop+disable recorded; rollback = `systemctl --user enable --now tradeai-operator-readiness.timer`.
- `docs/project/PHASE201_GOVERNANCE_TIMER_RETIREMENT_PORTFOLIO_PREFLIGHT_CLOSEOUT.md`: "PHASE41 governance timers retired | **4**".
- `docs/operations/SCHEDULED_JOBS_REFERENCE.md`: the four standalone timers "were **consolidated into the single active `tradeai-governance-pipeline` controller**".
- `scripts/pipelines/run_governance_pipeline.sh` `gov_step "operator_readiness"` invokes `scripts/report_operator_readiness_summary.py` writing `docs/maturity_hardening/operator_readiness_latest.{json,md}`.
- `journalctl --user -u tradeai-governance-pipeline.service` 2026-08-31 07:40: `operator_readiness status=ok`.

**Registry updates:** `state=RETIRED`, `state_since=2026-06-05`, `superseded_by=tradeai-governance-pipeline.timer`, `reason_confidence=ESTABLISHED`.

Note: sibling governance-facts/status remain CORRELATED from #722 (under-graded relative to the same PHASE201 corpus). Out of scope for this wave's six-lane list; flagged for a later pass.

### 2. `tradeai-flash-portfolio-risk-hourly` (NEVER_SCHEDULED/UNKNOWN → ESTABLISHED)

**Prior claim (#722):** "Genuinely unexplained."

**Evidence quoted:**

- Commit `eed471bc4` (2026-08-03) `feat(llm): fleet Flash-first policy + cadence timers` ships `config/systemd/flash-cadence/`.
- `config/systemd/flash-cadence/README.md`:
  > Install timers (**optional — operator**)
  with example `enable --now` only for `tradeai-flash-watchlist-daily.timer`.
- Host unit birth: `~/.config/systemd/user/tradeai-flash-portfolio-risk-hourly.timer` Birth=2026-08-03 00:35:20.
- `systemctl --user is-enabled` = `disabled`; `journalctl --user -u tradeai-flash-portfolio-risk.service` = No entries.
- Sibling flash timers from the same commit (`flash-watchlist-daily`, `flash-llm-intelligence`) **were** enabled and ran until 2026-08-18 (now PAUSED/CORRELATED).

**Cause of NEVER_SCHEDULED:** enablement is operator-gated by the shipped README and was never performed. Same shape as `cio-residual-web` ESTABLISHED ("operator sequences it").

**Registry updates:** `state_since=2026-08-03`, `reason_confidence=ESTABLISHED`.

### 3. `tradeai-flash-portfolio-risk-weekend` (NEVER_SCHEDULED/UNKNOWN → ESTABLISHED)

Same shipment and README as the hourly twin. Weekend OnCalendar `Sat,Sun *-*-* 10:00:00` → same service unit. Never enabled, never fired. ESTABLISHED for the same optional-install reason.

---

## Remain UNKNOWN after re-investigation (3)

An honest UNKNOWN that was genuinely re-investigated is the finding.

### 4. `deep-overnight-llm` — UNKNOWN (unchanged confidence)

- PHASE102 closeout commit `1a843fc3` (2026-06-01) + `docs/project/PHASE102_OLD_OVERNIGHT_RETIREMENT_CLOSEOUT.md` reason: **"Global queue covers all jobs"** — supersession claim never verified.
- Sibling false-retirement precedent: 2026-06-11 `continuous_runner covers 04:00-11:00` found FALSE and reverted (`docs/CHANGELOG.md` ~3432).
- `PHASE58_OLD_OVERNIGHT_MONOPOLY_RETIREMENT_CLOSEOUT.md` is **DESIGN ONLY — not applied**.
- Last completed job 2026-05-23 — **nine days before** the 2026-06-01 retirement — so the retirement may not even explain the silence.
- No later PR establishes a verified successor for this lane's `deep_overnight_llm_results` outputs.

**Not upgraded.** Unverified supersession claims are exactly why `reason_confidence` exists (PR #722 narrative).

### 5. `overnight-batch` — UNKNOWN (unchanged confidence)

- Crontab carries only `PHASE102-RETIRED` — no reason text on the line.
- Same unverified "Global queue covers all jobs" closeout as above.
- **Partial reversal without registry knowledge** (still true, reconfirmed live):
  - `# RESTORED 2026-07-04 weekly (tax_agent staleness max 7d; sweep was retired as collateral of overnight_batch Phase 102 retirement)` then active `35 6 * * 1 … overnight_batch.py --tax-sweep`
  - active `40 5 * * * … overnight_batch.py --outcomes`
- `docs/MASTER_SYSTEM_DOCUMENTATION.md` documents agent-performance scorer **rehomed** to `update_agent_performance.py` — that is WHERE a piece went, not WHY the monopoly path was retired.
- Coverage of the `--telegram` overnight path by the global queue remains unverified.

**Not upgraded.**

### 6. `cio-decision-engine` — UNKNOWN (unchanged confidence)

- Live crontab: `#0 7 * * 1-5 $PY scripts/cio_decision_engine.py --run  # DISABLED 2026-08-08`.
- No authoring commit/PR found for the disable (`git log -S 'DISABLED 2026-08-08'`; Aug 7–9 window empty of an authoring change). Last `logs/cio_decisions.log` mtime **2026-08-07 07:00**.
- `docs/cio/CIO_NOTIFICATION_RUNTIME_TOPOLOGY.md` claims alex + cio_decision_engine were "moved to `agent-runtime@*.timer` shadow-live" — **DOC-CLAIM not transferred**: only the alex cron line records `agent_runtime@alex` supersession; this line carries none.
- `docs/cio/ARCHITECTURE.md` + `docs/audits/CIO_PLATFORM_REMEDIATION_2026-08-27.md` Fix C1 still treat the disable reason as unknown; operator chose option **(b)** document mechanical independence (PR #526) rather than re-enable.

**Not upgraded.** Same-day-as-alex is calendar coincidence, not transferable supersession (already recorded by #722).

---

## What was searched (shared)

| Source | Result |
|---|---|
| `git log` / `git show 1a843fc3`, `eed471bc4`, PR #722 | PHASE102 thin closeout; flash-cadence optional install; prior UNKNOWN list |
| `docs/ops/lane_retirement_annotations.proposed.txt` | deep_overnight / cio_decision still `reason=UNKNOWN` |
| Live `crontab -l` | PHASE102-RETIRED tags; RESTORED tax-sweep; DISABLED 2026-08-08 cio line |
| `docs/CHANGELOG.md` ~3432 | continuous_runner false-retirement reverted |
| PHASE201{C,D} + PHASE201 closeout + SCHEDULED_JOBS_REFERENCE | **operator-readiness retirement ESTABLISHED** |
| `systemctl --user` / `journalctl --user` | operator-readiness disabled/no journal; governance-pipeline runs operator_readiness ok; flash-portfolio-risk never fired |
| `docs/cio/*` + CIO remediation C1 | cio-decision-engine why still open |
| Agent 2a overnight doc | **not present yet** — baseline shrink skipped |

---

## Validation

```
cd /home/johnclaw/tradeai-wt-a4-unknown-retirements
pytest tests/test_lane_registry.py -q
```

(Results quoted in the PR body after the run.)

---

## Operator notes (no action taken)

- Applying `docs/ops/lane_retirement_annotations.proposed.txt` still edits live crontab → operator-only.
- Re-enabling `cio_decision_engine.py` cron remains blocked on establishing why it was disabled (C1).
- Optional flash portfolio-risk timers remain disabled; enabling is operator-only.
- Governance-facts/status CORRELATED→ESTABLISHED via the same PHASE201 corpus is a natural follow-up, not done here.
