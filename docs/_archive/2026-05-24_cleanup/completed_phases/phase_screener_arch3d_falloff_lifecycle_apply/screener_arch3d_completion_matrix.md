# SCREENER-ARCH-3D — Completion Matrix

| Deliverable | Status | Evidence | Deferred Phase |
|---|---|---|---|
| Baseline report | done | 1,129 active, 976 source-missing | |
| Falloff apply policy | done | 8 lifecycle states defined | |
| Dry-run falloff apply | done | 993 safe + 136 expire candidates | |
| Operator approval gate | done | Documented with commands | |
| Safe apply source_missing | done | 885 marked | |
| Safe apply retained_by_ttl | done | (via source_missing) | |
| Safe apply needs_refresh | done | 89 marked | |
| Safe apply active | done | 153 marked | |
| Expire apply | blocked | 136 candidates, --operator-approved-expire not set | Operator decision |
| Archive apply | not requested | --operator-approved-archive | Operator decision |
| Post-apply validation | done | All 1,129 still ACTIVE | |
| API/dashboard validation | done | Endpoints reflect updated state | |
| Cron wrapper verification | done | 3 jobs verified by actual cron | |
| Tests | done | 21/21 + 23/23 regression | |
| Safety | done | Full audit passed | |

## Test Results

21/21 ARCH-3D + 23/23 ARCH-3C regression.
