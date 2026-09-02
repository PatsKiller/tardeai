Status:      ACTIVE
as_of:       2026-09-01T21:28:07-04:00
run_id:      mp-20260901-210554
Measured at: origin/main 6d6609915 · CURRENT 6d6609915 (BUILD_SHA file content) · $PROJ 0a591048b
Canonical repo path: docs/implementation/maturity-program/mp-20260901-210554/STAGE_01_AGENTS_POLICY_RECONCILIATION.md
Authority:   Stage 1 reconciliation. AGENTS.md 1.0.0 is PROPOSED, not ACTIVE.

# Stage 1 · Constitutional cleanup and conflict matrix

## What changed in AGENTS.md

| change | class | evidence |
|---|---|---|
| document-control block (10 keys) + `Document version policy` | MINOR | `Policy-Version:` was **0** before; now 1 |
| §13.5 duplicate merged, unique obligations folded in | PATCH | headings 2 → 1 |
| §13.6 **numbering collision** renumbered to §13.7 | PATCH | see correction below |
| §13.4–13.7 restored to ascending order | PATCH | was 13.4→13.6→13.5→13.7 |
| two "Where things go" tables merged | PATCH | headings 2 → 1, no unique row lost |
| **§2B role authority profiles** | **MAJOR** | new authority semantics |
| version history table | MINOR | current row == `Policy-Version` |

**Net class MAJOR**, set by §2B. The version policy requires the higher class when a change could
be read either way.

### Correction to the program's own premise

The brief instructed: *"Merge the duplicate §13.6 sections into one."* **They are not duplicates.**

```
line 1008  ## 13.6 · Operator surface data producers      (Finviz auth, screener vs enrichment)
line 1107  #  13.6 · Conformance checklist                 (pre-build checklist)
```

Two distinct sections that collided on one number. **Merging would have destroyed content.**
Resolved by renumbering the later one into §13.7, which was free — a peer's
`CIO_AFTERNOON_FIVE_2026-09-01.md` had already established that §13.7 did not exist. §13.5 *was*
a genuine duplicate and was merged.

Removing the §13.5 stub then exposed a second defect the brief did not name: the survivors ran
13.4 → 13.6 → 13.5 → 13.7. Reordered, and a test now pins ascending order.

## Conflict matrix

| # | conflict | controlling rule | required amendment | approver | blocks work? |
|---|---|---|---|---|---|
| 1 | **AGENTS.md vs architecture v3.3 broker stages.** v3.3 line 310 says `LIVE_TRADE` and a momentum-scalp live canary are "architecture-owner approved" after P11; ADR-008 (line 5010) marks it ACCEPTED. AGENTS.md §0.2 says the broker subsystem is out of scope entirely. | **AGENTS.md** — safer/more restrictive wins | §2B defines `EXECUTION_ENGINEERING_AGENT` but explicitly does **not** grant it. v3.3 needs a note that architecture-owner approval ≠ agent authority. | operator | **YES** — blocks Stage 7 |
| 2 | **local commit vs branch push.** AI_WORK_POLICY §2 makes commit the checkpoint; §3 caps pushes at 2/tranche; §16 requires explicit intent. | AI_WORK_POLICY (hook-enforced) | none — AGENTS.md already references rather than restates it | — | no |
| 3 | **Drive sync vs egress.** §2A: credentials, account numbers, PII, `.env` contents "never leave this box". Stage 1.6 requires a Drive mirror of AGENTS.md. | both — they do not actually conflict | AGENTS.md is policy text with no secrets; the merged "Where things go" now names the mirror as the **one governed exception**, content-hash verified | operator ratifies with 1.0.0 | no |
| 4 | **Bitwarden vs no credential-store access.** AGENTS.md:1402 says a key "is regenerated from Bitwarden Secrets Manager"; §0 forbids credential/secret access. `scripts/gog_broker.sh` exists. | §0 — no agent reads the store | AGENTS.md:1402 is descriptive (how the operator restores it), not a grant. Recommend an explicit "operator does this, not the agent" clause. | operator | no |
| 5 | **$0.25 vs $0.50 daily cap.** Runtime enforces **0.50** — `LLM_GLOBAL_DAILY_USD_CAP=0.50` in 5 `lane_registry.json` cron lines and `gate_d_bundle_2_advisory_canary.py:15`. `llm_process_registry.json` notes date the move: *"2026-08-11 … under global 0.25"* → *"2026-08-12 … under global 0.50"*. **AGENTS.md documents neither number.** | **RESOLVED 2026-09-01 — operator ratified $0.50** | the change **is** attributed in config notes, but nothing evidences *operator* approval vs an agent recording its own change. Add the ruling cap to AGENTS.md §12 with its approval reference. | operator | **Stage 5 only** — the MVL budget gate cannot be enforced against an unratified cap |
| 6 | **advisory agents vs deterministic execution services.** v3.3 line 714 has a "Deterministic broker adapter"; line 1971 M7 a session-scoped 2FA canary. | AGENTS.md §2B | `LIVE_CANARY_CONTROLLER` is defined as *"a deterministic service, never an LLM agent"* — this is the reconciliation, and it is now testable | operator (§2B is MAJOR) | no |
| 7 | **4.3/10 maturity vs M1–M5 gates.** `ARCHITECTURE_v3_0.md:271` and `v2_0.md:68` state ~4.3/10. AGENTS.md §15: *"maturity is not scored as a percentage here."* | **AGENTS.md §15** | the 4.3/10 figures are historical (v2.0/v3.0 docs) and are superseded for gating purposes; no edit to those archives required | — | no |

