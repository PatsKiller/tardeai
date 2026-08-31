# Phase 4 — Advisory Desk Analyst Committee & `InvestmentDecision@v1`

Status:      HISTORICAL
as_of:       2026-08-13T16:45:18-04:00
Measured at: efcc51365 / not measured

> Converged investment office. Alex (CIO) is the chair and sole producer of the
> final investment recommendation; the committee provides inputs/constraints.
> Everything remains `READ_ONLY_ADVISORY` — no broker/order/stop/2FA authority.

## 1. What Phase 4 adds

Phase 4 formalizes two things that were previously implicit or scattered:

1. **A deterministic Advisory Committee** — Morgan (CWO), Steph, Maria, Guardian
   (risk), and Ledger (tax) cast structured votes; Alex chairs and reconciles.
2. **The canonical `InvestmentDecision@v1` contract** — the single, hash-pinned
   artifact every final recommendation becomes, consumed downstream by the action
   ledger, notification outbox, outcome store, and two-way curation.

## 2. Committee model (`scripts/lib/cio_committee.py`)

Pure, provider-call-free. Vote vocabulary is a 1:1 subset of the frozen
`SpecialistAdvisoryPosition` contract in `cio_advisory_schema.py`:

```
SUPPORT | OPPOSE | NEUTRAL | DEFER | INSUFFICIENT_EVIDENCE
```

`convene(votes, quorum=3)` computes, deterministically:

| Consensus | Meaning |
| --- | --- |
| `UNANIMOUS_SUPPORT` / `UNANIMOUS_OPPOSE` | all decision votes agree |
| `CONSENSUS_SUPPORT` / `CONSENSUS_OPPOSE` | ≥ 2/3 super-majority; dissent recorded |
| `CONSENSUS_NEUTRAL` | no actionable votes (all NEUTRAL/DEFER/INSUFFICIENT) |
| `MIXED` | SUPPORT and OPPOSE both present, no super-majority |
| `BLOCKED_QUORUM` | fewer than `quorum` members cast a decision vote |
| `BLOCKED_DEFENSE` | a blocking office (Guardian/`risk_agent`) cast OPPOSE |

### Fail-closed rules (proven by canaries)

1. `DEFER` / `INSUFFICIENT_EVIDENCE` do **not** count toward quorum — a committee
   that declines to opine cannot authorize action.
2. A **Guardian OPPOSE is a hard veto** (`BLOCKED_DEFENSE`), even under a
   SUPPORT super-majority. The defense desk cannot be out-voted.
3. A `MIXED` committee cannot be `READY_FOR_OPERATOR`.
4. Any `material_disagreement` marked `READY_FOR_OPERATOR` requires Alex's
   `how_disagreements_were_resolved` — no blind voting.

### Chair authority

Alex is **not** a voting member. He chairs: he reads the `CommitteeResult`,
reconciles dissent (documented), and issues the single final position. Only
`alex` carries `cio_synthesis` / `CIO_SYNTHESIS` (structurally enforced in
`scripts/agent_runtime/agents/definitions.py`).

## 3. `InvestmentDecision@v1` (`scripts/lib/cio_investment_decision.py`)

A dataclass pinning, for one recommendation:

- `schema_version` — `InvestmentDecision@v1`
- `parent_run_id` — the CIO run that produced it
- `final_position` — `BUY | SELL | SELL_TAXABLE | TRIM | HOLD | NO_ACTION | DEFER`
- `committee` — the `CommitteeResult`
- `evidence_refs` — a list of `EvidenceRef@v1` (Phase 2)
- `rationale_linked_to_evidence`, `conditions_to_change_view`, `material_risks`
- `actionability` — `READY_FOR_OPERATOR | NEEDS_MORE_EVIDENCE | CONFLICT_UNRESOLVED`
- `decision_id` — deterministic SHA-256 content hash

### Deterministic identity

