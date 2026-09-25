# Agent operating standards v1 (companion to AGENTS.md)

```
Version:   1.0.0 (PROPOSED with AGENTS.md 1.3.0; sections A-G are MINOR operating rules)
Base-SHA:  1c60ecb4264ba4dcc6a38106e76fae0d96a26787
Scope:     how agents work — not language-specific style (that is the engineering standard,
           owned by the architecture/standards workstream; linked below)
```

Every rule states what enforces it today. **ENFORCED** means a named check fails the change.
**PARTIAL** means a check exists but covers only some paths or clients. **POLICY** means the rule
has no mechanical check yet, so a reviewer enforces it. Nothing here claims more than that.

Language-specific formatting, lint, types, tests, migrations and logging are in
[`docs/governance/ENGINEERING_STANDARD.md`](../ENGINEERING_STANDARD.md). This file does not restate
them. Start at [`docs/governance/NEW_AGENT_STARTS_HERE.md`](../NEW_AGENT_STARTS_HERE.md); find owners
via [`docs/architecture/ARCHITECTURE_INDEX.md`](../../architecture/ARCHITECTURE_INDEX.md).

---

## A. Code and annotations

| rule | enforcement |
|---|---|
| Before editing, record the base SHA, the served SHA if runtime matters, the modules, contracts and named stores touched, the risk class, and the smallest relevant test. | POLICY (PR template section "Scope") |
| Search for an existing producer or contract before adding one (AGENTS.md §13.5). | POLICY |
| The smallest coherent change. A refactor never changes financial authority. | POLICY + independent review on sensitive paths (section D) |
| Changed Python files pass the pinned Ruff (0.16.2, rules in `pyproject.toml`); legacy ignores (`F401/F811/F841`) are ratcheted file by file, never widened. | ENFORCED — `scripts/agent_changed_file_quality.py`, `agent-governance` workflow |
| Tests exercise the behaviour, one refusal path, and preservation-on-failure for a stateful producer. | POLICY |
| A new test file is registered in the CI route that runs it. | ENFORCED — `scripts/check_test_coverage.py --fail-on-new` |
| Comments explain *why* a non-obvious rule exists and cite a stable issue, incident, PR or contract; they never restate the code. | POLICY |
| A `TODO` names an owner, a tracked item and a review date. | POLICY |
| Every runtime claim in a PR, doc or report is labelled `OBSERVED`, `CODE-ONLY`, `DOC-CLAIM` or `UNKNOWN`, with the SHA and the receipt (AGENTS.md §4). | POLICY |

## B. Contracts, versions and provenance

| rule | enforcement |
|---|---|
| A public data structure or state transition carries `schema`/version, owner, producer, consumer, authority, source id, `as_of`, a freshness bound, and explicit unknown/unavailable semantics. | PARTIAL — `scripts/check_dark_contracts.py --fail-on-new` catches a contract with no consumer; the field list is reviewer-enforced |
| A new data source or writer of an authoritative store is a registry row with an operator `approval` (AGENTS.md §7A). | ENFORCED — `scripts/check_data_source_authority.py` (`UNAPPROVED_SOURCE`) |
| A breaking change to a contract gets a new `@vN`; the old one stays readable until every consumer moves. | POLICY |
| Unknown is never zero, empty is never healthy (AGENTS.md §5, §9.1). | POLICY |

## C. Concurrent agents, worktrees and leases

