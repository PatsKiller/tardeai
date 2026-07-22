- daily loss, gross notional, concurrent position, or trade-count limit is exhausted.

No additional 2FA is required for an add that remains inside the signed session envelope.

## 16H.3 Cancel one

`CANCEL` applies to the selected working order only.

The adapter returns a terminal or pending cancellation state, and the position/order projection remains conservative until the broker confirms.

## 16H.4 Cancel-all controls

The default control is:

```text
CANCEL ALL ENTRIES
```

It cancels:

- unfilled entries;
- add orders;
- unfilled fallback attempts;

while preserving:

- broker-native stops;
- protective children;
- approved exit orders unless explicitly selected.

Additional scopes:

```text
CANCEL SYMBOL NON-PROTECTIVE
CANCEL SESSION NON-PROTECTIVE
CANCEL ACCOUNT ALL WORKING
```

`CANCEL ACCOUNT ALL WORKING` requires a stronger confirmation because native broker cancel-all operations may include unrelated or protective orders. If protection is cancelled, the system immediately re-protects or moves to flatten according to policy.

## 16H.5 Flatten

`FLATTEN` means:

> Cancel unsafe conflicting orders, close the complete current position for the selected symbol and accounts, and verify zero.

It prioritizes flatness over price optimization.

Broker translation:

```text
Alpaca:
  native close-position or close-all endpoint when capability verified
  reconcile every multi-status child

Moomoo:
  cancel conflicting working orders
  refresh position direction and quantity
  submit opposite-side close order
  use RTH market only when supported and policy permits
  use marketable limit during limit-only sessions
  reconcile zero

Schwab:
  cancel conflicting working orders
  refresh position
  submit opposite-side close order
  use RTH market only when supported and policy permits
  otherwise governed marketable-limit
  reconcile zero
```

If a broker rejects the close, the engine:

- preserves any existing protection;
- retries only through a separately authorized fallback close method;
- escalates visually and through notifications;
- never reports flat until the broker and local reconciliation agree.

## 16H.6 Intelligent sell

`SELL SMART` seeks better exit quality within a bounded deadline.

Modes:

```text
SELL_25_PERCENT
SELL_50_PERCENT
SELL_CUSTOM
SELL_ALL_SMART
```

It uses:

- bid/ask and spread;
- microprice;
- depth;
- OFI;
- tape aggression;
- replenishment;
- current RES/RRS;
- urgency;
- maximum exit duration;
- broker rate limits.

Exit ladder:

```text
PASSIVE OFFER or join
→ improve one tick
→ midpoint/inside-spread limit
→ marketable limit
→ RTH market order when authorized and supported
```

`SELL SMART` converts to flatten behavior immediately when:

- hard stop or kill switch;
- RRS critical;
- data becomes unsafe;
- exit deadline expires;
- session close rule;
- protection failure;
- operator selects FLATTEN.

## 16H.7 Action confirmations

The following require confirmation:

- quick add;
- cancel-all broader than symbol entries;
- flatten;
- smart sell custom quantity;
- broker failover when policy is prompt-only;
- session amendment.

The confirmation is not another 2FA when the action remains inside the active session envelope.

---

# 16I. FEATURE CONTROL AND TEST MODAL

## 16I.1 Purpose

Every new Active Trader capability is independently testable without altering the current `/v3` experience.

## 16I.2 Modes

```text
OFF
READ_ONLY
SHADOW
SIMULATION
LIVE_CANARY
```

## 16I.3 Feature controls

The modal governs:

```text
active_trader_next
broker_alpaca
broker_moomoo
broker_schwab
multi_account
broker_failover
session_builder
session_2fa
smart_entry
quick_add
cancel_one
cancel_all
flatten
smart_sell
resilience_resistance
runner
overnight_conversion
journal_replay
drive_sync
operator_email
```

Flags can be scoped by:

- environment;
- operator;
- broker;
- account;
- symbol;
- session;
- expiration.

## 16I.4 Authority

Feature flags:

- cannot create session authorization;
- cannot enlarge a signed envelope;
- cannot bypass broker capability;
- cannot enable live trading without the live-canary flag and a valid session;
- are stored server-side;
- are versioned and audited;
- have an immediate rollback value.

The UI modal displays old value, new value, scope, reason, expiry, and affected services before saving.

## 16I.5 Existing live system

Implementation rules:

- `/v3` remains available;
- current API behavior remains unchanged;
- current services are not replaced;
- new schemas are additive;
- live flags default off;
- new broker writes remain unreachable until the approved canary stage;
- production deployment is separate from code completion;
- every stage includes old-dashboard regression tests.

