# Phase P3 — Versioned thesis store

**Authority:** READ_ONLY_ADVISORY  
**Branch:** `feature/advisory-desk-v1`  
**Code:** `scripts/lib/cio_theses.py`  
**Log:** `data/cio/cio_theses.jsonl`  
**Projection:** `data/cio/cio_theses_projection.json`

## What it is

A **versioned desk living thesis** (and optional theme theses) that plans, wakes, and enrichment can **pin**.

| Concept | Where |
|---|---|
| Per-goal thesis snippets | `CIOGoalStore.thesis_summary` / `thesis_history` (WS1) |
| **Versioned desk thesis** | **This store** — `desk@vN` pins |

Not a free-running brain. Not broker. Operators (or agents under advisory authority) **publish** versions; history is append-only.

## Schema (head / version record)

| Field | Meaning |
|---|---|
| `thesis_id` | `desk` (default) or e.g. `theme_defense` |
| `version` | Monotonic int per thesis_id |
| `thesis_version` | Canonical pin `desk@v3` |
| `summary` | Main living statement |
| `stance` | Optional short label |
| `bullets` | Optional short bullets |
| `linked_symbols` / `linked_goal_ids` / `linked_plan_ids` | Soft links |
| `evidence_refs` | Optional structured refs |
| `owner_agent` | e.g. alex |
| `status` | `active` \| `superseded` \| `archived` |
| `parent_version` | Prior version number |
| `change_note` | Why this version |
| `authority` | Always `READ_ONLY_ADVISORY` |

## API

```python
from scripts.lib.cio_theses import CIOThesisStore
s = CIOThesisStore()
s.publish(
    "Risk-aware observe-only; escalate material drift to operator.",
    owner_agent="alex",
    stance="defensive",
    bullets=["No new risk without operator"],
    linked_symbols=[],
    change_note="initial desk thesis",
)
s.get_current("desk")           # head
s.get_by_pin("desk@v1")         # historical pin
s.list_versions("desk")
s.link("desk", plan_ids=["plan_…"])
s.archive("desk", reason="…")
s.context_block("desk")         # pack for agent/enrich
```

## Wiring

| Path | Behavior |
|---|---|
| Plan create | Auto-sets `thesis_version` to current desk pin if present |
| Plan enrich | Evidence pack includes `desk_thesis` (+ pin) |
| Goal agent context | `desk_thesis` block beside goal `thesis_snippets` |
| Goal wake context | `thesis_version` on wake context when desk thesis exists |
| Wake traces (P5) | `thesis_version` field when plan/context has pin |
| `/cio thesis` | Current desk thesis (zero LLM) |
| `/cio thesis history` | Version list |

## Operator commands

```bash
# Publish desk thesis
.venv/bin/python - <<'PY'
from scripts.lib.cio_theses import CIOThesisStore
print(CIOThesisStore().publish(
    "Risk-aware observe-only; escalate material drift.",
    owner_agent="alex",
    stance="defensive",
    change_note="p3 bootstrap",
    actor_id="operator",
)["thesis_version"])
PY

.venv/bin/python scripts/cio_commands.py thesis
.venv/bin/python scripts/cio_commands.py thesis history
# Telegram: /cio thesis · /cio thesis history
```

## Tests

```bash
.venv/bin/python -m pytest tests/test_cio_theses_p3.py -q
```

## Non-goals

Mem0, LangGraph, auto-rewrite of thesis by free agents, broker path, mass Telegram notify.
