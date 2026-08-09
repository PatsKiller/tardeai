# Phase 2 Authority Matrix — Alex CIO Agent

**Date:** 2026-08-08
**Phase:** P2.0 Authority Freeze
**Status:** FROZEN

---

## 1. Alex Authority Classification

### READ Authority

Alex may READ (through deterministic Trade AI service interfaces only):

- Canonical Trade AI financial state (portfolio, holdings, performance, risk, tax, retirement)
- Data Broker outputs (all domains)
- Deterministic portfolio/risk/tax/retirement evidence
- CIO actions / runs / handoffs / artifacts (via CIO Action Ledger, CIO Run Store)
- Health decisions / wake jobs (via Health Boundary, Wake Job Store)
- Hermes challenges/results (via Hermes Challenge Queue)
- Notification delivery state (via Notification Outbox)
- Operator profile / IPS / goals (via cio_operator_profile.py)
- Specialist artifacts / handoff results
- Financial domain capability matrix

### WRITE Authority (Through Deterministic Services ONLY)

Alex may WRITE through the following deterministic service interfaces:

- CIO action create/update → CIOActionLedger (P-1.3)
- Handoff enqueue → AgentHandoffQueue (P-1.4)
- Hermes challenge request → HermesChallengeQueue (P-1.9)
- Operator notification enqueue → NotificationOutbox (P-1.7)
- CIO run/case state → CIORunStore (P2.3)
- Learning candidate proposal (future, P2.6+)

### DENY Authority

Alex MUST NOT:

- Submit broker orders
- Mutate positions
- Mutate risk limits
- Mutate stop levels
- Mutate account settings
- File taxes
- Access 2FA credentials
- Access secrets/credentials
- Direct database write
- Raw event-store file append (outside service interface)
- Run systemctl/sudo/cron
- Perform infrastructure remediation
- Deploy code
- Merge git branches
- Self-modify production policy
- Use direct paid-model (OpenAI/Anthropic) as fallback

---

## 2. Machine-Readable Authority-by-Tool Allowlist

| tool_id | domain | read_or_write | deterministic_service | authority_class | allowed_agents | requires_operator_confirmation | requires_health_ready | requires_action_id | requires_run_id | audit_fields |
|---|---|---|---|---|---|---|---|---|---|---|
| tradeai_read_portfolio | portfolio | read | Data Broker | READ_ONLY | alex, maria, steph, guardian, ledger | false | false | false | false | caller, timestamp, domain |
| tradeai_read_holdings | portfolio | read | Data Broker | READ_ONLY | alex, maria, steph, guardian, ledger | false | false | false | false | caller, timestamp, domain |
| tradeai_read_performance | performance | read | Data Broker | READ_ONLY | alex, steph | false | false | false | false | caller, timestamp, domain |
| tradeai_read_attribution | performance | read | Data Broker | READ_ONLY | alex, steph | false | false | false | false | caller, timestamp, domain |
| tradeai_read_risk | risk | read | Risk services | READ_ONLY | alex, guardian, steph | false | false | false | false | caller, timestamp, domain |
| tradeai_read_tax | tax | read | Tax services | READ_ONLY | alex, ledger, steph | false | false | false | false | caller, timestamp, domain |
| tradeai_read_retirement | retirement | read | Data Broker | READ_ONLY | alex, steph, ledger | false | false | false | false | caller, timestamp, domain |
| tradeai_read_health | health | read | CIOHealthBoundary | READ_ONLY | alex, all | false | false | false | false | caller, timestamp |
| cio_action_create | action | write | CIOActionLedger | GOVERNED_WRITE | alex | true | true | true | true | caller, action_id, run_id, timestamp, hash |
| cio_action_update | action | write | CIOActionLedger | GOVERNED_WRITE | alex | true | true | true | true | caller, action_id, run_id, timestamp, hash |
| cio_action_read | action | read | CIOActionLedger | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| cio_handoff_enqueue | handoff | write | AgentHandoffQueue | GOVERNED_WRITE | alex, maria | false | true | false | true | caller, handoff_id, run_id, timestamp, hash |
| cio_handoff_read | handoff | read | AgentHandoffQueue | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| cio_handoff_claim | handoff | write | AgentHandoffQueue | GOVERNED_WRITE | alex, steph, guardian, ledger | false | true | false | true | caller, handoff_id, run_id, timestamp |
| cio_hermes_challenge_request | hermes | write | HermesChallengeQueue | GOVERNED_WRITE | alex | false | true | false | true | caller, challenge_id, run_id, timestamp, hash |
| cio_hermes_challenge_read | hermes | read | HermesChallengeQueue | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| cio_notification_enqueue | notification | write | NotificationOutbox | GOVERNED_WRITE | alex | true | true | false | true | caller, notification_id, run_id, timestamp, hash |
| cio_notification_read | notification | read | NotificationOutbox | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| cio_run_create | run | write | CIORunStore | GOVERNED_WRITE | alex | false | true | false | true | caller, run_id, timestamp, hash |
| cio_run_update | run | write | CIORunStore | GOVERNED_WRITE | alex | false | true | false | true | caller, run_id, timestamp, hash |
| cio_run_read | run | read | CIORunStore | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| cio_profile_read | profile | read | cio_operator_profile | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| cio_profile_write | profile | write | cio_operator_profile | GOVERNED_WRITE | alex | true | false | false | false | caller, version, timestamp, hash |
| cio_learning_propose | learning | write | Learning Candidate Store | GOVERNED_WRITE | alex | true | true | false | true | caller, candidate_id, run_id, timestamp |
| tradeai_read_capabilities | capability | read | Financial Domain Matrix | READ_ONLY | alex | false | false | false | false | caller, timestamp |
| tradeai_read_wake | wake | read | CIOWakeJobStore | READ_ONLY | alex | false | false | false | false | caller, timestamp |

