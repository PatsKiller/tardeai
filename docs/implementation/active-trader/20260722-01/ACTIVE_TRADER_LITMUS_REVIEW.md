# Active Trader Architect Litmus Review — Stage 0

**Run ID:** 20260722-01 · Reviewer report reproduced VERBATIM below. The reviewer ran as a
tool-restricted read-only agent (no Write/Edit/file-mutation/external-service tools available —
structural write denial). Controller attestation follows the report.

---

```yaml
review_id: ATN-LITMUS-STAGE0-2026-07-22-01
architecture_version: v3.3
implementation_sha: 87c2fa09fa95a8a69233959b04b1144e1297b923
reviewer: independent-architect-explore-agent
access_mode_verified: READ_ONLY
write_attempted: false
verdict: CONDITIONAL_PASS

blocking_findings:
  - id: BF-1
    dimension: 9-broker-specific-flatten-correctness / 25-unresolved-operational-risk
    title: Approved live-canary broker (Moomoo) is never shown to satisfy the mandatory broker-native protection precondition
    detail: >
      §16.8 and ADR-015 make broker-resident (server-side, disconnect-surviving) protection a
      hard precondition — "Where broker-native or equivalent independently survivable protection
      is unavailable, live scalp trading remains disabled for that account even when the session
      is authorized." Yet P14 and ADR-008 designate Moomoo momentum-scalp as THE approved live
      canary, and §16F.4 / Appendix E describe Moomoo protection only as a *client-translated*
      "opposite-side close order," with US Moomoo trading described as limit-only 24h. Neither the
      architecture nor the implementation program presents evidence that Moomoo OpenD supports a
      broker-resident protective stop that survives client/gateway/OpenD outage. If it does not,
      the approved live target broker structurally cannot pass its own gate, making the P14 premise
      internally contradictory. This does not block the non-live stages (0-13) but must be resolved
      before any live-canary authorization.
  - id: BF-2
    dimension: 12-request-rate-governance
    title: Single account-level token bucket is under-specified against two different Moomoo provider ceilings
    detail: >
      §16B.5 states "One account-level token bucket governs placements, modifications, cancellations,
      protection changes, emergency reserve," but the documented Moomoo limits differ by action:
      place_order 15/30s and modify_order 20/30s. A single shared bucket cannot simultaneously and
      correctly enforce two distinct ceilings; the only numeric policy given ("ordinary modify budget
      <=16, reserve >=4" = 20, the modify cap) provides no explicit enforcement of the lower 15/30s
      placement ceiling, and does not define how placement tokens and modify tokens interact within
      one bucket. "Fail closed before exceeding provider limits" is asserted but the mechanism to do
      so across the dual ceiling is not specified. This is a determinism/safety gap that must be
      closed before simulation rate-limit acceptance (Stage 10) and live (Stage 14).

nonblocking_findings:
  - id: NF-1
    dimension: 6-primary/fallback-duplicate-fill-prevention
    title: "Prove source not filled" mechanism is asserted but not specified for asynchronous broker order state
    detail: >
      §16F.8 / §28.6 permit automatic failover only after "source order is confirmed rejected or
      safely cancelled AND source filled quantity is known." For brokers with eventual-consistency
      order state (Schwab Trader API), confirmed-terminal state and known fill quantity may not be
      atomically obtainable at failover time. The architecture lists a test for "source broker late
      fill after rejection/cancel ambiguity" (§23.2) but does not define the deterministic rule that
      resolves the ambiguity window, only the guarantee it must achieve.
  - id: NF-2
    dimension: 8-cancel-and-cancel-all-protection
    title: Native account-level cancel-all creates an unprotected-position race window
    detail: >
      §16H.4 acknowledges native broker cancel-all may include protective children and requires
      "immediately re-protect or move to flatten." Between the native cancel and the re-protect
      submission the position is momentarily unprotected. The documents state the intent but do not
      bound the exposure of this window or require an atomic protect-preserving primitive where the
      broker offers one.
  - id: NF-3
    dimension: 19-drive/github-documentation-integrity
    title: The two controlling documents disagree on repository identity, and mandated AGENTS.md files are absent
    detail: >
      Architecture names canonical path /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild and
      host ms01-openclaw; the implementation program names repo PatsKiller/tardeai. Evidence confirms
      both are reconcilable (git remote is PatsKiller/tardeai; the canonical path is a sibling worktree;
      this review runs in worktree /home/johnclaw/worktrees/active-trader-next on branch
      feat/active-trader-next), but no explicit mapping is documented. Separately, implementation
      program §0 step 2 mandates "Read repository AGENTS.md files from root to target directory," yet
      no AGENTS.md exists anywhere in the tree — a mandated preflight input that cannot be satisfied.
  - id: NF-4
    dimension: 11-litmus-review-schema / internal-consistency
    title: Litmus output schema in architecture §16J.3 is a subset of the controlling litmus prompt v1.0
    detail: >
      Architecture §16J.3 defines the reviewer output with review_id/verdict/findings/hash, but the
      controlling ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md additionally requires
      access_mode_verified, write_attempted, recommended_operator_checks, and 25 enumerated dimensions.
      A controller that validates the reviewer artifact against §16J.3 alone would accept an
      under-specified report. The documents should reconcile the canonical reviewer schema.
  - id: NF-5
    dimension: 25-unresolved-operational-risk
    title: Regulatory citation (FINRA PDT replacement, April 2026, 18-month phase-in) is unverifiable from the repository
    detail: >
      Appendix D presents a specific SEC/FINRA regulatory event as fact and uses it to justify not
      hard-coding PDT. The mitigation (read broker/account rule at order time) is sound irrespective
      of the citation's accuracy, but the citation itself is an external, forward-dated claim that
      cannot be verified in a read-only Stage 0 review and should not be treated as settled fact.
  - id: NF-6
    dimension: 2-session-scoped-2FA / 7-quick-add-envelope
    title: Dynamic-universe authorization admits symbols the operator never individually reviewed at 2FA
    detail: >
      §1.2 permits the signed envelope to bind "a deterministic dynamic universe rule" rather than an
      explicit symbol list. Combined with §16F.4 (Schwab electronic-entry/broker-assist eligibility is
      learned only at runtime), a dynamically admitted symbol may carry restrictions the operator could
      not have seen at authorization. The failover/pause workflow (§16F.9) handles this safely, but the
      operator-authorization surface is wider than a reviewed symbol list, which should be made explicit
      in the 2FA envelope-review UI.
  - id: NF-7
    dimension: 22-unattended-checkpoint-resume / 24-rollback
    title: Non-live build run has a hard external dependency on Google (Drive/Gmail) and Bitwarden availability
    detail: >
      §16K.10 and program preflight halt the entire implementation run if Gmail or Drive verification
      fails. Coupling a code-build/test run's ability to proceed to third-party SaaS availability is an
      operational fragility; a Google/Bitwarden outage blocks non-live engineering progress that has no
      financial risk. This is a design trade-off worth flagging, not a safety defect.

questions:
  - Does Moomoo OpenD provide a broker-resident protective stop that survives OpenD/gateway/client
    disconnect for US equities, and if not, how can ADR-015 / §16.8 be satisfied for the P14 Moomoo canary?
  - Within the single account-level token bucket, what deterministic rule enforces the 15/30s placement
    ceiling distinctly from the 20/30s modify ceiling, and how is the emergency reserve carved from each?
  - What is the deterministic decision rule when a broker cannot confirm terminal order state or fill
    quantity within the failover decision window (BF/NF-1)?
  - Which schema (§16J.3 vs litmus prompt v1.0) is canonical for validating reviewer artifacts?
  - Is tastytrade (an adapter present in the repository, scripts/tastytrade_adapter.py) intentionally
    out of scope, given the architecture's broker plane is Alpaca/Moomoo/Schwab only?

evidence_refs:
  - docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md §1.2, §16.8, §16B.5, §16F.4, §16F.8, §16H.4, §16J.3, §16K.10, Appendix D, Appendix E, ADR-008, ADR-015
  - docs/prompts/ACTIVE_TRADER_ARCHITECT_LITMUS_REVIEW_PROMPT_v1_0.md (required-output block, 25 dimensions)
  - docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md §0 step 2, Stages 0-14
  - apps/command-center-v3/vite.config.ts:36 (base '/v3/'), :44-46 (proxy /api -> 127.0.0.1:7777)
  - apps/command-center-v3/src/App.tsx:194 (BrowserRouter basename="/v3")
  - apps/command-center-v3/package.json (react ^18.3.1, react-router-dom ^6.23.1, vite ^5.4.2, playwright, lightweight-charts, recharts — matches Appendix D)
  - apps/command-center-v3/src/pages/TradingHub.tsx, ScalpStopMonitorCard.tsx (existing Scalp surface)
  - repo confirms NO apps/command-center-v3-next, NO /api/v3/active-trader routes, NO Moomoo/futu SDK (absent from requirements.txt and imports)
  - scripts/broker_adapter.py, scripts/schwab_*.py, scripts/broker_confirm_alpaca.py, scripts/tastytrade_adapter.py (existing Schwab/Alpaca[/tastytrade] broker code)
  - git remote origin https://github.com/PatsKiller/tardeai; branch feat/active-trader-next; worktree /home/johnclaw/worktrees/active-trader-next; canonical path /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild present as sibling worktree

recommended_operator_checks:
  - Require documented proof (broker doc + runtime probe artifact) of Moomoo disconnect-surviving
    protective-order capability BEFORE authorizing P14; otherwise disable Moomoo live per §16.8.
  - Require the rate-governor design to state explicit, separately-enforced place (15/30s) and
    modify (20/30s) limits with reserve accounting, and a Stage 10 test that drives both ceilings.
  - Reconcile the canonical litmus-reviewer output schema (§16J.3 vs prompt v1.0) before Stage 12
    relies on it as an automated gate.
  - Add AGENTS.md at repo root (and target dirs) or amend program §0 step 2 to tolerate absence.
  - Confirm tastytrade scope decision and add an explicit repo-identity/path mapping note bridging
    the architecture's canonical path and the implementation program's PatsKiller/tardeai.
  - Treat the FINRA/PDT citation as unverified; verify independently before any account-rule logic
    depends on the stated effective dates.

review_hash: see controller attestation below (SHA-256 of this file)
completed_at: 2026-07-22
```

