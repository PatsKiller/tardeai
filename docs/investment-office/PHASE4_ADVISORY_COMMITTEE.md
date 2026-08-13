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

## 5. Checkpoint 4 canaries

`tests/test_cio_checkpoint4_committee.py` — 26 hermetic tests (0 provider calls,
0 live side effects) covering quorum, unanimity, super-majority, MIXED, defense
veto, neutral consensus, deterministic `decision_id`, evidence gate, disagreement
resolution, fact-dump rejection, action-payload idempotency, pipeline
deduplication, a real `CIOActionLedger` roundtrip (temp path), and the
`SpecialistAdvisory` → `CommitteeVote` bridge.

Run:

```bash
python3 -m pytest tests/test_cio_checkpoint4_committee.py -q
```

## 6. Known gaps (honest, not hidden)

- The committee is wired as a **deterministic engine**; the specialist *LLM*
  production of `SpecialistAdvisory` artifacts into real `CommitteeVote`s is the
  next integration step (ties the opinion engine + governed model bridge to the
  committee). The bridge function (`vote_from_specialist_advisory`) is ready for it.
- `final_position` enum is chair-level; mapping from the legacy synthesis
  `recommendation` vocabulary (`ADD/ADD_ON_PULLBACK/REBALANCE_TRIM/…`) to the
  canonical enum is a follow-up normalization, not done here.
