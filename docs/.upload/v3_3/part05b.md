GMAIL_SEND_AS
ACTIVE_TRADER_DRIVE_FOLDER_ID
```

Email subjects:

```text
PASS: Trade AI Active Trader night run <run_id>
STOPPED: Trade AI Active Trader night run <run_id> at stage <n>
ACTION REQUIRED: Trade AI Active Trader credentials and operator tasks <run_id>
```

The email includes:

- run state;
- branch and draft PR;
- stage commits;
- Drive folder;
- green/failed stage;
- tests;
- live-system impact;
- operator TODO;
- credential TODO;
- architecture litmus verdict;
- next recommended action.

No broker credentials or secret values appear in email.

## 16K.9 Bitwarden credential scaffolding

The implementation program produces:

```text
config/credential_requirements/active_trader.yaml
docs/implementation/.../CREDENTIAL_REQUIREMENTS.md
docs/implementation/.../OPERATOR_TODO.md
```

For each requirement:

```yaml
secret_name:
project:
environment:
required_by_stage:
purpose:
format:
scope:
rotation:
operator_supplied:
placeholder_allowed:
service_identity:
verification_method:
```

Automatic behavior:

- create required placeholder secret records in `trade-ai-lab` when the lab Bitwarden machine account has write permission;
- use a sentinel value such as `UNSET__OPERATOR_REQUIRED`;
- code must reject sentinel values;
- never invent or derive a broker credential;
- never copy production secrets into lab;
- create production placeholder records only when the night-run envelope explicitly grants Bitwarden production-placeholder write authority;
- otherwise list exact production creation steps in the operator TODO.

Required likely credential families:

```text
MOOMOO_DATA_*
MOOMOO_TRADE_UNLOCK_*
ALPACA_* per enabled account/environment
SCHWAB_* OAuth application and token material
GOOGLE_DRIVE_SYNC_*
GMAIL_NOTIFICATION_*
OPERATOR_NOTIFICATION_EMAIL
```

The exact names are discovered against the existing secrets convention before creation.

## 16K.10 Unattended prerequisites

The night run does not begin unless preflight proves:

- GitHub branch push;
- Google Drive write and hash verification;
- Gmail send test to the configured operator;
- lab Bitwarden write;
- test database/migration rollback;
- no live broker credential mounted in the implementation environment;
- no production deploy credential;
- no live feature flag enabled;
- enough disk space;
- deadline and resource budget;
- checkpoint directory writable.

If the notification email cannot be proven, unattended mode does not start.

## 16K.11 Overnight boundaries

The unattended run may complete architecture-approved implementation and non-live tests.

It must stop before:

- production deployment;
- production migration activation;
- live feature enablement;
- real session 2FA;
- Moomoo live unlock;
- live order submission;
- merge to main.

Those actions use a later operator start prompt tied to the exact reviewed SHA.

# 17. BROKER, ACCOUNT, AND ORDER AUTHORITY

## 17.1 Capability registry

```text
broker_accounts
broker_capabilities
routing_policies
execution_arm_state
order_authorizations
order_intents
adapter_health
```

## 17.2 Current capability posture

| Broker | Current controlling posture |
|---|---|
| Schwab | transport/pilot capability subject to existing gates and the applicable per-order authorization policy |
| Alpaca simulation | enabled testing lane where configured |
| Alpaca live | capability must be proven; no assumption from scaffold |
| Moomoo | data-only first; simulation next; live scalp canary approved once adapter and P11 gates are complete |
| SnapTrade | excluded pending evidence |

## 17.3 Routing chain

```text
released ticket
  → account eligibility
  → adapter capability
  → account sizing
  → risk and concentration
  → immutable order intent
  → simulation authorization
       OR per-order live authorization
       OR active momentum-scalp session authorization
  → adapter
  → broker acknowledgment
  → order-state reconciliation
