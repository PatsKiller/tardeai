# Evaluation & Shadow Test Plan — Agent Intelligence Foundation

Status:      ACTIVE
as_of:       2026-08-16T23:27:44-04:00
Measured at: efcc51365 / not measured

`READ_ONLY_ADVISORY`. This plan covers **Phase 2.5 (dry replay harness)** and
**Phase 11 (shadow acceptance before behavior influence)**. It defines how we
measure the agent stack against historical data, and how we compare an
*augmented* (memory/MCP-assisted) decision path against the *baseline* path —
**without ever letting the augmented path influence production behavior**.

> **Boundary.** Everything below is read-only and additive. No broker / order /
> stop / 2FA / risk-policy mutation. No network. No write to production stores.
> Shadow comparison never changes what the operator sees.

---

## 1. Dry replay harness (Phase 2.5)

### 1.1 Design

`scripts/lib/agent_replay_harness.py` replays the historical wake corpus
(`data/cio/cio_wake_traces.jsonl`, 397 rows) through the same context chokepoint
the live path will use (`get_context_for_agent`), and — only when a
`decision_loader` supplies decision payloads — through the notification
suppression (`evaluate_notification`) and follow-up binding
(`needs_next_review` / `build_next_review`) logic.

```
load_wake_traces(path) -> list[dict]        # read JSONL, skip blanks/invalid
replay_wakes(wake_path, *, decision_loader, notify) -> metrics
render_replay_report(metrics) -> str
```

The harness is **DRY-ONLY by construction**:

- It only reads historical logs.
- `notify` is accepted for interface parity but **never invoked**.
- `notifications_sent` is a pure computed simulation (what *would* be sent),
  not an actual send.
- There is no code path that writes to a production store or touches Telegram.

### 1.2 Metric definitions

| Metric | Definition | Source |
|--------|-----------|--------|
| `number_of_wakes` | rows replayed | real data |
| `trace_coverage` | rows with non-empty `trace_id` ÷ total rows | real data |
| `trace_completeness` | rows with `phase == "close"` ÷ total rows | real data |
| `decision_lineage_breaks` | rows with `wake_id` but empty `trace_id` | real data |
| `context_build_failures` | wakes where context build raised or produced an invalid envelope | real data |
| `notifications_considered` | decisions evaluated via `evaluate_notification` | simulated |
| `notifications_sent` | decisions that *would* be sent (computed only) | simulated |
| `suppressed` | decisions not sent (carried a `suppressed_reason`) | simulated |
| `duplicate_unchanged` | subset of `suppressed` flagged as unchanged replay | simulated |
| `missing_next_review` | material non-actions (e.g. WAIT) with no durable binding | simulated |
| `operator_dispositions_recovered` | decisions/wakes with a recoverable disposition | simulated |

### 1.3 Honesty: measured vs simulated

The real `cio_wake_traces.jsonl` carries **no decision payloads**
(`decision` is absent from all 397 rows). Therefore:

- **Measured on real data** (always populated): `number_of_wakes`,
  `trace_coverage`, `trace_completeness`, `decision_lineage_breaks`,
  `context_build_failures`.
- **Simulated** (populated only when a `decision_loader` is supplied, or in
  synthetic fixtures): all notification and follow-up metrics.

We must never present a notification/suppression number as "measured from
production" unless a real decision payload was loaded. On the real corpus the
harness honestly reports those as `0` until a loader is wired.

---

## 2. Shadow comparison packet (Phase 11)

For each sampled wake we run **two** decision paths and record a comparison
packet. The baseline path is the current production logic; the augmented path
adds memory retrieval and read-only MCP context. Neither path mutates anything.

### 2.1 Packet schema

```jsonc
{
  "wake_id": "wake-...",
  "trace_id": "tr_...",
  "baseline": {
    "decision_id": "dec_base_...",
    "current_action": "WAIT",
    "act_now": false,
    "context_digest": "ctx_..."
  },
  "augmented": {
    "decision_id": "dec_aug_...",
    "current_action": "REVALIDATE",
    "act_now": false,
    "context_digest": "ctx_..."
  },
  "comparison": {
    "same_decision": false,
    "changed": ["current_action", "next_review.kind"],
    "why": "memory surfaced a prior operator view that shifted the action"
  },
  "inputs_used": {
    "memory_ids": ["m1", "m2"],
    "mcp_context": ["read-only quote refresh"],
    "specialists_changed": ["steph consulted (baseline: none)"]
  },
  "diff_effects": {
    "notification_changed": true,
    "follow_up_changed": true
  },
  "authority": "READ_ONLY_ADVISORY"
}
```

### 2.2 Required comparison fields

- **baseline vs augmented decision** — both decision objects, digest-identified.
- **same/different** — whether the two decisions are materially identical.
- **why** — the human-readable cause of any difference.
- **memory ids** — the episodic-memory records actually retrieved and used.
- **MCP context used** — which read-only MCP calls informed the augmented path.
- **specialists changed** — which specialist inputs differed from baseline.
- **notification changed** — whether the notification decision would differ.
- **follow-up changed** — whether the next-review binding would differ.

---

## 3. Promotion gate criteria

An augmented path is eligible for promotion toward controlled activation only
when **all** of the following hold:

| Criterion | Gate |
|-----------|------|
| Canonical-truth override | **0** — memory/MCP never rewrites `office_truth` |
| Unauthorized action | **0** — no broker/order/stop/2FA/risk-policy mutation |
| Trace coverage | **≥ 99%** of wakes carry a non-empty `trace_id` |
| MCP write attempts denied | **100%** of write-classified MCP calls denied |
| P0 / P1 defects | **0** open P0/P1 |

### 3.1 Honesty rule: small sample sizes

Do not claim maturity from a small or unrepresentative sample.

- Always report **N** (the number of wakes/decisions the measurement covers).
- Report confidence only when N is large enough to support it; otherwise label
  the result **observational, not conclusive**.
- Never phrase a finding as "the system is safe/correct" on the basis of a
  handful of cases — say "no violations observed across N sampled wakes".

---

## 4. Authority

`READ_ONLY_ADVISORY`. Zero broker / order / stop / 2FA / risk-policy mutations.
No network, no secrets, no live side effects. Shadow evaluation is advisory
evidence only; it never changes production behavior.
