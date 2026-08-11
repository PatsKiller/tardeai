# Autonomy gap close — Goal + Thesis store (WS1–WS6)

**Date:** 2026-08-11  
**Branch:** `feature/advisory-desk-v1`  
**Authority:** READ_ONLY_ADVISORY forever  

Honest status: **goal-driven wake path is real on this host in SHADOW.**  
Not a free-running autonomous trader. Heartbeat remains the safety net.

---

## What was missing / what shipped

| WS | Item | Status |
|---|---|---|
| 0 | Host truth (branch, --once, backup) | [RUNTIME_TRUTH_2026-08-11.md](./RUNTIME_TRUTH_2026-08-11.md) |
| 1 | Goal + per-goal thesis snippets | `scripts/lib/cio_goals.py` → `data/cio/cio_goals.jsonl` |
| 2 | Dispatcher goal wakes | `CIOWakeDispatcher.enqueue_goal_wakes` inside `poll_and_dispatch` |
| 3 | Wake contract (context + thesis touch) | `CIORunWorker` goal step + agent_runtime goal jobs |
| 4 | /cio rate path | Existing `scripts/cio_commands.py rate` → action ledger (verified present) |
| 5 | Storage follow-ups | Maintenance script + notes (no auto VACUUM) |
| 6 | Acceptance | Commands below |

### Later same day — P3 versioned desk thesis (distinct)

WS1 per-goal `thesis_summary` is **not** the desk pin. **P3** adds `CIOThesisStore`
(`scripts/lib/cio_theses.py` → `data/cio/cio_theses.jsonl`) with canonical pins
`desk@vN`. Plans auto-pin; agent context includes `desk_thesis`.  
Operator: `/cio thesis` · docs: [THESIS_STORE_P3.md](../../cio/THESIS_STORE_P3.md).

---

## Goal store API

```python
from scripts.lib.cio_goals import CIOGoalStore
s = CIOGoalStore()
s.create_goal(owner_agent="alex", title="...", due_ts=..., linked_event_types=[...])
s.update_goal(goal_id, title="...")
s.update_thesis(goal_id, "evidence-grounded note", agent_id="alex")
s.close_goal(goal_id, status="achieved")
s.list_open_goals(owner_agent="alex")
s.get_context_for_agent("alex")  # open goals + thesis + recent events + open actions
s.list_due_or_idle_goals(owner_agent="steph")
```

Fields: `goal_id`, `owner_agent`, `title`, `description`, `status`, `priority`,  
`created_ts`, `updated_ts`, `due_ts`, `success_criteria`, `linked_event_types[]`,  
`linked_symbols[]`, `linked_action_ids[]`, `thesis_summary`, `last_wake_ts`,  
`wake_count`, `last_outcome`.

---

## Dispatcher behavior

On every `poll_and_dispatch()`:

1. **Existing** PENDING wake claim path unchanged (sole claimant for lifecycle).
2. **Also** `enqueue_goal_wakes()` for due / idle / never-woken goals (and optional linked event types).
3. Dedup: same `agent_id` + `goal_id` within **30 minutes** (`data/cio/cio_goal_wake_dedup.jsonl`).
4. NEW_RUN wakes with `trigger_type` `GOAL_DUE` | `GOAL_EVENT_LINKED`.
5. FLEET SHADOW operable agents allowed even if maturity catalog lags (DESIGNED).

```
$ .venv/bin/python -c "from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher; print(CIOWakeDispatcher().enqueue_goal_wakes(max_new=5))"
```

---

## Acceptance evidence (live host)

### A — agent_runtime --once

| Agent | Result |
|---|---|
| alex | exit 0 · COMPLETED 1 |
| morgan | exit 0 · COMPLETED 1 |
| steph | exit 0 · COMPLETED 1 |

Dispatcher enqueued GOAL_DUE wakes for alex/morgan/steph and `poll_and_dispatch` claimed them without waiting for the 30-min heartbeat alone.

### B — Material path (shadow)

Goal due → wake enqueue → context payload (`get_context_for_agent` summary) → shadow job / run thesis touch.  
Actions still go through existing action ledger writers; `/cio ack` and `/cio rate` already persist (`cio_commands.py`).

### C — Safety

| Check | Result |
|---|---|
| Broker credentials on agents | No |
| Local dumps | 1 · compliant |
| Health dump auto-remediate | denylisted |

### D — Docs

- This file  
- [RUNTIME_TRUTH_2026-08-11.md](./RUNTIME_TRUTH_2026-08-11.md)  
- [AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md](./AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md) (updated)

---

## Tests

```
.venv/bin/python -m pytest tests/test_cio_goals_and_dispatcher.py -q
# 5 passed — goal CRUD, context, dispatcher dedup, backup policy presence
```

---

## Operator notes

1. Goals live under `data/cio/` (canonical tree; release should symlink `data/runtime` already; CIO JSONL is under `data/cio` on project root — ensure timer WorkingDirectory is project root).
2. Heartbeat `cio_heartbeat.py` stays as backstop.
3. Do **not** set production_activation from this work.
4. Content embeddings VACUUM: only via  
   `scripts/maintenance/content_embeddings_maintenance.py --confirm` (never auto).
