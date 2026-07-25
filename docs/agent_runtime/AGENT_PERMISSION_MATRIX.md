# Agent Permission and Authority Matrix

**Contract:** `agent-runtime-monitoring-v1`  
**Applies to:** `config/agent_maturity_catalog.json`  
**Environment:** LAB / SHADOW only

## Global denied authority

| Capability | State | Enforcement intent |
|---|---|---|
| Broker submit/modify/cancel | DENIED | Reflective agents never call broker adapters. |
| Order creation or mutation | DENIED | Agents may critique or stage evidence only. |
| Approval mutation | DENIED | Human/operator approval remains external. |
| 2FA request or verification | DENIED | Agents cannot initiate or satisfy financial authorization. |
| Production database write | DENIED | This tranche is fixture/read-model only. |
| Production config promotion | DENIED | Learning and critique cannot self-promote. |
| Production secret access | DENIED | Raw secrets are excluded from prompts, artifacts, replay, and KB. |
| Service control | DENIED | No systemd, scheduler, provider, or runtime activation. |

## Per-agent scope

| Agent | Read scope | Governed write scope | Explicit denials |
|---|---|---|---|
| Sentinel | tickets, validators, KB lessons/cases | review artifacts, quarantine staging | ticket edits, scores, ratification, promotion |
| Darwin | artifacts, outcomes, cases | independent scores | artifacts, ratification, promotion |
| Iris | lessons, cases, retrieval evidence | lesson reviews, contradictions | ratification, hypothesis/config promotion |
| Nightly Reflection | cases, exceptions, KB | candidate lessons, registered hypotheses | ratification and promotion |
| Argus | population artifacts | exception records | packet repair, ticket writes, promotion |
| Maria | facts, events, KB | research artifacts | entry mechanics and execution |
| Vega | technical facts, closed bars, KB | technical reviews | price truth and execution |
| Pulse | deterministic feature windows and replay | microstructure reviews | raw-tick reasoning and execution |
| Steph | portfolio/account read models, KB | allocation reviews | account/position writes and rebalance submission |
| Guardian Risk | risk, portfolio, events | risk objections | risk override and execution |
| Ledger Tax | tax lots, accounts, cases | tax reviews | basis/lot mutation and execution |
| Hermes | KB, cases, scores | hypothesis registration and experiment plans | self-promotion and config activation |
| Aegis | logs, cases, runs | incident artifacts | shell/service control and broker actions |
| Alex | artifacts, reviews, scores | synthesis artifacts | release, risk override, execution |
| Concierge | governed run/artifact reads | bounded status/cancel/resume/explain requests | shell, production DB, broker, config |
| Atlas | governed run/checkpoint evidence | workflow and handoff records | broker, approval, 2FA, config promotion |

## Database scope

This branch creates no database adapter and changes no schema.

- authoritative persistence belongs to the separately reviewed persistence lane;
- monitoring projections consume mappings/interfaces or fixtures;
- production database writes are unrepresentable;
- future read adapters must use a read-only role and must not expose raw prompts,
  DSNs, connection metadata, credentials, or provider payload dumps.

## Provider and model scope

A catalog budget may permit bounded model calls for a future LAB/SHADOW run.
That does not activate a provider.

- model identity and provider family must be recorded on artifacts;
- local-to-cloud fallback must be explicit and cannot count as independent local
  review;
- paid cost defaults to `$0.00` in the catalog;
- deterministic failure remains sovereign;
- no model result can create financial authority.

## Operator controls

Only governed controls may eventually be exposed:

- status;
- explain;
- cancel;
- resume where terminal-state rules allow it;
- replay;
- evidence navigation.

Controls must not imply execution, approval, 2FA, config promotion, lesson
ratification, or service-control authority.

## Evidence ownership

| Evidence | Owner / reviewer |
|---|---|
| Agent definition and authority | Architecture owner |
| Artifact schema | Agent owner plus independent reviewer |
| Sentinel review outcomes | Darwin and operator review |
| Darwin score policy | Deterministic version owner plus human review |
| Lesson candidates | Reflection producer; Iris/operator reviewer |
| Ratification | Operator/human authority only |
| Authority scan | Integrator and security review |
| Disable/rollback proof | Agent owner and operator |
| Production promotion | Separate operator-controlled gate |

## Fail-closed rules

The monitoring contract rejects:

- missing canonical agents;
- undefined artifact, review, or score policies;
- missing stop conditions;
- missing disable or rollback controls;
- any authority value other than `DENIED`;
- invalid lifecycle states;
- an `OPERATIONAL` claim before acceptance evidence;
- fixture data represented as live runtime evidence.
