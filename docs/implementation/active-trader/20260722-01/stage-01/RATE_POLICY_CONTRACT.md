# Rate Policy Contract — Stage 1 (BF-2 resolution, owner-approved)

**Run ID:** 20260722-01 · Implementation: `RateBudget` / `RatePolicy`
(`scripts/active_trader/contracts.py`). Moomoo itself is NOT installed; this stage ships
configuration + validation contracts only. The runtime governor arrives with Stage 5 and
must use a token bucket **plus an exact sliding-window check**.

## Approved per-account budgets (30-second window)
| Action class | Provider ceiling | Ordinary budget | Protection/exit reserve |
|---|---:|---:|---:|
| PLACE | 15 | 12 | 3 |
| MODIFY_CANCEL | 20 | 16 | 4 |

## Enforced validation rules (all tested, fail-closed)
- PLACE and MODIFY_CANCEL are **separate budgets**; any shared/other action class is rejected.
- `ordinary + reserve > ceiling` rejected (each class independently).
- Non-positive window rejected; missing account scope rejected; negative values rejected.
- Both budgets of one policy must scope the same account.
- Ordinary traffic can NEVER consume the reserve (`consume(..., is_protection=False)`
  refuses at the ordinary budget boundary).
- The provider ceiling is absolute: refused **even for protection/emergency** traffic
  (`consume(..., is_protection=True)` refuses at ceiling).
- `RatePolicy.approved_moomoo(account_scope)` is the single constructor for the approved
  values, so drift from the ruling is impossible without a code change.
