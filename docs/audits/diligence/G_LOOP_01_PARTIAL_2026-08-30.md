# G-LOOP-01 — Partial: operator-gated DLQ ledger (dry-run)

**Date:** 2026-08-30  
**Authority:** READ_ONLY_ADVISORY  
**MBI_BEHAVIOR:** 0  
**Gap:** G-LOOP-01 (lineage `complete_to_checkpoint` ≪ program KPI)  
**Status:** **PARTIAL / residual OPEN**  
**Rails:** never_auto_remediate `store_consistency` · no silent identity merge · no 99.99% claim  

---

## 1. What this package delivers

Implements P9 design phases **C (dead-letter enqueue)** and **D (replay dry-run / operator-gated apply receipt)** as an operator CLI — not a silent remediator.

| Artifact | Path |
|----------|------|
| DLQ ledger helpers | `scripts/lib/cio_dlq_ledger.py` (`CIOLifecycleDLQ@v1`) |
| Operator CLI | `scripts/cio_lifecycle_dlq.py` (`CIOLifecycleDLQRun@v1`) |
| Tests (tmp fixtures) | `tests/test_cio_gap_loop_01.py` |
| Census input (P9) | `scripts/cio_registry_orphan_census.py` |
| Design reference | `docs/audits/diligence/P9_REGISTRY_ORPHAN_LIFECYCLE_2026-08-30.md` |

Ledger path (default): `<state_root>/data/cio/lifecycle_dlq.jsonl` (APPEND_ONLY_EVIDENCE).

---

## 2. Operator usage

```bash
# Inspect findings from orphan/missing_cross_id census (default 30d)
python scripts/cio_lifecycle_dlq.py --census-days 30

# Append enqueue rows to the DLQ ledger (does not touch lineage hubs)
python scripts/cio_lifecycle_dlq.py --census-days 30 --write-ledger

# Print planned replay actions (dry-run; optional ledger annotate with --write-ledger)
python scripts/cio_lifecycle_dlq.py --census-days 30 --replay-dry-run
python scripts/cio_lifecycle_dlq.py --census-days 30 --write-ledger --replay-dry-run

# Apply path: REFUSED unless TRADEAI_DLQ_APPLY=1
# Even when armed, only appends an apply-receipt — never rewrites historical stores
python scripts/cio_lifecycle_dlq.py --apply                    # exit 2, APPLY_REFUSED
TRADEAI_DLQ_APPLY=1 python scripts/cio_lifecycle_dlq.py --apply --json
```

Reason codes (from P9 §6.3): `MISSING_EVENT_ID`, `NULL_WORKFLOW_ID`, `UNKNOWN_NOTIFICATION_ID`, `UNKNOWN_WORKFLOW_ID`, `UNKNOWN_CHECKPOINT_ID`, …

---

## 3. Explicit non-claims

- Does **not** claim lifecycle completion of **99.99%** (or any ramp milestone).
- Does **not** merge identity arcs (research/checkpoint vs CIO/notification).
- Does **not** rewrite `cio_workflow_lineage.jsonl` or other hub/satellite stores.
- Does **not** auto-remediate store consistency.
- Does **not** edit the gap register (PR-G / register updates are a separate package).

P9 measured baseline remains the authoritative gauge until a later measured window shows rise: lineage `complete_to_checkpoint` was **406/752 (54.0%)** at P9 pin; orphan census 30d missing_cross_id / orphan_hits as reported in the P9 diligence note.

---

## 4. Residual OPEN (why still PARTIAL)

G-LOOP-01 stays **OPEN** until:

1. **Measured** completion rate rises on a defined production window (instrumentation + identity authority — P9 phases A–B / P1-WS2).  
2. DLQ drain is operator-authorized with evidence (receipts + re-census), not dry-run alone.  
3. Program ramp toward the KPI is evidenced — this package only adds the **ledger + dry-run gate**, not the completion claim.

Success for *this* package: enqueue + dry-run + env-gated apply-receipt work under rails; hubs unchanged.

---

## 5. Evidence standard

1. Doc: this file + P9 lifecycle path §6.3 C–D  
2. Code: `cio_lifecycle_dlq.py` / `cio_dlq_ledger.py`  
3. Tests: `tests/test_cio_gap_loop_01.py` (tmp fixtures; apply refused without env; hubs byte-stable under apply)

---

## 6. Out of scope / forbidden

- Promoting exact-main / notify-on / broker writes  
- Silent delete or rewrite of store rows  
- Claiming 99.99% achieved  
- Editing `docs/audits/CIO_DILIGENCE_GAP_REGISTER.md` in this PR  
- Raising MBI_BEHAVIOR above 0  
