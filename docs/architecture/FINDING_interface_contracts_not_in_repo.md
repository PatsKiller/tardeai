# Finding — `INTERFACE_CONTRACTS.md` is cited everywhere and version-controlled nowhere

Status:      ACTIVE
as_of:       2026-09-10
Filed under: AGENTS.md §20 — a contradicting finding opens an amendment in the same wave
Found by:    narrative-identity work (Phase 6)

## The finding

`INTERFACE_CONTRACTS.md` is referenced by production code, by tests, and by
operator-facing documents as though it were part of this repository:

| Citation | Location |
|---|---|
| "INTERFACE_CONTRACTS.md §6: `effect_kind='none'` is legal and is NOT evidence of consumption" | `scripts/lib/wake_subject_selector.py:92` |
| contract reference | `scripts/lib/campaign_interfaces.py:9,57,70` |
| contract reference | `scripts/lib/campaign_interfaces_b.py:5`, `_c.py:5`, `persistent_wake_interfaces.py:5` |
| test assertions | `tests/test_wake_subject_selector.py:96`, `tests/test_wake_consumption_loop_closure.py:10` |
| §5 / §6 cited as authority | `docs/architecture/maturity_gap_closure_20260910/CIO_AS_IS_2026-09-10-0215.md` |

**It does not exist in the repository.** `git log --all -- '**/INTERFACE_CONTRACTS.md'`
is empty. The file lives only at
`/home/johnclaw/trade-ai-campaigns/m2-canary-20260907/control/INTERFACE_CONTRACTS.md`,
with a differing copy under `.../evidence/lane-b/` and two more in `/tmp`.

## Why it matters

A contract that governs runtime behaviour, is quoted in code comments as the
reason for a rule, and is asserted against in tests, has no version history, no
review path, and at least two divergent copies. Nothing detects if they drift.
The campaign header even declares it "FROZEN at baseline `f1c87242…`" — a freeze
that no gate can verify.

This is the same class of defect as the ones this wave has been closing: work
that exists and is real, but lives somewhere the system cannot see. The rich
CIO documents had the same shape — cited, emailed, and untracked — until
2026-09-10.

## Also found

`docs/architecture/agent-contracts.md` documented `AgentConsumptionReceipt@v1` as
current while `campaign_interfaces.py` declares `@v2`. A `Status: SUPERSEDED`
header was added to that page in the same wave.

## Proposal — operator decision, not taken here

1. Move `INTERFACE_CONTRACTS.md` into `docs/` and make the campaign copy a
   pointer, or
2. Vendor it under `docs/convergence/` alongside `CONTROL_PLANE_CONTRACTS.md`,
   which is the existing integrator-owned home for frozen contracts.

Either way, add a gate asserting the in-repo copy matches the baseline the header
claims. Until then, every citation above is a citation to an unversioned file.

Not executed: moving a frozen, integration-owner-only contract is an ownership
decision (§17), not an engineering one.
