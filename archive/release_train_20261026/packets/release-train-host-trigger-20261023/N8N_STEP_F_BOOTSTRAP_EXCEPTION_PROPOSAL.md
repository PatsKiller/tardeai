# Proposal: a §23.24 bootstrap exception for arming step F

**PROPOSAL ONLY.** Nothing here is in force. It grants nothing and changes no gate. It accepts no exception. It edits
neither AGENTS.md nor any `N8nFrameworkExceptions@v1` file. Accepting an exception is the operator's decision (§17,
§23.24 activation bar: "an exception the operator accepted in the PR").

- Task: `T-20261023-f5213b`.
- Plan: "Make the release train actually run", §1, last bullet.

## 1. The circularity

Arming step F imports and publishes `tradeai-fabric-release-train`. The mandatory import gate
(`scripts/check_n8n_import_ready.py`, which runs `check_n8n_workflow_framework.py --gate activation`) refuses it with
`framework_gate` (arming packet, step F). Three things are missing:

- **FW-P1 to FW-P6** platform elements are not PASS;
- **every runtime obligation is UNPROVEN.** The workflow has 18:
  - 23.24-M1a, M3b, M4b, M5b, M6b;
  - A1b, A3b;
  - L1, L3b, L4b, L5b;
  - R2b, R3b, R6b;
  - SEC1b, SEC2b, SEC5;
  - BAR;
- **exceptions are UNVERIFIED** ("authenticated host approval consumer unavailable").

Most of those runtime obligations can only be evidenced by runs *of the workflow*, for example:

- M1a: ledger runs joined to n8n execution `run_id`;
- L1: `requested_by = n8n:workflow:<id>`;
- M3b: p95 over saved executions;
- L5b: a drift receipt for the deployed copy.

Proving the workflow needs runs. Runs need the import, and the import needs the proof. No amount of waiting breaks
that loop.

## 2. What the host-timer runs can evidence, and what they cannot

The host trigger (this packet) runs **the same writer with the same argv** that the workflow's Run Lane calls:
`release_train_window_request.py --window <slot> --append --shadow-only`, which is the allowlist `live_arg`. It also
runs the same census. Its runs therefore produce real evidence about the **lane**, though not about the **workflow**.

| Obligation | Host-timer runs supply | Still needs the n8n workflow |
|---|---|---|
| M5b: stores written are all named | `LaneRunReceipt@v2` store list from every host-timer run, compared with the contract's `connects_to` | no |
| M6b: an empty success fails at the host | the writer's `no_op` receipts (`produced_count 0`, `empty_reason nothing_due`) on STOP-set windows | the RunReceipt verdict path through the executor |
| R6b: both schedulers respect the key | journal O_EXCL `duplicate` when a host timer and a forced tick hit one window | `effect_owners` row for the n8n fire |
| R3b: fallback executed | the host timer **is** the declared fallback; `rollback.sh` drill receipt | `CutoverReceipt@v1` rollback |
| M3b: p95 duration | p95 of the writer's run time from the lane receipts (`started_at` → `ok_at`) | p95 of n8n executions |
| M1a, L1, L3b, L5b, A1b, A3b, SEC1b, SEC2b, SEC5, M4b, R2b, L4b | — | yes: these are properties of n8n, the relay and the executor, not of the lane |
| BAR | — | the gate exit 0 itself |

## 3. The proposed exception (for the operator to accept, amend or refuse)

A **bootstrap exception**, scoped to exactly one workflow and one stage:

1. **Scope.** It covers `tradeai-fabric-release-train` only, and only promotion to **shadow**. Its request lanes
   carry `--shadow-only` in the reviewed allowlist argv (H.0). It never covers canary, cutover or a live request.
2. **Obligations excepted.** Only the runtime obligations marked "yes" in §2's last column. These are the ones that
   cannot exist before the first n8n run. Every static element still has to pass.
   - **Platform elements.** FW-P1 to FW-P6 are **not** excepted by this proposal. They are measured with
     `--probe-host`, or carried by their own operator exception.
3. **Substitute evidence required before the exception binds.**
   - At least **7 consecutive days** of host-timer runs for all four slots: 28 request receipts and 28 census
     receipts.
   - Each request has a journal file with a `-win` id and a claimer receipt (and a report, once #2033 is live).
   - The M5b, M6b, R6b, R3b and M3b rows of §2 are filled from those runs.
   - All of this is collected into `N8nFrameworkRuntimeEvidence@v2` rows labelled
     `source: host-timer (lane evidence, not workflow evidence)`.
4. **Expiry and conversion.**
   - The exception expires **14 days after publish**, or at the first of: any promotion beyond shadow, or a gate run
     showing an excepted obligation FAIL.
   - Within those 14 days, the workflow's own runs must turn every excepted obligation into EVIDENCED, or the workflow
     is unpublished. It is archived and never deleted (§0 rule 6), and the host timers keep the train ticking.
5. **No double train.**
   - While both schedulers can fire, the journal's one-id-per-window rule (O_EXCL) is the effect key. The second
     request is a `duplicate`.
   - After conversion, the operator disables the host timers with `rollback.sh --apply`.
6. **Recording.**
   - The operator accepts the exception in the step-F PR, as the §23.24 activation bar requires, with an
     `N8nFrameworkExceptions@v1` entry naming the workflow id, the excepted obligation ids, the expiry and this
     document.
   - The "authenticated host approval consumer unavailable" condition still has to be resolved for the gate to read
     that entry. It is a separate operator item and is not solved here.

## 4. What this proposal does not do

- It changes no gate code, no `--gate activation` behaviour and no allowlist. It writes no exceptions file.
- It does not route around the import gate (§0 rule 3). Step F stays refused until the operator acts.
- It is not needed for tonight. The host timers make the train tick without n8n.
