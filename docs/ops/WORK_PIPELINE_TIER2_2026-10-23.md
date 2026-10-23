# Work pipeline Tier 2: passkey acts through the host applier (2026-10-23)

```
Status:      ACTIVE in code for approve_design and contract_reviewed; merge_pr, release_now and approve_item are built
             and OFF (config/ops_controls.json work_pipeline.*) until the AGENTS.md clauses below are ratified
as_of:       2026-10-23T14:20:00-04:00
Measured at: origin/main 98bef2794 + PR #2021 (Work pipeline Tier 1); hermetic tests only, no live-server traffic
```

Operator, 2026-10-23, on the Work pipeline mockup: "the HTML looks great. But nothing is actionable on there", then
approved both action tiers ("both"). Tier 1 (one click, coordination store only) is PR #2021
(`docs/ops/WORK_PIPELINE_2026-10-23.md`). This is Tier 2.

## How a Tier 2 act works

Every Tier 2 act is one **Ops → Controls change request** of a kind `pipeline.*` (`scripts/lib/ops_controls_core.py`
`KINDS`, logic in `scripts/lib/work_pipeline_tier2.py`). It therefore gets the whole Ops Controls surface (AGENTS.md
§27.2–§27.3):

1. The card button opens a dialog. For an approval it asks for the operator's own words.
2. **Preview** creates the request (`POST /api/v2/ops/controls/requests`): only the operator's tailnet identity on
   serve_proxy is accepted (agents, n8n and the service token get `AGENT_CALLER_REFUSED`), CSRF is checked, and the
   server computes the preview and the exact phrase, e.g. `APPROVE DESIGN DSN-20261022-data-domains 2026-10-23`.
3. **Confirm with passkey**: a fresh WebAuthn assertion (user verification required, bound to that request), sent
   with the typed phrase. The sudo window (PR 1970) is not merged, so every act needs its own assertion.
4. **Approve**: the request is HMAC-signed and handed to the one host applier (`tradeai-ops-applier.service`,
   `scripts/ops/operator_controls_applier.py`), which re-plans, refuses on drift, applies, verifies and records the
   result. Command Center never holds GitHub or deploy credentials and never executes these acts itself.

| Kind | Flag (`config/ops_controls.json` `work_pipeline`) | Default | What the applier does |
|---|---|---|---|
| `pipeline.approve_design` | `approve_design_enabled` | **on** | Appends `DesignApproval@v1` (id, the operator's words, actor, time, request id, factor) to `<claims_dir>/designs/approvals.jsonl`. Works for a design (`DSN-…`), a phase (`DSN-…-P<n>`) or a packet (`docs/ops/packets/<id>`). |
| `pipeline.contract_reviewed` | `contract_reviewed_enabled` | **on** | Appends `ContractReview@v1` to `<claims_dir>/contracts/reviews.jsonl` for a lane whose `config/n8n_health_contracts.json` contract is `DRAFT` (§23.19). |
| `pipeline.approve_item` | `approve_item_enabled` | off | `APPROVE` items of an approval package in the hash-chained `approval_packages.jsonl` (decided_by = the operator, passkey). |
| `pipeline.merge_pr` | `merge_pr_enabled` | off | With the operator's `gh` on the host, re-reads the PR. It refuses unless the head SHA still matches and every required check of the base branch is exactly `success` (not skipped, not neutral). Then it runs `gh pr merge <n> --merge --match-head-commit <sha>` and verifies the PR merged. |
| `pipeline.release_now` | `release_now_enabled` | off | Refuses without an active `release-write` guard grant. Then it runs `scripts/cio_phase2_exact_main_deploy.sh prepare` and `promote`. Undo: `… rollback`. |

A kind whose flag is off is refused `FEATURE_OFF` before any request exists. The card shows it disabled, with the
reason in its tooltip.

## Why approvals go to a ledger, not straight into the design file

Command Center and the applier hold no git push credentials. A commit to main from the applier would also bypass
review and the push policy (AI_WORK_POLICY.md). So the approval goes to the coordination ledger at once, carrying the
passkey assertion. The Work board and the Work pipeline read it immediately
(`design_registry.apply_ledger_approvals`): the design reads `APPROVED` with `file_pending: true` and drops off
"awaiting approval". The next agent that touches the design commits `status: APPROVED` with the operator's words and
the ledger reference. DRAFT → REVIEWED health contracts work the same way.

## Never on the board

Broker orders, stops, kill-switch clearing and issuing grants. `approve_item` stays off for this reason: an APPROVED
package lets the approval poller mint the guard grants it binds.

## AGENTS.md amendment needed (operator package proposal)

Before `merge_pr`, `release_now` and `approve_item` are switched on, and to remove doubt about the two kinds that are
on. Class: MINOR (it adds an operator surface for acts the operator already owns and grants agents nothing).
Proposed text for §27.2:

> - **The Work pipeline's Tier 2 acts are Controls acts (20.2.0).** From Ops → Coordination → Work pipeline the
>   operator may, each time with a fresh passkey assertion and the typed phrase, through the one host applier:
>   approve a design, phase or packet, and mark a DRAFT n8n health contract reviewed. Each is an append-only record in
>   the coordination store (`designs/approvals.jsonl`, `contracts/reviews.jsonl`) carrying the operator's words and
>   the assertion. Such a record **is** the operator's approval in their own words for §28.3b and §23.19, and is not
>   a relayed approval under §28.4. An agent that carries it into the design or contract file cites the record.
>   The operator may also merge a PR whose required checks are all exactly `success` at the head the operator saw
>   (`--match-head-commit`), and run the exact-main release (prepare + promote) under an active `release-write`
>   grant. Approving an approval package that binds a guard grant is issuing a grant (§17) and stays at the host
>   terminal or Telegram until a later version says otherwise. Agents never call these endpoints (§27.2).
>   *Cause (§20): operator 2026-10-23, "nothing is actionable on there" and "both".*

Once that clause is ACTIVE, flip `merge_pr_enabled` and `release_now_enabled` in a reviewed PR. Leave
`approve_item_enabled` off unless the clause covers grant-binding packages.

## Files

- `scripts/lib/work_pipeline_tier2.py`: kinds, flags, plan (read-only, no GitHub) and apply (applier only)
- `scripts/lib/ops_controls_core.py`: the five `pipeline.*` KindSpecs; phrase, plan and apply delegate to the module
- `config/ops_controls.json`: the `work_pipeline` flags
- `scripts/lib/design_registry.py`: ledger overlay (`apply_ledger_approvals`); approved packets leave "awaiting"
- `scripts/lib/work_pipeline.py`:
  - per-card `actions.tier2` (approve a design, packet or package; merge on an operator merge step; contract
    reviewed when a DRAFT lane id is in the PR title);
  - view-level `tier2.release` (origin/main SHA from the census, merged items waiting);
  - open approval packages as proposed items.
- UI: `WorkPipelinePanel.tsx` (`Tier2Button` dialog; "Release now" beside the strip),
  `src/lib/workPipelineTier2.ts` (+ test in `npm run build`)
- Tests: `tests/test_work_pipeline_tier2_20261023.py` (gate `work_pipeline_tier2_20261023`),
  `e2e/work-pipeline-tier2.spec.ts` (stubbed authenticator, mocked routes; in `cc-surface-agreement-ci`)
