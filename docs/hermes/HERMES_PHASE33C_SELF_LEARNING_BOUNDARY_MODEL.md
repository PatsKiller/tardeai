# Hermes Phase 33C — Self-Learning Boundary Model

**Date:** 2026-06-01
**Status:** AUTHORITATIVE — governance document

---

## What Self-Learning Means

Hermes self-learning is the system's ability to detect gaps in its own knowledge, generate research tasks, discover sources, curate findings, and improve advisory quality — all without executing trades or mutating production execution state.

---

## Allowed Self-Learning Activities

| Activity | Status | Phase |
|----------|--------|-------|
| Detecting stale/weak/missing evidence | OPERATIONAL | Phase 21, 30 |
| Generating research backlog tasks | OPERATIONAL | Phase 22, 32 |
| Discovering sources through SearXNG | OPERATIONAL (manual) | Phase 17–19 |
| Staging curated research candidates | OPERATIONAL | Phase 19, 32 |
| Scoring source quality | OPERATIONAL | Phase 18, 25 |
| Recommending embedding candidates | OPERATIONAL (dry-run) | Phase 25 |
| Recommending promotion candidates | OPERATIONAL (dry-run) | Phase 13 |
| Updating advisory metadata after approval | OPERATIONAL | Phase 15 |

## NOT Allowed Without Future Explicit Approval

| Activity | Current Status | Required Gate |
|----------|---------------|--------------|
| Broker execution | PROHIBITED | Phase 40+ (if ever) |
| Proposal creation/mutation | PROHIBITED | Phase 40+ |
| Journal mutation | PROHIBITED | Phase 40+ |
| Auto-rebalance | PROHIBITED | Phase 40+ |
| Auto-promotion | PROHIBITED | Phase 39+ |
| Broad embeddings (>2 per batch) | NOT APPROVED | Phase 31+ |
| Unrestricted web research | NOT APPROVED | Phase 37+ |
| Public SearXNG exposure | NOT APPROVED | Phase 40+ |
| Hidden cron jobs | PROHIBITED | Never |
| Model-routing changes | PROHIBITED | Operator-only |

---

## Maturity Levels

| Level | Name | Description | Hermes Status |
|-------|------|-------------|---------------|
| 0 | Manual Only | All scripts run by operator | PASSED |
| 1 | Read-Only Observation | Automated observation, no writes | PASSED |
| 2 | Dry-Run Research | Automated analysis, file output only | PASSED |
| 3 | Capped Staged Writes | ≤10 rows per batch, operator-approved | **CURRENT** |
| 4 | Capped Embeddings/Promotions | ≤2 per pilot, operator approval | DESIGNED (Phase 25) |
| 5 | Autonomous Staged Research | Daily staged writes, operator review | DESIGNED (Phase 33E) |
| 6 | Production Advisory | Advisory cache auto-refresh | NOT DESIGNED |
| 7 | Trading/Proposal Automation | PROHIBITED until separate governance | NOT APPROVED |

**Current Hermes Maturity Level: 3 — Capped Staged Writes**

---

## Self-Learning Loop

```
Observe (safe views) → Analyze (Librarian) → Identify Gaps → Create Backlog
    → Discover Sources (SearXNG) → Curate (Librarian) → Stage (operator approval)
    → Embed (operator approval) → Promote (operator approval)
    → Improve RAG → Better Advisory → Repeat
```

Each step requires either:
1. Existing automation with caps and kill switch (Levels 1–3)
2. Explicit phase approval for new automation (Levels 4–6)
3. Separate governance review (Level 7)
