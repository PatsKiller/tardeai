# AGENTS.md 1.3.0 — authority amendment (PROPOSED, not in force)

```
Amends:          AGENTS.md 1.2.7
Proposed-Version: 1.3.0
Change-Class:    MAJOR (changes §0, §1, §2B and §17 — broker authority semantics)
Status:          PROPOSED — Effective-Date PENDING
Requires:        operator ratification bound to this PR's reviewed head SHA
                 (APPROVE_AGENTS_POLICY_1_3_0 <pr> <sha>) AND merge
Base-SHA:        1c60ecb4264ba4dcc6a38106e76fae0d96a26787
Operator-Direction-Recorded: 2026-09-25 (operator confirmed in session: "Yes, mine, draft it")
```

**Until ratified, the ACTIVE text of AGENTS.md governs unchanged.** Nothing in this file
authorizes any agent to modify, test against, or call the broker execution subsystem today.
§0 rule 2 still reads as it did. This document holds the replacement text and the reasons, so
the ratification is a review of one diff, not a rewrite.

Why this exists: the review of 2026-09-25 (finding 5) measured a direct contradiction between
AGENTS.md §0/§1 ("the broker execution subsystem is out of scope") and architecture v3.3 §1.2–§1.4,
which specifies a staged, operator-authorized live Active Trader and a controlled live canary;
and between the implementation program v1.1 ("push after every stage") and AI_WORK_POLICY.md §3–§4
(one push per tranche). A blueprint is not a grant, so the safe reading has been "propose only".
This amendment resolves the conflict explicitly, in the operator's words, instead of leaving each
agent to guess.

---

## 1. The operator's policy direction (recorded, not paraphrased into more)

> Agents may build and operate an authorized trading system. Live momentum scalp orders may be
> placed and managed automatically by the deterministic execution path only within an active,
> operator-approved, 2FA-verified, signed session envelope defined in architecture v3.3. Other
> live orders retain the applicable per-order or immutable composite-order authorization. An LLM
> cannot originate an order or bypass the execution path. The operator's approval of this policy
> direction is not a live-session grant or permission to run the live canary.

## 2. Authority hierarchy

Highest first. A lower document can narrow a higher one; it can never widen it.

| rank | source | governs | cannot |
|---|---|---|---|
| 1 | **A specific operator grant or instruction**, recorded (guard ledger, `APPROVE_*` token, or a session-signed envelope) | one bounded action: named scope, resource, SHA/session, expiry, uses | override the §0 floor without an AGENTS.md amendment; extend beyond its recorded scope |
| 2 | **AGENTS.md (ACTIVE version)** | agent behaviour, authority rails, operator-only list | be widened by any document below it |
| 3 | **AI_WORK_POLICY.md** | remote sync, push budget, CI cost, deployment boundary (canonical for those domains) | grant financial, broker, 2FA or deploy authority (its §20/§27) |
| 4 | **Architecture v3.3** | what the system must be and the invariants the build must satisfy | act as a grant; "the architecture allows X" is never authorization to do X |
| 5 | **Implementation program** (`docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_2.md`) | stage order, deliverables, checkpoints | override ranks 2–4; its push, Drive and mail steps run only as ranks 1–3 allow |
| 6 | Tool adapters (`CLAUDE.md`, `.cursor/rules/`, `.github/copilot-instructions.md`) | pointers only | contain rules |

