Status:      ACTIVE  
as_of:       2026-09-01T16:00:00-04:00  
Measured at: origin/main tip at branch open (contains #831 / `9428294ee`)  
Canonical repo path: docs/ops/CIO_WAKE_PERSIST_APPEND_2026-09-01.md  
Authority:   ops record for the wake_research_persist hits retain fix  
See also:    docs/ops/litmus/LITMUS_WAKE_2026-09-01.md  
             docs/ops/CIO_M5_FIRST_FIRE_2026-09-01.md  
             docs/maturity/CIO_INVESTMENT_PRODUCT.md (untouched)

# Wake research persist — retain research hits

## Verdict

**M5 stays `M5_CANDIDATE`.** This change only stops the durable artifact from
erasing the cycle that closed the loop. It does not claim days-earlier honor,
does not hand-run the entrypoint, and does not promote CURRENT.

## Problem (from LITMUS_WAKE / FIRST_FIRE)

`scripts/cio_wake_dispatch_entrypoint.py` wrote
`data/cio/wake_research_persist.json` with `_p.write_text(...)` every `*/5`.
The 13:35 cycle (`research_called>0`, `persisted>0` for `EXIT:WLDS`) was gone
from the JSON by 15:19. The log still had it. An artifact that keeps only the
latest idle cycle cannot prove M5.

## Change

| piece | what |
|---|---|
| `scripts/lib/wake_research_persist.py` | `WakeResearchPersist@v1` with `current` + `hits` (cap 20); legacy load → `current=that, hits=[]`; atomic tmp+rename via `atomic_write_json` |
| `scripts/cio_wake_dispatch_entrypoint.py` | live path calls `write_cycle` instead of bare `write_text` for this file |
| `tests/test_wake_research_persist_hits.py` | idle / hit / cap / legacy / mutation (bare write_text → red); comments stripped before overwrite scan |
| hardening allowlist | gate `wake_research_persist_hits` |

### Document shape

```json
{
  "schema": "WakeResearchPersist@v1",
  "current": { "...existing last-cycle object...": true },
  "hits": [
    {
      "as_of": "...",
      "dispatched": 4,
      "research_called": 3,
      "persisted": 1,
      "subjects": ["EXIT:WLDS"],
      "decisions": ["flash"],
      "unattended": true
    }
  ]
}
```

A cycle is retained as a hit when `research_called>0` **or** `persisted>0`
**or** a research decision is not skip/`cadence_not_due`-only. Idle
`no_subject` cycles update `current` only.

## Explicit non-goals

- `decide_after_load` / `next_eligible_at` math — untouched  
- `BehaviorWriteRefused` — untouched  
- No Telegram, no `outcome --apply`, no holdings, no `.env`  
- No `$PROJ` fast-forward, no lane cadence edits  
- No cash_letter / CASH_SLEEVE / total_cash  
- No S3 / S5 mint  
- No `migration:deterministic` stamp on this artifact (it has no writer field);
  the instrument-record stamp defect from FIRST_FIRE is **not** fixed here  
- **Promote: NO** unless the operator says `promote persist`

## Proof (local, not production entrypoint)

Copy the live JSON to `/tmp`, run `write_cycle` once idle and once with a
synthetic hit, show `hits` survived. Cron / CURRENT pin unchanged until
promote.

## Follow-up

Follow-up to #831 (LITMUS_WAKE pack — measurements, not code). One PR.
)
