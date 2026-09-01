# Rollback Runbook — Controlled Read-Only Activation (Phase 12)

Status:      ACTIVE
as_of:       2026-08-17T23:11:04-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY`. This runbook describes how to **roll back** any Phase 12
feature-flag activation and how to confirm core CIO decisions still work after
rollback. Rollback is the default posture: if anything is uncertain, revert to
the conservative flag set and re-verify.

The canonical rollback set lives in `scripts/lib/agent_feature_flags.py`
(`rollback_flags()`), and is identical to `DEFAULT_FLAGS`.

---

## 1. The rollback flag set

Apply exactly these values (equivalent to unsetting every activation flag):

```bash
export MEMORY_BEHAVIOR_INFLUENCE=0
export MCP_READ_ONLY_GATEWAY=0
export MEMORY_PROVIDER=null
export GOVERNED_MEMORY_ADVISORY_INFLUENCE=OFF
export LANGGRAPH_WORKER_PILOT=0
# observability flags return to conservative defaults as well:
export AGENT_CONTEXT_ENVELOPE=0
export AGENT_RUN_TRACE=0
export MEMORY_SHADOW=0
```

In code, `rollback_flags()` returns the identical conservative config:

```python
from scripts.lib.agent_feature_flags import rollback_flags, behavior_influence_active
rb = rollback_flags()
assert rb["MEMORY_BEHAVIOR_INFLUENCE"] == 0
assert rb["MCP_READ_ONLY_GATEWAY"] == 0
assert rb["MEMORY_PROVIDER"] == "null"
assert rb["LANGGRAPH_WORKER_PILOT"] == 0
assert behavior_influence_active(rb) is False
```

| Flag | Rollback value | Why this is safe |
|------|----------------|------------------|
| `MEMORY_BEHAVIOR_INFLUENCE` | `0` | Memory stops shaping advisory context immediately |
| `MCP_READ_ONLY_GATEWAY` | `0` | The read-only MCP path is taken out of the loop |
| `MEMORY_PROVIDER` | `"null"` | Memory retrieval degrades to `NOT_CONFIGURED` no-op |
| `LANGGRAPH_WORKER_PILOT` | `0` | No LangGraph pilot activity |

With this set, `behavior_influence_active()` is `False`, so no memory influence
can survive a rollback even if a caller forgets to check the other flags.

---

## 2. How to roll back

1. **Set the rollback environment** as above (or clear all `AGENT_*` / `MCP_*` /
   `MEMORY_*` / `LANGGRAPH_*` variables so defaults apply).
2. **Restart the affected services** so the new environment is read (portfolio-
   server, the governed bridge, Telegram transport, and any agent-runtime units
   that consume these flags).
3. **Confirm the flags actually loaded**:

   ```python
   from scripts.lib.agent_feature_flags import load_feature_flags, behavior_influence_active
   flags = load_feature_flags()
   print(flags)
   print("behavior_influence_active:", behavior_influence_active(flags))
   ```

4. **Re-run the verification** in section 3 below.

---

## 3. Confirm core CIO decisions still work after rollback

Rollback must **not** break the core advisory path. Confirm each of the
following:

1. **Health** — `/v3/cio` returns 200; the governed bridge and Telegram
   transport are up and healthy.
2. **Decision parity** — the post-rollback decision output is identical to the
   pre-activation baseline for the same inputs (same `decision_id`, same
   `current_action`, same `act_now`).
3. **Truth intact** — `office_truth` is unchanged; canonical cash/holdings/risk
   values are the deterministic engine's, never memory's.
4. **Authority intact** — every envelope still reports
   `authority == READ_ONLY_ADVISORY` and
   `memory_authority == NON_AUTHORITATIVE_CONTEXT`.
5. **Zero mutation** — no broker/order/stop/2FA/risk-policy mutation appears in
   any trace after rollback.
6. **Missing-memory degradation** — with `MEMORY_PROVIDER=null`, memory retrieval
   reports `NOT_CONFIGURED` explicitly (fail-soft), never a stale or guessed
   value.

A reusable post-rollback self-check:

```python
from scripts.lib.agent_feature_flags import load_feature_flags, behavior_influence_active
flags = load_feature_flags()
assert flags["AGENT_CONTEXT_ENVELOPE"] == 0
assert flags["AGENT_RUN_TRACE"] == 0
assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0
assert flags["MCP_READ_ONLY_GATEWAY"] == 0
assert flags["MEMORY_PROVIDER"] == "null"
assert flags["MEMORY_SHADOW"] == 0
assert flags["LANGGRAPH_WORKER_PILOT"] == 0
assert behavior_influence_active(flags) is False
```

---

## 4. What "must not break" means

- **Core CIO decisions.** The advisory office still produces the same canonical
  recommendation for the same inputs. Rollback removes *augmentation*, not
  *decision-making*.
- **Canonical truth.** The deterministic engines and `office_truth` remain the
  single system of record; memory/MCP never wrote to them in the first place, so
  there is nothing to un-write.
- **Broker safety.** No order, stop, 2FA, or risk-policy state was ever touched,
  so rollback has nothing to reconcile on the execution side.
- **Fail-soft behavior.** A rolled-back system degrades to `NOT_CONFIGURED` /
  `null` everywhere — it must not raise, hang, or fall back to stale memory.

In short: **rollback returns the system to its pre-activation state, and the
pre-activation state is the fully-working `READ_ONLY_ADVISORY` baseline.** If
any of the six confirmations in section 3 fails, do not re-enable; escalate to
the operator and treat it as a P0 until resolved.

> The office advises. It never decides for the operator.