```

No routing policy can omit proof of the applicable authorization mode.

## 17.4 Order intent

```yaml
order_intent_id:
ticket_id:
account_id:
broker:
symbol:
side:
quantity:
order_type:
limit_price:
stop_price:
targets:
time_in_force:
session:
children:
expires_at:
input_hash:
validation_hash:
risk_hash:
authorization_mode:
session_authorization_id:
authorization_hash:
status:
```

## 17.5 Execution authority

Reflective agents have no `BROKER_WRITE` capability.

Only the deterministic execution service can call adapters after authorization.

---

# 18. DATA MODEL

## 18.1 Agentic MVL tables

```text
agent_runs
agent_artifacts
agent_tool_calls
agent_reviews
agent_scores
kb_lessons
kb_cases
kb_chunks
```

## 18.2 Deferred runtime tables

Add only after need:

```text
agent_steps
agent_checkpoints
agent_handoffs
agent_budgets
agent_exceptions
agent_model_calls
agent_definitions
agent_capabilities
```

## 18.3 Moomoo control tables

```text
md_subscription_state
md_entitlement_state
md_data_quality
md_feature_snapshot
md_replay_manifest
md_sequence_gap
md_session_state
```

## 18.4 Scalp tables

```text
scalp_candidates
scalp_fires
scalp_shadow_outcomes
scalp_sim_orders
scalp_sim_trades
scalp_live_order_intents
scalp_audit
scalp_config_versions
active_trader_session_drafts
active_trader_session_authorizations
active_trader_session_accounts
active_trader_order_intents
active_trader_position_states
active_trader_journal_events
active_trader_score_snapshots
active_trader_parity_checks
broker_account_capabilities
broker_rejection_events
active_trader_feature_flags
active_trader_notification_events
active_trader_drive_sync_manifest
active_trader_run_checkpoints
```

Do not merge simulation and live order rows without an explicit environment discriminator and hard database constraints.

## 18.5 Hypothesis tables

```text
hypotheses
hypothesis_evaluations
hypothesis_adjudications
promotion_proposals
promotion_observations
```

---

# 19. API AND MCP CONTRACTS

## 19.1 Read tools

```text
read_watch_ticket
read_ticket_validation
read_operator_presentation
read_position
read_account
read_event
read_microstructure_snapshot
read_market_replay
search_kb
read_case
read_agent_run
read_agent_score
```

## 19.2 Staging tools

```text
create_review
create_exception
create_case
create_lesson_candidate
create_hypothesis
request_ticket_rebuild
request_model_review
request_premium_estimate
stage_order_intent
save_active_trader_session
authorize_active_trader_session
activate_active_trader_session
pause_active_trader_session
revoke_active_trader_session
request_active_trader_kill_switch
```

## 19.3 Active Trader API

```text
GET    /api/v3/active-trader/session
POST   /api/v3/active-trader/session/draft
POST   /api/v3/active-trader/session/validate
POST   /api/v3/active-trader/session/2fa
POST   /api/v3/active-trader/session/activate
POST   /api/v3/active-trader/session/pause
POST   /api/v3/active-trader/session/revoke
POST   /api/v3/active-trader/session/kill
GET    /api/v3/active-trader/candidates
GET    /api/v3/active-trader/symbol/:symbol
GET    /api/v3/active-trader/accounts
GET    /api/v3/active-trader/orders
GET    /api/v3/active-trader/positions
GET    /api/v3/active-trader/journal
GET    /api/v3/active-trader/parity
WS     /ws/v3/active-trader
```

All mutating endpoints require:

- authenticated operator;
- optimistic session version;
- idempotency key;
- audit reason;
- CSRF/session protection;
- server-side authorization and policy checks.

## 19.4 Broker actions and feature control

```text
GET    /api/v3/active-trader/brokers
GET    /api/v3/active-trader/brokers/capabilities
GET    /api/v3/active-trader/rejections
POST   /api/v3/active-trader/order/:id/cancel
POST   /api/v3/active-trader/orders/cancel-all
POST   /api/v3/active-trader/position/add
POST   /api/v3/active-trader/position/sell-smart
POST   /api/v3/active-trader/position/flatten
GET    /api/v3/active-trader/features
POST   /api/v3/active-trader/features
GET    /api/v3/active-trader/run-state
```

Mutating order endpoints require an active session authorization and exact account/symbol scope.

The feature-control endpoint cannot enable production live trading without a separately verified live-canary state.

## 19.5 Denied tools

```text
raw_secret_read
arbitrary_sql_write
production_config_write
unbounded_shell
broker_write
approval_mutation
2fa_generation
2fa_bypass
lesson_self_ratification
self_score
```

## 19.6 Tool-call envelope

```yaml
run_id:
agent_id:
capability:
resource:
scope:
reason:
idempotency_key:
expires_at:
source_sha:
input_hash:
```

---

# 20. OBSERVABILITY, SLOS, AND FAILURE SEMANTICS

## 20.1 Core SLOs

| Service | SLO |
|---|---|
| Deterministic ticket validation | 99.9% completion; measured latency |
| Operator presentation | no mechanics without verified ticket |
| Sentinel research review | target completion within 5 min |
| Proposal review | decision or explicit timeout within 6 min default |
| Moomoo gateway heartbeat | 5-second check, configurable |
| Feature freshness | session-specific |