## Reviewer's challenge-only explanation (verbatim)

The v3.3 architecture and the v1.1 implementation program are, for the non-live stages, internally coherent, safety-first, and implementable against the real repository. Spot-checks confirm the architecture's stated preconditions: `/v3` exists at `apps/command-center-v3` with basename `/v3`, there is no `/v3-next`, no `/api/v3/active-trader` routes, Schwab/Alpaca broker code exists while no Moomoo SDK is present, and the frontend stack matches Appendix D. The determinism/authority spine (Laws 1-4, 16, §17.5), server-side session authority, hash-bound envelopes, capability-resolved broker actions, protection-preserving cancel-all, flatten-verifies-zero, event-sourced journaling, and no-self-scoring learning boundaries are all sound in the documents. On that basis the non-live build (Stages 0-13 / P0-P13) can proceed.

I withhold an unqualified PASS for two document-level reasons that bear directly on the *approved live canary*, plus documentation-consistency gaps. First (BF-1): the one broker the architecture actually approves for the live canary — Moomoo — is never shown to satisfy the architecture's own mandatory broker-native, disconnect-surviving protection precondition (§16.8/ADR-015); Moomoo close is described only as a client-translated opposite-side order. If Moomoo lacks a broker-resident stop, the P14 premise contradicts ADR-015. Second (BF-2): the single account-level token bucket is under-specified against Moomoo's two different documented ceilings (place 15/30s vs modify 20/30s), and the only numeric policy given equals the modify cap while leaving the lower placement cap without explicit enforcement — a request-rate-governance gap. The nonblocking findings (async duplicate-fill proof mechanism, cancel-all re-protect race window, repo-identity divergence, missing AGENTS.md, litmus schema subset mismatch, unverifiable FINRA citation, dynamic-universe authorization surface, and hard SaaS dependency for a non-live build) are challenges to resolve but do not block the staged non-live work. Verdict: CONDITIONAL_PASS — proceed with non-live stages; resolve BF-1 and BF-2 and the enumerated questions before any live-canary authorization.

I confirm I performed no writes, edits, commits, branch/flag/config changes, secret reads, broker calls, or agent triggers; my access was read-only throughout.

---

## Controller attestation

- Reviewer access mode: the reviewer executed as an `Explore`-type subagent whose tool set
  excludes Write, Edit, NotebookEdit, Artifact, and agent-spawning — writes were structurally
  impossible, not merely prohibited. Observed write attempts: **0**.
- The reviewer returned this report as message text only; this file was written by the Stage 0
  controller, verbatim, as the single permitted reviewer artifact.
- `review_hash`: the SHA-256 of this artifact file is recorded in `stage-00-drive-manifest.json`
  and in the stage-00 closeout; it serves as the canonical review hash.
- Verdict: **CONDITIONAL_PASS** — not a FAIL; Stage 0 may close. Blocking findings BF-1/BF-2
  gate the live canary (Stage 14 / P14), not Stages 0–13.
