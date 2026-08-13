# Phase 4 — Advisory Desk Analyst Committee & `InvestmentDecision@v1`

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

Run:

```bash
python3 -m pytest tests/test_cio_checkpoint4_committee.py tests/test_cio_checkpoint4_synthesis.py -q
```

## 6. Known gaps (honest, not hidden)

- **Specialist-artifact resolution into the committee is the remaining live
  integration.** `CIORunWorker._route_specialists` hardcodes `artifacts: []`;
  the committee engine, `synthesize_decision`, and the `synthesis_fn` factory are
  fully wired and tested, but the worker must be extended to read completed
  `SpecialistAdvisory` artifacts (from the handoff queue / run store
  `specialist_artifact_refs`) into `specialist_result["artifacts"]` before
  synthesis. The tests inject artifacts via a thin wrapper to prove the
  worker→committee→decision→action path is correct end-to-end.
- The specialist *LLM* production of `SpecialistAdvisory` artifacts (opinion
  engine + governed model bridge) is not yet routed through the committee; the
  `vote_from_specialist_advisory` bridge is ready for it.
- `final_position` enum is chair-level; mapping from the legacy synthesis
  `recommendation` vocabulary (`ADD/ADD_ON_PULLBACK/REBALANCE_TRIM/…`) to the
  canonical enum is a follow-up normalization, not done here.