`decision_id` is a SHA-256 over the **material** fields only. Bookkeeping fields
that vary across re-construction — `decision_id`, `created_at`, evidence
`ref_id`, evidence `observed_at` — are excluded. Provenance (`source`,
`source_record_id`, `source_timestamp`, `quality_state`, `value_hash`) is
retained, so the same logical decision hashes identically and provenance is
still pinned.

### Validation (`validate()` — fail-closed)

- Rejects fact-dump-only rationale.
- Requires quorum; rejects `BLOCKED_DEFENSE`.
- Rejects `MIXED` marked `READY_FOR_OPERATOR`.
- Rejects `READY_FOR_OPERATOR` with unresolved `material_disagreements`.
- **Evidence gate**: execution positions (`BUY/SELL/SELL_TAXABLE/TRIM`) must pass
  `gate_action` over `required_domains` (missing/blocking domain = hard block).
- Requires `conditions_to_change_view` for any non-defer position.

## 4. Pipeline (`scripts/lib/cio_decision_pipeline.py`)

`publish_decision(decision)` maps a decision to **exactly one** action and, when
`READY_FOR_OPERATOR`, **exactly one** operator notification. Both key off
`decision_id` (`idempotency_key = decision:<hash>`), so re-publishing is a no-op
(one verdict → one action → one notification, never duplicates). Non-ready
decisions are recorded as actions but produce no notification.

## 4b. Committee synthesis wiring (`scripts/lib/cio_committee_synthesis.py`)

The bridge that turns produced specialist advisories into a decision the live
`CIORunWorker` can consume:

```
[SpecialistAdvisory...] → vote_from_specialist_advisory → CommitteeVote...
  → convene → CommitteeResult → reconcile_committee → final position
  → build_decision → InvestmentDecision@v1 → recommendations_from_decision
  → recommendation rows consumed by CIORunWorker._write_actions
```

Key pieces:

- `reconcile_committee(intended_position, committee_result, ...)` — Alex is the
  chair; he proposes an `intended_position` and the committee gates it (see §2
  fail-closed rules). Returns `{final_position, actionability, resolution,
  overridden}`.
- `synthesize_decision(...)` — the full deterministic pipeline: advisories →
  committee → reconciled decision. Raises on a malformed advisory (fail-closed).
- `recommendations_from_decision(decision)` — maps a decision to the
  `recommendations` rows `CIORunWorker._write_actions` expects, with `action` +
  `action_type` so `determine_action_type` and `create_action` both resolve.
- `build_committee_synthesis_fn(...)` — returns a `synthesis_fn` callable
  drop-in for `CIORunWorker(synthesis_fn=...)`. It produces a decision and, when
  the decision is **valid**, the recommendation rows; when the decision is
  **invalid** (defense veto, quorum block, evidence gap, unresolved MIXED), it
  returns `recommendations: []` + `blocked: True` so the worker creates a STATUS
  action — never an execution action.

## 4c. Closing the specialist→committee resume loop (`scripts/lib/cio_specialist_artifacts.py`)

The previously-open gap — that a resumed run convened the committee from an
empty `artifacts: []` — is now closed end-to-end:

1. **Durable advisory persistence** — `AgentHandoffQueue.complete()` now persists
   the full `specialist_advisory` envelope (a `SpecialistAdvisory`-shaped dict) on
   `HANDOFF_COMPLETED`, and the projection surfaces it. Legacy completions that
   carry only `summary`/`evidence_refs` still convene as a `NEUTRAL` vote (never a
   fabricated position).
