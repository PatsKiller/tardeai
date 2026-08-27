# P0 Build and UI Validation — 2026-05-29

## Python Compile Check
```
.venv/bin/python -m py_compile scripts/api_v2.py
COMPILE OK
```

## API Validation (live server on :7777)

### Hygiene Summary Response
| Metric | Value |
|--------|-------|
| total_count | 141 |
| expired_count | **65** (was ~62 before fix) |
| rejected_count | (via classification: 74) |
| linked_open_trade_count | 2 |
| duplicate_count | 0 |
| blocked_count | 0 |
| stale_count | 0 |
| needs_review_count | 0 |
| recent_count | 0 |

### Classification Breakdown
| Classification | Count |
|----------------|-------|
| rejected | 74 |
| expired | 65 |
| linked_to_open_trade | 2 |

Total: 141 (74 + 65 + 2 = 141)

### Previously-Miscategorized Rows (verified fixed)
| ID | Symbol | status | classification | signal_decision |
|----|--------|--------|---------------|-----------------|
| 10 | BLBD | EXPIRED | expired | GO |
| 97 | TLSI | EXPIRED | expired | GO |
| 124 | EVER | EXPIRED | expired | (empty) |

### Response Format
- `status` field now shows uppercase-normalized proposal status (was signal_decision)
- `signal_decision` field added as separate context field
- `reason` field now shows `"Status: REJECTED"` or `"Status: RISK_BLOCKED"` for clarity

## Frontend
- No frontend code changes required
- ProposalHygienePanel.tsx uses `Record<string, any>` — handles new fields automatically
- No build needed

## Payload Saved
`logs/p0_proposal_fixes/proposal_hygiene_validation.json` (50,963 bytes)
