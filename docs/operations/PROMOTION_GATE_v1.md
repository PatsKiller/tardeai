# Promotion Gate v1 — Phase 10 (prepare-only)

Status:      ACTIVE
as_of:       2026-07-27T11:56:39-04:00
Measured at: efcc51365 / not measured

**Packet:** E (`scripts/operator_packets/packet_e_promotion_gate.{sh,py}`)  
**Phase:** 10  
**Ack token:** `PROMOTE-AGENT-OPERATIONAL-E`  
**Environment:** SHADOW / LAB evidence only  

## Hard invariants

| Invariant | Status in this phase |
|-----------|----------------------|
| Mark any agent `OPERATIONAL` | **FORBIDDEN** — never done by Packet E |
| Enable agent timers / cron / systemd timers | **FORBIDDEN** — remain disabled |
| Broker / order / approval / 2FA authority | **DENIED** |
| Production `trade_ai` database writes | **FORBIDDEN** |
| Log or print DSN / secrets | **FORBIDDEN** |
| Treat `kb_lessons.lifecycle=CANDIDATE` as production policy | **FORBIDDEN** — CANDIDATE ≠ policy |
| Auto-ratify lessons or promote hypotheses | **FORBIDDEN** |

Phase 10 is a **gate and intent recorder only**. Actual status promotion to
`OPERATIONAL` is deferred to **Phase 11** and requires a human sign-off file under
`docs/operations/promotion_signoffs/` plus an out-of-band acceptance process.
Packet E will refuse execute-without-intent with:

> promotion execute not enabled until Phase 11 human sign-off file

With `--write-intent`, Packet E may write a **signed intent** JSON under
`docs/operations/promotion_intents/`. That file documents the request and preflight
evidence hash. It does **not** change `deployment_state`, catalog files, or DB rows.

## Prerequisites checklist (Packets A–D + Phase 9)

Complete **before** running Packet E preflight for any agent:

### Packet A — LAB / SHADOW foundation

- [ ] **A1** Isolated `agentic_runtime` schema applied only on LAB/SHADOW DB (not production `trade_ai`)
- [ ] **A2** Read plane deployed; reader role least-privilege; zero-authority HTTP surface
- [ ] DSN targets are non-production; DSN values never logged

### Packet B / C — surface deploy (if used)

- [ ] Watch / Defense deploys completed under their own ack tokens
- [ ] No schedule edits performed as part of agent work

### Packet D — SHADOW acceptance population

- [ ] Packet D run completed with `accepted_thresholds: true`
- [ ] `watch_artifacts_processed ≥ 100`, `known_bad_fixtures_processed ≥ 20`
- [ ] `reviews > 0`, independent reviewer and scorer (Phase 9 independence)
- [ ] `agents_marked_operational == 0` on the Packet D report
- [ ] CANDIDATE `kb_lessons` / `kb_cases` / `kb_chunks` present for known-bad path
- [ ] Report JSON retained for `--packet-d-report`

### Phase 9 — independence & authority

- [ ] Reviewer ≠ producer on every review (independence rate 1.0)
- [ ] Scorer ≠ producer on every score (independence rate 1.0)
- [ ] Zero authority violations (no broker/order/approval/2FA/config promote)
- [ ] Maturity gates evaluated; no agent represented as `OPERATIONAL` in catalog
- [ ] Lane D definitions remain SHADOW/DESIGNED (`docs/agent_runtime/LANE_D_SHADOW_AGENTS.md`)

### Operational posture (explicit)

- [ ] **Timers / cron for agents remain disabled** — Packet E does not enable them
- [ ] **Lesson lifecycle CANDIDATE ≠ production policy** — no auto-ratify
- [ ] Operator has reviewed SHADOW evidence out-of-band
- [ ] No production trade path depends on these agents

## What Packet E preflight checks

Given `--agent-id` list + `--ack` + evidence files:

| Gate | Pass condition |
|------|----------------|
| `evidence_source` | `--packet-d-report` and/or `--lab-counts` supplied |
| `reviews_gt_0` | `reviews > 0` |
| `self_review_eq_0` | `self_review == 0` (and Packet D independence rates = 1.0 when present) |
| `kb_candidate_exists` | `kb_lessons_candidate > 0` |
| `read_only_api` | Static GET-only / zero-authority contract on `ReadOnlyAgentRuntimeAPI` |
| `no_operational_from_packet_d` | Packet D did not mark anyone OPERATIONAL |
| `phase9_*_independence` | When Packet D metrics present: rates ≥ 1.0 |
| `catalog_not_operational:*` | Catalog entry (if any) is not already OPERATIONAL |

## Usage

```bash
# Default-disabled / prepare-only
./scripts/operator_packets/packet_e_promotion_gate.sh

# Self-check (no DB)
./scripts/operator_packets/packet_e_promotion_gate.sh --self-check
./scripts/operator_packets/packet_e_promotion_gate.sh <RELEASE_SHA> --self-check

# Preflight only
./scripts/operator_packets/packet_e_promotion_gate.sh <RELEASE_SHA> \
  --preflight \
  --agent-id sentinel --agent-id darwin \
  --ack PROMOTE-AGENT-OPERATIONAL-E \
  --packet-d-report /path/to/packet_d_report.json \
  [--lab-counts /path/to/lab_counts.json]

# Execute: still refuses OPERATIONAL (Phase 11 message)
./scripts/operator_packets/packet_e_promotion_gate.sh <RELEASE_SHA> \
  --execute \
  --agent-id sentinel \
  --ack PROMOTE-AGENT-OPERATIONAL-E \
  --packet-d-report /path/to/packet_d_report.json

# Execute + signed intent only (still not OPERATIONAL)
./scripts/operator_packets/packet_e_promotion_gate.sh <RELEASE_SHA> \
  --execute --write-intent \
  --agent-id sentinel --agent-id darwin \
  --ack PROMOTE-AGENT-OPERATIONAL-E \
  --packet-d-report /path/to/packet_d_report.json
```

### LAB counts JSON shape (optional)

```json
{
  "reviews": 120,
  "self_review": 0,
  "kb_lessons_candidate": 20,
  "agents_marked_operational": 0,
  "read_only_api": true,
  "accepted_thresholds": true
}
```

## Phase 11 (out of scope for this packet)

Human sign-off files (future) live under `docs/operations/promotion_signoffs/`.
Until Phase 11 is implemented and a sign-off file is accepted:

1. No agent `deployment_state` becomes `OPERATIONAL`.
2. Agent timers/cron stay disabled.
3. CANDIDATE lessons stay non-policy.
4. Packet E may only preflight or write intents.

## Related docs

- `docs/agent_runtime/AGENT_HANDBOOK.md` — lifecycle states
- `docs/agent_runtime/LANE_D_SHADOW_AGENTS.md` — SHADOW fleet + maturity gates
- `docs/agent_runtime/AGENT_PERMISSION_MATRIX.md` — denied authorities
- Packet D runner: `scripts/operator_packets/packet_d_shadow_acceptance.py`
- **Next strategic unlock (market data, not agent promotion):**  
  Moomoo Stage 0 read-plane foundation — `docs/operations/MOOMOO_STAGE0_FOUNDATION_v1.md`  
  (Packet F; quotes/history/subscription scaffolds only; **no** order path, **no** agent OPERATIONAL)
