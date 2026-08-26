# Bounded canary dry-run — SCHG / CSCO / ANET

Date: 2026-08-20  
Authority: `READ_ONLY_ADVISORY`  
Script: `scripts/publish_symbol_thesis_canary.py`  
Artifact: `evidence/SYMBOL_THESIS_CANARY_DRY_RUN_2026-08-20.json`

## Command

```bash
python scripts/publish_symbol_thesis_canary.py --symbols SCHG CSCO ANET
```

## Result

| Symbol | thesis_state | has_summary | applied | skip_reason |
|--------|--------------|-------------|---------|-------------|
| SCHG | RESEARCH_REQUIRED | false | false | `no_existing_summary_will_not_invent` |
| CSCO | RESEARCH_REQUIRED | false | false | `no_existing_summary_will_not_invent` |
| ANET | RESEARCH_REQUIRED | false | false | `no_existing_summary_will_not_invent` |

## Apply decision

**No apply.** All three canaries reported `no_existing_summary_will_not_invent`.
Per P1.8: do not invent thesis text; leave dry-run report only.
`CANARY_THESIS_APPLY=1` was **not** set and `--apply` was **not** run.

## Notes

- Mode: `dry`
- `auto_thesis_on_wake`: false
- financial_action: false