| rule | enforcement |
|---|---|
| Every mutating session works in its own registered worktree (`scripts/new-worktree.sh`) and starts with `scripts/agent_session_start.py`. | PARTIAL — the primary tree is hook-guarded; worktree identity is tested (`tests/test_agent_worktree_identity.py`) |
| Claim the paths and named stores you will change; check peer leases and open PRs touching them; heartbeat the lease. | PARTIAL — `scripts/lib/agent_file_lease.py` (`tests/test_agent_session_and_lease.py`, `test_agent_file_lease_canonical.py`) |
| Leases are **host-local**. A second machine does not see them; cross-host work serializes through one coordinator. | POLICY |
| On a stale or overlapping lease, stop mutating and escalate. Never steal a live claim. | POLICY |
| **Never use `git stash`** — the stash list is shared across every worktree (two agents popped each other's work on 2026-09-23). Use a WIP commit. | POLICY |
| The coordinator owns integration and closeout. No agent calls its own work independently reviewed. | POLICY |

## D. GitHub branches, PR evidence, review and CI

| rule | enforcement |
|---|---|
| A PR states base and head SHAs, owned files/stores, authority class, contract changes, migrations, negative tests, proof artifacts, rollback, and the served-release verification plan. | PARTIAL — `.github/pull_request_template.md` (added here); a mechanical check is a follow-up |
| Exact-head CI must pass after the final amendment; a PR whose base moved is re-verified, not assumed. | PARTIAL — `main` requires `cio-hardening` with `strict: true`; other jobs are not required (see admin actions) |
| Sensitive paths need an independent reviewer who is not the author. | **NOT ENFORCED** — `.github/CODEOWNERS` added here, but `require_code_owner_reviews` is false and `required_approving_review_count` is 0 (measured 2026-09-25) |
| Push, merge, deploy and broker authority are separate grants (AI_WORK_POLICY §16, §21, §27; amendment §3). | PARTIAL — pre-push hook + guard ledger for push/release; merge/deploy by operator |
| Force-pushing a pushed PR branch is refused; restack with merge commits. | ENFORCED — tool permission deny (observed 2026-09-24) |
| GitHub is never a shared working directory; checkpoints are local commits (AGENTS.md §0 rule 4). | ENFORCED — pre-push hook + push budget counter |

Branch protection and required-context changes are §17 operator actions:
`REPOSITORY_PROTECTION_ADMIN_ACTIONS.md`.

## E. Secrets (Bitwarden Secrets Manager)

| rule | enforcement |
|---|---|
| Bitwarden Secrets Manager is the only source of truth for production, shadow and lab credentials, in separate projects with least-privilege machine accounts. | POLICY — inventory not audited (review finding; operator audit) |
| Source, PRs, fixtures, prompts, logs, Drive docs and GUI hold **logical identifiers only**, never values. | ENFORCED for git — `scripts/check_no_secrets.py` (pre-commit and `--tree` pre-push) |
| Runtime injection is short-lived and never echoed. A secret never appears in a process argv: systemd `ExecStart` must use `$$VAR` so the shell, not systemd, expands it (2026-09-24 incident). | POLICY |
| The Bitwarden bootstrap token is a documented exception: owner, storage path, rotation and revocation procedure. | POLICY — document owed |
| No coding agent retrieves or rotates a production secret under a generic grant. `guard` lists secret access as never grantable. | ENFORCED at the shell hook — `bin/guard scopes` ("secret: never grantable"); not at other entry points |
| A detected leak means revoke, review history and remnants, and file an incident receipt. Deleting the file is not a fix. | POLICY |

## F. Persistent agent identity and memory

| rule | enforcement |
|---|---|
| Each persistent agent has one registered identity, owner, authority, deployed model/version, input contract, source freshness, a single writer per state store, checkpoint/retry/idempotency key, stop condition, budget, consumer and rollback. | PARTIAL — `config/agent_clients.yaml` and the lane registry cover some fields |
| A memory record carries the subject GUID, evidence ids, valid time, ingestion (transaction) time, author, contradiction state, TTL/retention and provenance. | ENFORCED for the bitemporal store (schema + 22 post-checks, `docs/ops/COGNITIVE_MEMORY_PRODUCTION_RUNBOOK.md`); POLICY elsewhere |
| Retrieval records the ids it actually selected, including counter-evidence. Memory placed in another agent's prompt is **not** that agent's read receipt. | POLICY |
| Memory writes run with the least-privileged role, and are tested as that role, not as the owner (2026-09-24: `FOR UPDATE` passed as owner, failed in production). | ENFORCED for the integrator — `tests/test_memory_agent_least_privilege_20260924.py` |
| Learning may propose; deterministic validation, independent review and operator authority promote. `MBI_BEHAVIOR = 0` holds. | ENFORCED — `BehaviorWriteRefused` (`scripts/lib/cio_instrument_record.py:390`) |

## G. GUI claims

| rule | enforcement |
|---|---|
| Every GUI route is registered with its owner, canonical API and producer, field definitions and units, served SHA, `as_of`/freshness, empty/error behaviour, feature flag, and a smoke test. | POLICY — registry owed (see [`ARCHITECTURE_INDEX.md`](../../architecture/ARCHITECTURE_INDEX.md)) |
| A route distinguishes configured, shadow, observed-live, blocked, stale and unknown. | PARTIAL — v3 control-plane envelopes carry `UNAVAILABLE` |
| No hardcoded runtime model, maturity pass count, account value or agent-activity claim is shown as a live fact. | **NOT ENFORCED** — `apps/command-center-v3/src/pages/AgentsHub.tsx` embeds a fixed model and roster; `config/agent_maturity_catalog.json` carried a stale "11/12" (truth-repair workstream) |
| After a deploy, the displayed value is checked against the canonical store, not inferred from a green build. | POLICY |

---

### Grants (review finding 6) — what they are and are not

A guard grant names the principal, role, worktree/session, action class, resource, plan or
PR/head SHA, environment, expiry, maximum uses, reason, approver and audit id. It is
**bounded permission for one operation class**. Recorded facts, measured 2026-09-25:

- The shell classifier (`.cursor/hooks/guard-lib.sh`) matches command text and paths
  heuristically. It is not a sandbox, and it does not govern Python entry points, web APIs, IDE
  edits, other hosts or the production service.
- `config/agent_clients.yaml` marks several clients `enforcement_level: ADVISORY`.
- Telegram approval (`scripts/lib/guard_remote_approval.py:239 verify_and_consume`) checks
  `chat_id` only. `from_id` is stored as metadata. **Proposed:** also require an allow-listed
  sender id, so a group chat member cannot approve.
- Grants of the same scope replace each other across sessions (observed 2026-09-24). Re-check
  `bin/guard show` immediately before a guarded action, and never use a grant whose stated reason
  does not cover the work.

Hence the rule for anything financial: authorization is **re-checked at the resource that
mutates** (for broker mutations, `TRADING_SESSION_GRANT_CONTRACT.md`), never only at the shell.
