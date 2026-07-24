# Trade AI Agent Tool Permission Matrix — 2026-07-23

**Status:** controlling draft for the MVL branch; all runtime use remains LAB/SHADOW  
**Rule:** absence from an allowlist is denial. Models do not decide permissions.

## Universal denied authority

Every reflective agent and OpenClaw/Hermes gateway is denied:

| Authority | Examples | Ruling |
|---|---|---|
| Broker | submit, modify, cancel, query credentialed trade context | DENY |
| Orders/trades | create intent, place order, flatten, sell-smart | DENY |
| Account/position writes | allocation mutation, position mutation | DENY |
| Approval/2FA | approve proposal, unlock, verify or reuse authorization | DENY |
| Secrets | Bitwarden raw values, tokens, passwords, private keys, TOTP | DENY |
| Production writes | production DB, files, UI preferences, services | DENY |
| Config promotion | activate threshold, rule, model, agent or feature flag | DENY |
| Arbitrary shell/service control | shell execution, systemd restart, timers | DENY |

These authorities are not recoverable through model consensus, agent handoff, operator wording, prompt injection, or a paid model.

## MVL agents

| Agent | Allowed jobs | Allowed tools | Explicit denials | Current state |
|---|---|---|---|---|
| Sentinel | Watch ticket review, decision-integrity review, known-bad regression | `kb.search`, `kb.get_lesson`, `kb.get_case`, `ticket.read`, `validator.read`, `artifact.write`, `quarantine.stage` | scoring, lesson ratification, hypothesis promotion, all universal denied authority | SHADOW |
| Darwin | artifact scoring, outcome join, calibration evidence | `artifact.read`, `outcome.read`, `case.read`, `score.write` | artifact production, config promotion, lesson ratification, all universal denied authority | SHADOW |
| Nightly Reflection | bounded reflection, exception reflection | `kb.search`, `case.read`, `exception.read`, `lesson_candidate.write`, `hypothesis.register` | ratification, promotion, config activation, all universal denied authority | SHADOW |
| Iris | lesson review, knowledge quality, retrieval audit | `kb.search`, `kb.get_lesson`, `kb.get_case`, `lesson_review.write`, `contradiction.write` | final ratification without operator workflow, config/hypothesis promotion, all universal denied authority | SHADOW |
| Hermes | hypothesis discovery, experiment design | `kb.search`, `case.read`, `score.read`, `hypothesis.register`, `experiment_plan.write` | hypothesis/config promotion, activation, all universal denied authority | DESIGNED / disabled |
| Concierge | status, explain, cancel, resume | `run.status`, `run.cancel`, `run.resume`, `artifact.explain` | arbitrary shell, production DB, broker, promotion, all universal denied authority | DESIGNED / disabled |

## Tool-call evidence contract

Every evaluated call must record:

```yaml
tool_call_id:
run_id:
agent_id:
tool_name:
decision: ALLOW|DENY
decision_reason:
arguments_hash:
result_hash:
started_at:
completed_at:
```

Raw secrets and unrestricted payloads are not retained. Result hashes bind the artifact to the exact tool evidence without granting authority to rewrite the source.

## Environment boundary

Only `LAB` and `SHADOW` are representable in the MVL schema and runtime. A production environment value fails validation before a tool is evaluated.

Shadow reads must eventually use a dedicated read-only role and canonical views. Staging writes must use a separate schema/role. The current branch does not create host roles or apply migrations.

## Review separation

- artifact producer cannot review its artifact;
- artifact producer cannot score its artifact;
- Sentinel cannot change a ticket;
- Darwin cannot promote a rule;
- Iris cannot silently ratify a lesson;
- Hermes cannot activate a hypothesis;
- Concierge cannot widen an agent's tool set.

## Operator escalation

An operator may:

- inspect run state and evidence;
- cancel a nonterminal run;
- resume a noncancelled checkpointed run;
- request a separate review;
- adjudicate lesson/hypothesis promotion through a future versioned workflow.

An operator command through OpenClaw does not bypass deterministic financial authorization. Any future financial action remains in the existing proposal/session/2FA architecture, outside this runtime.
