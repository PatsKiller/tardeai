# P1 Phase B — Proposal Lifecycle Report — 2026-05-29

## Changes Applied

### 1. ATM Expiry Primary Status — FIXED
- **File**: `scripts/atm_auto_approver.py` lines 302-306
- **Change**: ATM expiry now sets `status='EXPIRED'`, `lifecycle_status='EXPIRED'`, and `lifecycle_message` in addition to `atm_expired_at` and `atm_expiry_reason`
- **Safety guard**: `WHERE status NOT IN ('APPROVED_FOR_PAPER_TEST', 'BROKER_SUBMITTED')` prevents expiring approved/submitted proposals
- **Rows backfilled**: 0 — all 4 existing ATM-expired proposals already had correct status
- **Impact**: Prevents future status drift between ATM expiry state and primary status

### 2. Proposal Lifecycle Inspector — ADDED (API only)
- **Endpoint**: `GET /api/v2/paper-proposals/lifecycle-inspector?proposal_id=<id>`
- **File**: `scripts/api_v2.py`
- **Features**:
  - Aggregates proposal + enrichment satellites + linked trades + lifecycle events
  - Computes actionability, next action, and safety flags
  - Normalizes status uppercase
  - Returns enrichment satellite counts
  - Returns up to 10 recent lifecycle events
- **UI**: Not added this session — API-only. Next step: "Inspect" button on PaperProposals.tsx

## Files Changed
| File | Change |
|------|--------|
| `scripts/atm_auto_approver.py` | ATM expiry now updates primary status |
| `scripts/api_v2.py` | Added lifecycle inspector endpoint |

## Validation
| Check | Result |
|-------|--------|
| Python compile (api_v2.py) | PASS |
| Python compile (atm_auto_approver.py) | PASS |
| Inspector: expired proposal | PASS |
| Inspector: approved/traded proposal | PASS |
| Inspector: rejected proposal | PASS |
| Hygiene panel counts | PASS (65 expired, 2 linked, 0 needs_review) |

## Rows Mutated
**0** — code-only changes. No DB backfill needed.

## Remaining P1 Gaps
1. ~~ATM expiry primary status~~ — DONE
2. ~~Proposal lifecycle inspector~~ — DONE (API), UI pending
3. Lifecycle inspector UI panel on PaperProposals.tsx — P2

## Safety Confirmation
| Check | Result |
|-------|--------|
| Orders placed | NO |
| Broker writes | NO |
| paper_trades trade-state changes | NO |
| Proposal mutations | NO (0 rows, code fix only) |
| Journal mutations | NO |
| Classifier apply | NO |
| LLM calls | NO |
| Qwen/Gemma4/Grok used | NO |
| Cron changes | NO |
| Health-agent files changed | NO |
| retry_cmd files changed | NO |