---

# 16J. READ-ONLY ARCHITECT LITMUS REVIEW

## 16J.1 Reviewer boundary

A second architect receives:

- architecture;
- staged implementation program;
- repository map;
- schema diff;
- capability matrix;
- test results;
- security model;
- closeout artifacts.

The reviewer has read-only repository, Drive, and artifact access.

The reviewer cannot:

- edit files;
- write comments that trigger automation;
- create commits or branches;
- merge;
- deploy;
- change flags;
- change architecture;
- request credentials;
- call brokers.

## 16J.2 Review questions

The litmus review assesses:

- determinism and authority;
- account and broker correctness;
- rejection/failover safety;
- session-bound quantity semantics;
- flatten/cancel protection;
- rate limits;
- idempotency;
- partial fills;
- P&L reconciliation;
- journal completeness;
- dashboard isolation;
- credential handling;
- unattended-run recoverability;
- test coverage;
- rollback.

## 16J.3 Output

```yaml
review_id:
architecture_version:
implementation_sha:
reviewer:
verdict: PASS|CONDITIONAL_PASS|FAIL
blocking_findings: []
nonblocking_findings: []
questions: []
evidence_refs: []
review_hash:
completed_at:
```

The reviewer writes one report artifact only.

A `FAIL` or unresolved blocking finding pauses the implementation program for architecture-owner review. It does not cause automated edits.

---

# 16K. AUTONOMOUS CODEX NIGHT-RUN, DOCUMENTATION, AND OPERATOR HANDOFF

## 16K.1 Purpose

The non-live implementation program is designed to run sequentially overnight with deterministic stop conditions.

It is not an autonomous production deployment.

## 16K.2 Branch policy

```text
branch: feat/active-trader-next
base: verified current main SHA
one commit per completed stage
push after each green stage
no automatic merge to main
create or update one draft PR
```

## 16K.3 Stage transaction

For each stage:

```text
load checkpoint
→ verify clean owned scope
→ read architecture and stage contract
→ plan
→ implement
→ test
→ create closeout
→ run read-only security checks
→ commit
→ push
→ sync stage artifacts to Drive
→ verify local/GitHub/Drive hashes
→ update checkpoint
→ continue only if green
```

On failure:

```text
stop
→ preserve worktree and logs
→ write failure closeout
→ commit diagnostic artifacts when safe
→ push checkpoint branch
→ sync available evidence to Drive
→ email operator
→ do not start next stage
```

## 16K.4 Checkpoint

```yaml
run_id:
architecture_version:
program_version:
base_sha:
branch:
current_stage:
state:
last_green_stage:
stage_commits: []
drive_artifacts: []
pending_operator_actions: []
test_summary:
failure:
updated_at:
```

## 16K.5 GitHub artifacts

Each stage produces:

```text
docs/implementation/active-trader/<run_id>/stage-XX-plan.md
docs/implementation/active-trader/<run_id>/stage-XX-closeout.md
docs/implementation/active-trader/<run_id>/stage-XX-tests.json
docs/implementation/active-trader/<run_id>/stage-XX-changes.txt
docs/implementation/active-trader/<run_id>/stage-XX-drive-manifest.json
```

The stage commit contains code and its own evidence.

## 16K.6 Google Drive synchronization

Canonical Drive destination:

```text
Trade_AI_Docs_v2/
  implementation/
    active-trader/
      <run_id>/
        stage-00/
        stage-01/
        ...
        final/
```

Requirements:

- idempotent create/update;
- Drive file ID manifest;
- SHA-256 verification;
- resumable upload for larger artifacts;
- no duplicate artifact names for retries;
- no source secret files;
- stage sync before advancing;
- final full-run sync.

Google Drive failure pauses the run when `drive_sync_required=true`.

## 16K.7 Final sync

At terminal completion:

1. enumerate all run commits;
2. enumerate all changed files;
3. generate final architecture-compliance report;
4. generate test and build report;
5. generate credential requirements;
6. generate operator to-do list;
7. generate rollback plan;
8. upload final artifacts to Drive;
9. verify Drive hashes;
10. update the draft PR;
11. send the completion email.

## 16K.8 Operator email

Use the Gmail API `messages.send` route with the minimum approved send scope.

Required configuration:

```text
OPERATOR_NOTIFICATION_EMAIL
GMAIL_NOTIFICATION_CREDENTIAL_SLOT