## Blocking summary

- **#1 blocks Stage 7** (Active Trader / broker-facing agents remain BLOCKED).
- **#5 blocks the Stage 5 budget gate** until the operator ratifies 0.25 or 0.50.
- Nothing blocks Stages 2–4.

## Verification

```
tests/test_agents_policy_v1.py                    43 passed
12 mutations, each reverted, AGENTS.md byte-identical after each:
  5 authority denials removed                     -> red (one each)
  fail-open to the widest role                    -> red
  claim a prior 1.x that never existed            -> red
  Policy-Version drifts from the history row      -> red
  re-introduce the 13.6 collision                 -> red
  role authority made self-amendable              -> red
  drop the secrets-never-sync rule                -> red  (SURVIVED first pass — see below)
  Effective-Date set while Status PROPOSED        -> red  (SURVIVED first pass — see below)
tests/test_ai_work_policy_hooks.py                10 passed
check_line_endings --range origin/main...HEAD     churn: none
```

### Two mutations survived the first pass

**Dropping "Never sync `.env`, keys, or credentials" turned nothing red.** The merge-preservation
test checked the neighbouring fragment `check_no_secrets.py`, so deleting the prohibition while
leaving the enforcement mention passed. **Presence of a neighbour is not presence of the rule.**
The test now asserts the prohibition text itself, whitespace-normalized.

**A `PROPOSED` policy could carry a concrete `Effective-Date`**, asserting it was already in
force while awaiting approval. No rule coupled them. Both the rule and its test were added —
§9.1, an absent approval must never render as an affirmative one.

## Not this change

Pre-existing and **not caused here**, reproduced on clean `origin/main` with 0 dirty:
`test_agent_flash_governance.py` and three sibling governance suites — **7 failed, 69 passed**.
They sit outside the only required check (`cio-hardening`), so they go red and block nothing (§8).

`$PROJ` remains at `0a591048b`, 20 behind `origin/main`. Two fast-forward attempts were made
under operator approval; the first aborted correctly when a cron started inside the
check-to-checkout gap. Stage 1 was executed from a worktree off `origin/main`, so the drift does
not affect this content.


---

## Conflict #5 — resolved, with a caveat that matters more than the number

The operator ratified **$0.50** on 2026-09-01. AGENTS.md 1.1.0 §12 now records it with its
approval reference.

**Ratifying the value did not make it an enforced control.** Measured on `origin/main`:

```
crontab lines SETTING LLM_GLOBAL_DAILY_USD_CAP=0.50 :  6
active crontab lines invoking an LLM-spending script: 84
per-process daily_cost_cap_usd values               : 11 caps summing to $11.45/day
gate_d_bundle_2_advisory_canary.py:367  "LLM_GLOBAL_DAILY_USD_CAP not set.
                                         Will default to bridge's internal cap."
```

So ~78 of 84 LLM lanes run with the global cap unset. **$0.50 is the ruling policy ceiling; it
is not a guarantee that daily spend cannot exceed it.** §12 states this explicitly rather than
implying enforcement the runtime does not provide.

**Consequence for Stage 5.** The MVL budget gate can enforce $0.50 for the four-agent cohort by
setting the variable on those lanes specifically. It cannot claim a box-wide $0.50 ceiling until
the gap is closed — either by setting the variable on every LLM lane, or by moving the check into
the shared transport so it cannot be omitted. Named debt.
