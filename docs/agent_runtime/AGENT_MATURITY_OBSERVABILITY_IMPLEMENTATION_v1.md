# Agent Maturity Observability Implementation v1

This tranche adds read-only observability. It does not activate, promote, enable, deploy, schedule, or grant authority to any agent.

## Contract

Canonical schema: `agent-maturity-observation-v1`.

API contract: `agent-maturity-read-api-v1`.

Routes:

- `GET /api/v3/agent-maturity`
- `GET /api/v3/agent-maturity/summary`
- `GET /api/v3/agent-maturity/{agent_id}`

Mutation methods return 405 through the existing zero-authority read dispatcher. The repository-only maturity route can answer when the DB-backed Agent Runtime reader is unavailable, but it reports production runtime state as unverified.

## Source Adapters

Implemented in `scripts/agent_runtime/maturity_observability.py`.

Adapters are additive and normalize:

- Agent Runtime catalog and MVL config.
- Agent Runtime definition fleet.
- Hermes maturity-v2 config and honest gate evidence references.
- Proposal review, broker oversight, and defense adjudication provenance references.
- OpenClaw/Concierge declared lifecycle from safe repository evidence only.

The read model does not average Agent Runtime MVL and Hermes maturity-v2 scores. Top-level summaries count states and frameworks only.

## Three Truth Rules

Promotion authority is always `HUMAN_ONLY`.

`automatic_promotion_permitted` is always `false`.

Repository configuration is never displayed as proof of live production runtime activation. The read model separates declared activation (`declared_production_activation_authorized`) from live verification (`effective_production_activation_verified`). Unknown activation declarations remain null/UNVERIFIED rather than fabricated false.

## Gate Truth Table

Only `HEALTHY` review evidence can contribute to maturity eligibility, and only when framework-specific gates are also measured and passed.

| Review health | Sufficient samples result | Eligibility |
|---|---|---|
| `HEALTHY` | may pass only when remaining framework gates are complete | may become `ELIGIBLE_FOR_HUMAN_REVIEW` |
| `DEGRADED_FALLBACK` | `INSUFFICIENT_EVIDENCE` | `HUMAN_REVIEW_REQUIRED` |
| `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `NOT_RUN` | `NOT_RUN` | `NOT_ELIGIBLE` |
| `STALE_CACHE` | `STALE` | `HUMAN_REVIEW_REQUIRED` |
| `TIMEOUT` / `INVALID_OUTPUT` | `FAILED` | `NOT_ELIGIBLE` |
| `MISSING_REVIEWER` / `INCOMPLETE_CONSENSUS` / `PROVIDER_UNAVAILABLE` | `INSUFFICIENT_EVIDENCE` | `HUMAN_REVIEW_REQUIRED` |

Deterministic fallback remains visible as operational degradation where existing policy allows it, but it does not count as successful maturity evidence.

## Framework Thresholds

Supported exact threshold: Agent Runtime MVL `min_artifact_population` requires 100 reviewed artifacts, read from `scripts/agent_runtime/agents/maturity_gates.py`.

Unsupported exact thresholds: Hermes maturity-v2, broker oversight provenance, defense adjudication, and runtime-only OpenClaw metadata do not expose a complete next-rung sample gate from repository evidence alone. Those rows return `required_sample_size: null` and `next_gate_state: UNKNOWN` with operator checks.

## Review Provenance

Supported provenance states:

- `MODEL_REVIEW`
- `DETERMINISTIC_FALLBACK`
- `CACHED_MODEL_REVIEW`
- `MANUAL_REVIEW`
- `NOT_RUN`
- `UNKNOWN`

Supported health states include healthy, fallback, timeout, stale cache, missing reviewer, incomplete consensus, provider unavailable, invalid output, not run, and unknown.

## Command Center v3

The existing Agents Runtime tab now renders a Maturity scoreboard with:

- stable agent identity;
- subsystem and environment;
- lifecycle and effective authority;
- maturity framework and version;
- sample progress;
- next gate state;
- review health and provenance;
- human-review eligibility;
- runtime evidence status;
- warnings and operator checks.

The UI adds no promote, activate, deploy, approval, broker, or 2FA controls.

## Sanitized Runtime Inventory

Schema: `config/schemas/openclaw_runtime_inventory.schema.json`.

Example: `config/examples/openclaw_runtime_inventory.sanitized.example.json`.

Helper: `scripts/agent_runtime/sanitize_openclaw_runtime_inventory.py`.

The helper refuses raw `.openclaw/openclaw.json` paths and rejects secret-like keys.

## Historical Completeness Dry Run

Analyzer: `scripts/agent_runtime/outcome_completeness_dry_run.py`.

The analyzer reports missing outcome/provenance fields and candidate derived records with `dry_run: true` and `write_attempted: false`. It does not backfill or write production rows.

## Deployment Status

Not deployed.

No service or timer was enabled or started.

No production configuration or runtime state was changed.