**Push authorization and guard grants (recorded as they are, measured 2026-09-25).**
`AI_WORK_POLICY.md` §16 authorizes a push with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` **plus explicit
operator intent**; it never mentions `bin/guard`. The pre-push hook (`.githooks/pre-push`) *also*
treats **any** active guard `git-push` grant as push authorization **and** a push-budget override
(`scripts/lib/guard_push_auth.py`), whatever branch the grant was issued for. The recorded
relationship under 1.3.0:

- A guard `git-push` grant is one form of recorded operator intent (rank 1). It counts for a push
  **only when its reason names the branch or head SHA being pushed**.
- This PR adds that check. By default it only warns, so sessions aren't broken mid-flight;
  `TRADEAI_GUARD_PUSH_SCOPE_ENFORCE=1` makes it refuse. Making refusal the default is an operator
  decision.
- A push grant never authorizes merge, deploy, configuration, secret access or broker action
  (AI_WORK_POLICY §27).
- **Merge is not a separately enforced grant today:** `main` requires 0 approving reviews and
  code-owner review is off (`agent-governance` + `cio-hardening` are required and `enforce_admins`
  is on since 2026-09-25). See
  `REPOSITORY_PROTECTION_ADMIN_ACTIONS.md` for the administrator actions that would make it one.

**`bin/guard` is not an enforcement boundary for every agent.** Its hooks are wired for Cursor only
(`.cursor/hooks.json`). For Claude Code, whose sessions have no repository hooks, guard is
**advisory**. Under Cursor, `promote` classifies as `none` and `gh pr merge` is not classified at
all. So the requirement for anything consequential is **enforcement at the resource that mutates**.
For broker mutations that is exactly what `TradingSessionGrant@v1` verification provides; for
merge it is branch protection; for deploy it is the release script's own grant check.

**Conflict rule (unchanged):** where two sources at different ranks conflict, the higher rank wins;
where they are at the same rank or the conflict is ambiguous, the safer or more restrictive reading
wins, and the conflict is reported.

## 3. Five distinct authorities

Each is granted separately. Holding one implies none of the others.

| authority | what it permits | who may hold it | how it is granted |
|---|---|---|---|
| **A1 Coding** | edit, and unit/contract/replay-test, broker-adjacent code (adapters, contracts, the grant verifier, fixtures, simulators) in a registered worktree | `EXECUTION_ENGINEERING_AGENT` | ratification of this amendment + a declared file set; mocks, fixtures and replay only |
| **A2 Simulation** | run the execution path against the simulated broker (`SIM_BROKER`) and shadow modes | `EXECUTION_ENGINEERING_AGENT`, the deterministic path | A1 + no live credential or endpoint reachable (proved by test) |
| **A3 Deployment** | promote a reviewed SHA to the served release | `RELEASE_COORDINATOR` | an operator grant bound to the exact SHA (AI_WORK_POLICY §21, §27) |
| **A4 Live activation** | switch live-trading flags or start a live session | the operator only | operator ceremony; for Stage 14 the separate start instruction in §5 |
| **A5 Broker order authority** | a real order reaches a broker | the deterministic execution path only, inside a valid `TradingSessionGrant@v1` (scalp) or a per-order / immutable composite-order 2FA authorization (everything else) | operator 2FA; verified at the broker mutation boundary by `scripts/lib/trading_session_grant.py` |

An LLM agent may hold A1, A2 and (as coordinator) A3. **No LLM agent ever holds A4 or A5**, and no
code path may let an LLM originate, route, resize or bypass an order.

### Reading broker code (the "investigate" word in §0 rule 2)

The ACTIVE §0 rule 2 forbids agents to "investigate" the broker execution subsystem. Read
literally, that bars even reading its source. This amendment resolves it:

- **Under 1.3.0: read-only inspection** of broker code is part of A1. That means reading source,
  `grep`, and `file:line` citation, with no execution, no import into a running process, and no
  credential or endpoint access.
- **Until ratification:** read-only inspection happens only when an explicit operator instruction
  requires it for a governance or review task, and the output is limited to `file:line`
  inventories. This PR's enforcement-point table (`TRADING_SESSION_GRANT_CONTRACT.md` §3) and the
  architecture map's broker entry points were produced that way. They were read-only, with no
  broker file edited or executed, under the operator's 2026-09-25 instruction to "verify
  authorization at the broker mutation boundary". The reviewer should confirm that reading of the
  instruction.

## 4. What changes in AGENTS.md on ratification

The ratifying PATCH swaps in exactly this text. It is stored here, not in AGENTS.md, so the
unratified wording cannot be read as a rule.

**§0 rule 1 (unchanged).** The behaviour rail stays word for word: the *agent* never sizes,
orders, stops, weights, or writes to a broker. Authorized live orders come from the deterministic
execution path under A5, never from an agent.

**§0 rule 2 — replace with:**
> **Broker code is buildable; broker authority is not.** Engineering agents may implement and test
> broker-adjacent code only under Coding/Simulation authority (A1/A2): mocks, fixtures, simulated
> broker, replay. No agent calls a live broker, reads a live credential, sets a live flag, or
> requests 2FA. Real orders come only from the deterministic execution path inside a verified
> session grant or per-order authorization. See `docs/governance/agent-standards/AUTHORITY_AMENDMENT_1_3_0.md`.

**§1 "What the agent never touches" — replace the Broker execution bullet with:**
> - **Live broker authority.** Live credentials, live endpoints, 2FA, live flags, live sessions and
>   real orders. Broker-*adjacent code* is in scope under A1/A2; broker *authority* never is.

**§2B `EXECUTION_ENGINEERING_AGENT` — replace the BLOCKED line with:**
> `-> GRANTED by 1.3.0 for A1/A2 within a declared file set; live authority (A4/A5) never`

and the paragraph "`EXECUTION_ENGINEERING_AGENT` is defined but not granted" with:
> **`EXECUTION_ENGINEERING_AGENT` is granted A1/A2 only.** The declared file set is
> `scripts/active_trader/**`, `scripts/brokers/**`, `scripts/lib/trading_session_grant.py`,
> broker adapter modules and their tests. Every change in that set must keep a test proving that
> no live credential or endpoint is reachable from the test process.

**§17 — replace "anything in the broker subsystem, credentials, or 2FA" with:**
> live broker authority (A4/A5): live flags, live sessions, 2FA, credentials, the Stage 14 canary,
> and any change to `DETERMINISTIC_ENTRY_POINTS`, session-grant limits or the grant contract

**§0 adapters.** `CLAUDE.md`, `.cursor/rules/` and `.github/copilot-instructions.md` repeat §0
verbatim; the ratifying PATCH updates all of them in the same commit.

## 5. The controlled live canary keeps its own start

Ratifying 1.3.0 authorizes building and simulating. It does **not** start Stage 14. The live
canary requires a separate operator instruction, issued after review, tied to all of:

1. the exact reviewed SHA;
2. the selected broker and accounts;
3. the risk envelope — every `OPERATOR_DECISION_REQUIRED` limit in
   `TRADING_SESSION_GRANT_CONTRACT.md` set by the operator;
4. readiness evidence (the v3.3 §7 / Stage 13 proofs, observed on the served release);
5. operator presence for the session.

## 6. Stage checkpoints versus the push budget (finding 5)

**AI_WORK_POLICY.md wins (rank 3 over rank 5).** Recorded precedence:

- A stage checkpoint is a **local commit** plus the stage artifacts (`stage-XX-*.md/json`). It is
  not a push.
- The unattended run is **one tranche**: one push at the end (the draft PR), a second only for a
  CI failure local acceptance could not catch, a third only with operator approval.
- Drive sync of stage artifacts happens **after** the tranche push, once, with byte-hash readback.
- The preflight "GitHub push test" becomes a **read-only reachability check** (`git ls-remote`).
- Operator notification uses the existing operator chokepoint; sending email needs an operator-granted
  mail scope. Neither step may push, deploy or widen any authority.

The dependent instructions were updated in `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_2.md`
(v1.1 is marked superseded; nothing deleted).

## 7. What ratification requires

- Independent review of this PR by someone other than its author (AGENTS.md §11; the author cannot
  satisfy it).
- `APPROVE_AGENTS_POLICY_1_3_0 <pr> <sha>` from the operator, bound to the reviewed head.
- The ratifying PATCH: swap the §4 text in, update the adapters, set `Status: ACTIVE` and a real
  `Effective-Date`, and add the version-history row.
