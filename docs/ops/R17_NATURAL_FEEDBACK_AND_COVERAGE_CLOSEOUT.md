# R17 — Natural feedback closure and coverage convergence

**Authority:** `READ_ONLY_ADVISORY` · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Branch:** `feat/r17-natural-feedback-closure` (local only; not pushed)  
**Base:** `origin/main` `2d988c76`  
**Starting live maturity:** 88  
**Awarded:** **88** (89 not earned)

---

## Mission

Do not build another brain, memory store, or event bus. Close the missing
connections on the existing loop:

site sources → intelligence delta → graph impact → persistent cognition →
research gap → free-first → governed curation → thesis → CIO/specialists →
decision → **outcome checkpoint** → outcome → learning.

## What closed

1. **Natural decision → checkpoint (code).** `scan_office(..., persist=True)` now
   calls `bind_scan_decisions`. Checkpoints carry `subject_guid`, generation,
   horizon, `due_at`, runtime SHA, and a context receipt.
2. **Semantic dedupe.** Replay `decision_id` churn does not spam. Key is
   subject + recommendation + material generation + thesis/curation version +
   horizon. A genuine material-state change still creates a new checkpoint.
3. **Due processor.** `scripts/process_due_checkpoints.py` plus systemd unit
   **files** (not enabled). Not-due → `NO_ACTION`. Missing source →
   `OUTCOME_PENDING_DATA`. Does not fabricate elapsed time or trade.
4. **Cockpit.** `get_learning_cockpit_v1` reads durable jsonl counts
   (pending/due/completed/blocked). Not in-memory theater.
5. **Coverage v2.** `SUPPORTED | MISSING | NOT_APPLICABLE`. Portfolio/macro
   producers no longer fail IDENTITY. Unexplained MISSING = 0 after N/A and
   explicit closures. Not optimized for a FULL label.
6. **Bounded sector/industry wake.** Exposed/held/watch only. Shared industry
   text does not wake the universe.
7. **Catalyst/GUI/news/SEC/RAG/specialist envelope extras.** Evidence, not
   truth. Specialist disagreement preserved. No execution on stop/risk.

## What did not happen (on purpose)

- No git push. No CI. No PR.
- No CURRENT deploy. Auto-register is **not** live on pin `2d988c76`.
- Due timer **not** installed. Do not start it and call that natural.
- No Telegram canary, no cash_target invention, no PR #505, no production SQL.
- No model/process registry writes. Promotion ceiling remains `REVIEW_READY`.
- No fabricated market event. Event-driven research remains
  `BLOCKED_REAL_WORLD_EVENT`.
- **89 not awarded.** 90 remains longitudinally gated.

## 89 criteria

| # | Criterion | Status |
|---|---|---|
| 1 | New natural material decisions auto-register checkpoints | CODE_READY_NOT_ON_CURRENT |
| 2 | Unchanged replay does not spam | UNIT_PASS |
| 3 | Checkpoint state survives restart | UNIT_PASS |
| 4 | Due processor is live | **false** (unit exists, not enabled) |
| 5 | Cockpit reads durable stores | **true** |
| 6 | One genuinely elapsed observation end-to-end | **false** |
| 7 | No safety authority changes | **true** |

## Identity (CURRENT, honest)

Universe membership and identity were re-read, not hard-coded. Unresolved
security identities remain unresolved. Ticker text never mints `security_guid`.

## Remote policy

`LOCAL_R17_READY_FOR_SYNC=true`

One authorized push and one GitHub CI cycle remain operator-gated.
After that deploy, observe natural scan → bind → due processor without
manually starting a service and labeling it natural.
