# Desk thesis — `desk@vN`

**Code:** [`scripts/lib/cio_theses.py`](../../scripts/lib/cio_theses.py)  
**Authority:** `READ_ONLY_ADVISORY` on every stored record  
**Canonical pin form:** `{thesis_id}@v{version}` — default thesis id `desk` → e.g. `desk@v4`

The desk thesis is the **governing investment context** for advisory output. It is not a decorative footer: enrichment and desk notes are required to reason against stance, principles, risk posture, and escalation rules, and to echo the **exact pin** used for that advice.

---

## Event store + projection

| Artifact | Role |
|---|---|
| `data/cio/cio_theses.jsonl` | Append-only events (immutable history) |
| `data/cio/cio_theses_projection.json` | Rebuildable snapshot of current + all versions |
| `data/cio/cio_operator_learning.jsonl` | Cross-version operator dispositions (append-only) |

### Event types

- `THESIS_CREATED` — first publish for a thesis_id  
- `THESIS_VERSION_PUBLISHED` — pin advances (`desk@vN` → `desk@vN+1`)  
- `THESIS_STATUS_CHANGED` — active / superseded / archived  
- `THESIS_LINKED` — symbol/goal/plan links  
- `THESIS_LEARNING_APPENDED` — learning entry on head + durable learning JSONL  

`CIOThesisStore.publish(...)` creates a new version (monotonic integer). Prior head is retained in the versions map; status of older versions is `superseded` when a new head is published.

Distinct from per-goal `thesis_summary` snippets in the goal store.

---

## Pins and fail-soft accessors

```python
from scripts.lib.cio_theses import safe_current_pin, safe_context_block

pin = safe_current_pin("desk")          # e.g. "desk@v4" or None
block = safe_context_block("desk", full=True)  # dict or None
```

| Helper | Behavior |
|---|---|
| `make_pin` / `parse_pin` | Strict `id@vN` format |
| `CIOThesisStore.current_pin` | Head pin for thesis_id |
| `safe_current_pin` | Never raises; returns `None` on failure |
| `safe_context_block(..., full=)` | Compact or full governing block for prompts / plans |

Callers that must not crash (Telegram, enrichment, detector) use the `safe_*` helpers only.

---

## Document structure (desk@v2+ intelligence OS)

Published payload fields (illustrative structure — not host secrets):

```yaml
thesis_id: desk
version: 4
thesis_version: desk@v4          # pin
status: active
owner_agent: alex
authority: READ_ONLY_ADVISORY
stance: defensive_observe        # e.g. defensive_observe | balanced | opportunistic
summary: |                       # 2–4 sentence governing paragraph
  Risk-aware observe-only desk under a living thesis. ...
bullets:                         # short operating bullets
  - No broker/order/stop authority from chat or situations
  - Pin every plan to the exact desk@vN pin used for the advice
  - ...
principles:                      # governing principles (v2+)
  - Evidence before narrative — numbers only from Data Broker domains
  - Thesis is governing context, not a footer tag
  - Cash buffer is intentional optionality until data quality supports deploy
  - ...
risk_posture:                    # human-readable + structured thresholds
  "max_single_name=12.0% cash_band_min=20.0% ..."
risk_posture_structured:         # when present on head (via publish extra / migration)
  max_single_name_weight_pct: 12.0
  cash_band_min_pct: 20.0
  deep_dd_threshold_pct: 25.0
  concentration_fire_pct: 16.5
  notes: "Defensive observe: preserve optionality; ..."
escalation_rules:
  - "S1 deep DD ≥25% from basis → full material note + Hermes research_gap"
  - "S5 cash_pct above band (min 20%) → staged deployment options only; never force fills"
  - "S6 single-name weight ≥12% (fire ~16.5%) → Morgan-style size & thesis review"
  - "S8 defensive regime → material; Hermes high priority"
  - ...
learning_log:                    # head-carried recent entries (also durable JSONL)
  - kind: seed
    note: "Migrated from desk@v1 ..."
  - kind: plan_disposition
    disposition: defer
    symbols: [SCHD]
    note: "wait for price buffer"
    plan_id: plan_...
    thesis_version: desk@v2
linked_symbols: [SCHD, SPCX]
watch_symbols: [SCHD, SPCX]
parent_version: 3
change_note: "desk@v4 operator publish — refresh last_reviewed; ..."
published_ts / last_reviewed / updated_ts: ISO-8601
```

Thresholds should align with [`config/cio_situations.yaml`](../../config/cio_situations.yaml) unless the operator deliberately diverges stance/posture.

---

## Example: current pin shape (no secrets)

Live hosts commonly show something like:

| Field | Example (non-secret) |
|---|---|
| Pin | `desk@v4` |
| Stance | `defensive_observe` |
| Owner | `alex` |
| Cash band min | 20% |
| Max single-name | 12% |
| Deep DD | 25% from basis |
| Concentration fire | ≈16.5% book weight |
| Linked symbols | SCHD, SPCX |

Exact summary text and learning entries live on the host projection (`cio_theses_projection.json`). Architects should treat **pin + structure** as the contract; host numbers are snapshots, not constants in git.

---

## Who loads the thesis

| Consumer | How |
|---|---|
| Plan enrichment | `build_evidence_pack` → `safe_context_block(..., full=True)` + `safe_current_pin`; stamps `plan.thesis_version` |
| Situation detector (post-create) | Calls enrich under live pin |
| Telegram replies | `active_thesis_version()` / formatters show pin |
| Desk note v1.1 | Collects pin + full context for sections 1, 5, 6 |
| Goal context (Track B) | Goals may attach `safe_context_block("desk")` into wake/run context |
| Wake dispatcher | May copy `desk_thesis` / `thesis_version` into run context when present |

See [ARCHITECTURE.md](./ARCHITECTURE.md) for injection vs non-injection paths.

---

## Operator publish discipline

1. Publish a new version when **governing** content changes (stance, principles, thresholds, escalation), not for every market tick.  
2. Bump `last_reviewed` when the operator re-affirms the same structure (may advance pin for hygiene).  
3. Refresh external packets (Drive operating packet, this docs tree maturity note) with **pin + as_of** when pin advances.  
4. Never put tokens, broker credentials, or chat IDs in thesis body.

---

## Related

- [DESK_THESIS_V2.md](./DESK_THESIS_V2.md) — narrative for the v2 intelligence cut  
- [THESIS_STORE_P3.md](./THESIS_STORE_P3.md) — store delivery notes  
- [LEARNING_LOOP.md](./LEARNING_LOOP.md) — how dispositions append to learning  
