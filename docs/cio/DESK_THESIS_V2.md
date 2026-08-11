# Desk thesis desk@v2 — living CIO governing context

**Authority:** READ_ONLY_ADVISORY  
**Store:** `scripts/lib/cio_theses.py` · `data/cio/cio_theses.jsonl`  
**Learning:** `data/cio/cio_operator_learning.jsonl` + thesis head `learning_log`

## Purpose

`desk@vN` is the **governing context** for every material CIO plan and Telegram
reply — not a footer badge. Enrichment loads the full current desk text before
the model writes recommendations.

## desk@v2 structure

| Field | Role |
|---|---|
| `summary` | Living desk statement |
| `stance` | Short label (e.g. `defensive_observe`) |
| `principles` | Non-negotiable operating principles |
| `risk_posture` | How risk is taken / deferred |
| `escalation_rules` | When to surface to the operator |
| `bullets` | Short operator-facing reminders |
| `learning_log` | Seed + recent disposition learnings on head |
| `linked_symbols` | Names under active desk attention |

## Migration

- `desk@v1` remains readable via pin (historical plans).
- `desk@v2` published from v1 content + expanded structure (see publish script /
  ops log). Current pin becomes `desk@v2`.

## Enrichment contract

1. Load full current desk thesis (`context_block(full=True)`).
2. Multi-domain evidence: holdings_detail + cash/portfolio (+ risk when available).
3. Material situations (S1 deep DD, S5 cash, S6 concentration, S8) → longer form:
   thesis_alignment, multi_domain_summary, complete options, recommendation citing pin.
4. Routine → short card still cites `thesis_version`.
5. Operator dispositions (ack/defer/done/reject) → learning log for future enrich.

## Operator check

```bash
PYTHONPATH=scripts python3 -c "from scripts.lib.cio_theses import safe_current_pin, safe_context_block; print(safe_current_pin()); print(safe_context_block(full=True)['stance'])"
# expect desk@v2 · defensive_observe
```
