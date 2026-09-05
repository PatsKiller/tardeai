# Communications Gateway — Unit Results Packet

**Status:** Communications Gateway program documentation (Phases 0–11).
**Date:** 2026-09-05

**Purpose:** Record how to run the Phase 1–11 unit suite and capture CI output.  
**Production mode:** remains **OFF** (`COMMS_GATEWAY_MODE` unset / default).

---

## How to run

From repository root (this worktree):

```bash
pytest tests/test_comms_*.py tests/test_communications_portal.py -q
```

Explicit list (same set):

```bash
pytest \
  tests/test_comms_agent_contracts.py \
  tests/test_comms_communication_event.py \
  tests/test_comms_curation.py \
  tests/test_comms_delivery_ledger.py \
  tests/test_comms_enforcement_gate.py \
  tests/test_comms_librarian.py \
  tests/test_comms_shadow_compare.py \
  tests/test_comms_subject_memory.py \
  tests/test_communications_portal.py \
  -q
```

Optional: include chokepoint ratchet units when validating enforcement debt:

```bash
pytest tests/test_telegram_chokepoint_ratchet.py tests/test_provider_chokepoint_ratchet.py -q
```

---

## Expected invariants

- Default gateway mode is **OFF** when env is unset.  
- `PublishResult.delivery_owned` stays **False** under OFF/SHADOW.  
- No test may set production defaults to ACTIVE.  
- SHADOW compare helper records observations only; it does not send.

---

## Results log (paste CI / local output below)

| Date (UTC) | Runner | Command | Result | Notes |
|---|---|---|---|---|
| 2026-09-04 | local worktree | `python3 -m pytest tests/test_comms_shadow_compare.py -q` | 6 passed | Phase 11 helper |
| 2026-09-04 | local worktree | `python3 -m pytest tests/test_comms_*.py tests/test_communications_portal.py -q` | 81 passed | Full comms unit packet; mode default OFF |

### Paste block

```
......                                                                   [100%]
6 passed in 0.45s

........................................................................ [ 88%]
.........                                                                [100%]
81 passed in 3.25s
```

---

## Related

- Plan matrix: `docs/testing/test-plan.md`  
- Activation gates (unchecked): `docs/deployment/production-activation.md`