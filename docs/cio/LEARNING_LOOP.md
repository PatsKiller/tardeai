# Learning loop — dispositions → enrichment bias

**Code:**

- [`scripts/lib/cio_theses.py`](../../scripts/lib/cio_theses.py) — `append_learning`, `record_operator_learning`, `recent_operator_learning`  
- Disposition handlers via Telegram / converse (`scripts/lib/cio_telegram_converse.py`, `scripts/lib/cio_converse_core.py`)  
- Enrichment consumption in [`scripts/lib/cio_plan_enrichment.py`](../../scripts/lib/cio_plan_enrichment.py)  
- Desk note section 6 in [`scripts/lib/cio_desk_synthesis.py`](../../scripts/lib/cio_desk_synthesis.py)

**Authority:** every learning row carries `authority: READ_ONLY_ADVISORY`.

---

## Flow (live)

```
Operator: ack | rate | defer | done | reject  (+ optional note)
    → durable append: data/cio/cio_operator_learning.jsonl
    → optional THESIS_LEARNING_APPENDED on desk head (learning_log)
    → future enrich_plan / desk note reads recent dispositions
    → recommendations biased toward honoring operator intent
       e.g. SCHD concentration defer "wait for price buffer"
            → hold_with_thesis, do not re-spam trim
```

### Disposition meanings

| Disposition | Effect on learning |
|---|---|
| **ack** | Monitor; weak positive signal for “no change needed now” |
| **rate** | Quality signal for advisory (when captured) |
| **defer** | Strong postpone bias; note text is high value for enrichment |
| **done** | Operator considers item closed |
| **reject** | Negative on that recommendation path |

Telegram: `/cio defer plan_…` or reply keywords on plan threads.

---

## Storage shape (illustrative, no secrets)

```json
{
  "authority": "READ_ONLY_ADVISORY",
  "kind": "plan_disposition",
  "disposition": "defer",
  "note": "wait for price buffer",
  "plan_id": "plan_…",
  "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
  "symbols": ["SCHD"],
  "thesis_version": "desk@v2",
  "ts": "2026-08-11T21:33:52+00:00"
}
```

Thesis head `learning_log` may carry a truncated recent list for prompt context; the JSONL is the durable cross-version source.

---

## Where bias is applied

| Surface | Behavior |
|---|---|
| Plan enrichment | Evidence pack may include recent learning; thesis-fit text should honor open defers |
| Desk note §6 | Lists dispositions that bias the memo |
| Notify | Fingerprint ledger reduces spam; learning reduces *content* pressure to re-push rejected/deferred paths |

Learning does **not** auto-change detector thresholds or place orders.

---

## Current limitations (honest)

| Limitation | Reality |
|---|---|
| Volume | Few dispositions logged on typical hosts (seed + single SCHD defer class) |
| Closed-loop quality | No full auto-eval of whether enrichment “got better” after defer |
| Pin hygiene | Disposition may record older pin than current head; still valid history |
| Dedup | Duplicate JSONL lines possible historically; desk note dedupes for display |
| Rate/done/reject richness | Schema supports; operational use is still thin |
| Cross-agent memory | Not a general Mem0/LangGraph long-term memory product |

Continuous learning depth is a **gap**, not a shipped FA moat. See [ROADMAP_GAPS.md](./ROADMAP_GAPS.md).

---

## Related

- [THESIS.md](./THESIS.md)  
- [DESK_NOTE.md](./DESK_NOTE.md)  
- [AUTHORITY.md](./AUTHORITY.md)  