---

## 3. DENY Table (Explicit Prohibitions)

| tool_id | domain | reason | enforcement |
|---|---|---|---|
| broker_submit_order | execution | Broker order authority is NEVER granted to agents | API gateway deny |
| broker_cancel_order | execution | Broker order authority is NEVER granted to agents | API gateway deny |
| position_open | portfolio | Position mutation is NEVER granted to agents | API gateway deny |
| position_close | portfolio | Position mutation is NEVER granted to agents | API gateway deny |
| position_adjust | portfolio | Position mutation is NEVER granted to agents | API gateway deny |
| risk_limit_set | risk | Risk-limit mutation is NEVER granted to agents | API gateway deny |
| stop_set | risk | Stop-level mutation is NEVER granted to agents | API gateway deny |
| account_mutate | account | Account mutation is NEVER granted to agents | API gateway deny |
| tax_file | tax | Tax filing authority is NEVER granted to agents | Out of scope |
| credential_access | security | Secret access is NEVER granted to agents | Secret manager deny |
| db_direct_write | data | Direct database write bypasses event sourcing | File permission deny |
| event_store_raw_append | data | Raw event-store append bypasses service validation | File permission deny |
| systemctl | infra | System control is NEVER granted to agents | OS permission deny |
| sudo | infra | Elevated privilege is NEVER granted to agents | OS permission deny |
| crontab | infra | Schedule mutation is NEVER granted to agents | OS permission deny |
| code_deploy | infra | Code deployment is NEVER granted to agents | Out of scope |
| git_merge | infra | Git merge is NEVER granted to agents | Out of scope |
| policy_self_modify | governance | Self-modifying production policy is NEVER allowed | File permission deny |
| direct_paid_model | model | Direct OpenAI/Anthropic fallback is PROHIBITED | Governed bridge enforce |
| pro_max_auto_elevate | model | Automatic PRO_MAX elevation is NEVER allowed | Process registry enforce |

---

## 4. Authority Class Definitions

| Class | Description | Gate |
|---|---|---|
| READ_ONLY | Data access only, no mutations | Always allowed |
| GOVERNED_WRITE | Write through deterministic service interface with audit | Requires health_ready + run context |
| OPERATOR_CONFIRMED | Write requires operator confirmation via notification | A3 actions require operator review |
| NEVER | Permanently prohibited for agents | API/OS/File permission deny |
| P3_GATED | Defined but unreachable until Phase 3 authorization | Phase 3 gate |