2. **Resolver** — `resolve_run_specialist_advisories(run, get_handoff)` folds the
   run's `parent_handoff_ids` + `specialist_requests` into `{advisories,
   completed_handoff_ids, pending_handoff_ids, covered_specialists}` by reading
   the authoritative handoff queue. `extract_advisory_from_handoff` reconstructs
   the committee input.
3. **Worker wiring** — `CIORunWorker._route_specialists` now consumes resolved
   advisories into `specialist_result["artifacts"]`, skips re-routing specialists
   already requested or completed, and only waits on genuinely-outstanding
   handoffs. `execute()` auto-resumes a run parked in `WAITING_FOR_SPECIALISTS` /
   `WAITING_FOR_HERMES` back to `EVIDENCE_BUILD` so a RESUME_RUN wake re-runs the
   cycle against fresh output.
4. **Wake linkage** — `CIOEventDetector._check_handoff_completions` now emits a
   `RESUME_RUN` wake targeting `handoff.parent_run_id` (falling back to a
   `NEW_RUN` `SPECIALIST_COMPLETION` run for orphaned handoffs), so a completed
   specialist re-opens *its own* parent run rather than spawning an unrelated one.

```
specialist completes handoff ──► HANDOFF_COMPLETED (with specialist_advisory)
   ──► RESUME_RUN wake (target = parent run)
   ──► CIORunWorker.execute() auto-resumes → EVIDENCE_BUILD
   ──► _route_specialists resolves advisories → specialist_result["artifacts"]
   ──► build_committee_synthesis_fn convenes committee from real output
   ──► InvestmentDecision@v1 → action / notification
```

## 5. Checkpoint 4 canaries

- `tests/test_cio_checkpoint4_committee.py` — 26 hermetic tests: quorum,
  unanimity, super-majority, MIXED, defense veto, neutral consensus, deterministic
  `decision_id`, evidence gate, disagreement resolution, fact-dump rejection,
  action-payload idempotency, pipeline deduplication, a real `CIOActionLedger`
  roundtrip (temp path), and the `SpecialistAdvisory` → `CommitteeVote` bridge.
- `tests/test_cio_checkpoint4_synthesis.py` — 17 hermetic tests: `reconcile_committee`
  rules, `synthesize_decision` (valid hold, defense-veto block, defer mapping),
  `recommendations_from_decision` shape, `build_committee_synthesis_fn` (valid
  decision, defense-veto no-recommendations, malformed-advisory fail-closed,
  evidence-refs-from-snapshot), and two end-to-end `CIORunWorker.execute()`
  runs — one producing a HOLD action, one proving a defense veto yields a STATUS
  action and **no** execution action.
- `tests/test_cio_checkpoint4_resume.py` — 12 hermetic tests for the §4c loop:
  advisory extraction (full + legacy fallback + non-completed), run resolution
  (mixed completed/pending/failed, parent-handoff inclusion, ghost handoffs),
  handoff-completion persistence, `_route_specialists` artifact consumption
  (covered vs uncovered), a full two-phase `execute()` resume that convenes the
  committee from **real** resolved output and emits a HOLD action, and the
  `HANDOFF_COMPLETED` → `RESUME_RUN` wake linkage (with orphan fallback).

Run:

```bash
python3 -m pytest tests/test_cio_checkpoint4_committee.py tests/test_cio_checkpoint4_synthesis.py tests/test_cio_checkpoint4_resume.py -q
```

## 6. Known gaps (honest, not hidden)

- **The resume loop is code-closed but agent-readiness-gated.** The resolver,
  auto-resume, and `RESUME_RUN` wake linkage are delivered and canaried; however
  the specialist *agents* (`maria`, `steph`, `guardian`, `ledger`) are still
  `DESIGNED`/`NOT_READY` in `config/agent_maturity_catalog.json`, so handoffs to
  them are `BLOCKED` (fail-closed) and no real `SpecialistAdvisory` can yet flow.
  Promoting those agents past `NOT_READY` (shadow canary → handoff-capable) is
  the gating prerequisite for live committee output, not a code defect.
- The specialist *LLM* production of `SpecialistAdvisory` artifacts (opinion
  engine + governed model bridge) is not yet routed through the committee; the
  `vote_from_specialist_advisory` bridge is ready for it.
- `final_position` enum is chair-level; mapping from the legacy synthesis
  `recommendation` vocabulary (`ADD/ADD_ON_PULLBACK/REBALANCE_TRIM/…`) to the
  canonical enum is a follow-up normalization, not done here.
