# Hands Off Delivery

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 6398-6519 -->
## Moved from AGENTS.md (25.0.1 lines 6398-6519)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

- **1 Push budget 5, with a coordinator override on approved scope.** The per-branch budget (`AI_WORK_POLICY.md` §3,
  §17) is 5 authorized pushes, not 2.
  - Only the coordinator session may push past it, with `TRADEAI_REMOTE_PUSH_OVERRIDE=1`. That is the session that
    keeps the day's coordinator worklog (§28.3), identified by its `AGENT_CLAIM_SESSION`.
  - It may do so only for a PR linked to an operator-approved scope: a claim-board plan carrying an operator approval
    reference, or a PR body line `Operator-approval: <the operator's words or a reference to them>`. An approval
    relayed between agents never counts (§28.4).
  - Each override is logged with that reference: `TRADEAI_REMOTE_PUSH_OVERRIDE_REF` in the push-budget ledger, and
    `agent_claim.py note` in the coordinator worklog.
  - Force-push stays forbidden. Renaming or re-creating a branch to reset a budget is still routing around a denial
    (§0 rule 3).
  - The hook change (`scripts/lib/tradeai_push_budget.py`) ships after ratification by item 3's two-review path. Until
    it is merged, the hook enforces 2.

  *Cause (§20): on 2026-10-25 the budget of 2 blocked four operator-approved PRs, and each waited for an operator
  override.*
- **2 Shared infrastructure ships alone, through the digest (rewritten 25.0.0).** A PR in a class that once needed
  the operator per PR is labelled `shared-infra` at open and merges alone through Mergify's one-at-a-time queue after
  the operator's digest approval (§25.10). This covers scheduler, registry, allowlist, systemd and cron;
  communications; deploy-adjacent code outside the held list; the portfolio-server API; oversized PRs; deletions;
  auth code; and migrations.
  - **Conditions:** an `Adversarial-review: MERGE` receipt from a reviewer identity other than the author (item 10),
    with its reference; a `Real-layout proof:` line (§28.9); and every required check `success` on the head, plus
    `shared-infra-review` for `[shared-infra]` paths.
  - **Deletions** must archive with a tripwire (§0 rule 6).
  - **Migrations** must be expand-only and reversible, proven by a dry run on a scratch database. A destructive DDL is
    a deletion.
  - **Auth** code is eligible. A secret value, credential file, `.env` or `config/secret_registry.yaml` change never
    is.
  - **Verify:** the post-release tester adds `scripts/check_allowlist_consistency.py`, `scripts/check_lane_registry.py`
    and a clean `scripts/cron_outage_watchdog.py` pass to §28.12 step 9. A failure latches STOP and pages P1.
  - **Never by "Approve all":** held classes (§25.10) — broker, Active Trader, MBI, secrets, policy, hooks, guard, and
    merge and deploy tooling.
  - **§17:** for the cron, systemd, n8n-activation, dispatcher-row and data-source items, the merged, reviewed PR that
    the operator approved in the digest is the decision, in place of the per-act grant.

  *Cause (§20): §28.9, shared infrastructure ships alone; on 2026-10-25 every such PR waited for a per-PR operator
  release.*
- **3 Guard, hook, CI-enforcement, merge and deploy tooling: the operator's own merge (rewritten 25.0.0).** These
  PRs are held class (§25.10). They need two `Adversarial-review: MERGE` receipts from two reviewer identities other
  than the author (item 10), the `shared-infra-review` check `success` and a `Real-layout proof:` line, and then the
  operator's own merge; reviews alone never merge them.

  **No weakening.** A diff that removes or loosens a §0, §2 or §17 enforcement is flagged by the classifier and goes
  to the operator. That means a guard check, a never-list or held-path entry, a hook refusal, or an assertion of a
  pinned policy test. Each reviewer receipt attests "does not weaken §0/§2/§17 enforcement". A change is qualified by
  the verifier already on `main`, never by its own.

  *Cause (§20): review 2026-10-27 M1 and M3 — two agent reviews and a veto window let guard and CI changes ship with
  no operator act.*

- **4 Which lanes run live is declared in the repo.** A lane is live when:
  - its `config/lane_registry.json` row is at `scheduler.stage` `canary` or `cutover`, with `dispatch.mode` `live`;
  - and its `config/n8n_run_allowlist.json` entry has a `live_arg`.

  At deploy, the relay derives its live list from those rows (`scripts/render_n8n_relay_env.py`), never from a `never`
  lane (§23.14). The host setting `TRADEAI_N8N_RELAY_LIVE_LANES` becomes an override only:
  - removing a lane there takes effect at once;
  - adding a lane there stays the operator's §17 act;
  - when the derivation fails, the last good list is kept, never widened.

  Activating a lane is a reviewed registry PR under item 2. §17's "changing the n8n relay live list" now
  reads as changing the host override. *Cause (§20): on 2026-10-25, merged and released lanes stayed dry until the host
  relay live list was edited by hand.*
- **5 No TTY ACK for routine setup.** A new packet never needs an interactive TTY acknowledgement for a routine
  schedule or configuration change. It ships as merged and deployed configuration with a verify step (§25.10). *Cause (§20): on
  2026-10-25, setup packets stopped on TTY ACKs for schedule changes the operator had approved.*
- **6 Configuration is not a secret.** The server `.env` holds configuration only; secrets live in Bitwarden (operator,
  2026-10-25).
  - An agent may change a named configuration key with a tool that writes that key alone, backs the file up first
    (timestamped, mode kept) and prints only that key.
  - It never prints, copies or reads out another value.
  - A key on `config/secret_registry.yaml`, or named like a token, secret, password or credential, is refused.
  - An operator-facing switch belongs on Ops Controls (`/v3/system/ops-controls`) with an audited change log, not in a
    file edit.
  - Secrets themselves are unchanged: never read, copied or printed. This item narrows §24.7 for named configuration
    keys only, once that tool is on main.

  *Cause (§20): on 2026-10-25, enabling SMS waited on the operator to edit `.env` by hand. Operator: "this should have
  just been a toggle on the control ops."*
- **7 Retired (25.0.0).** The `solo` release-delegation class went with the release train. Mergify's `solo` queue
  label is unrelated and only orders merges.

- **8 Routine pushes and toolchains need no guard grant.**
  - (a) An agent working under an operator-approved plan or scope may `git push` its own feature branches without a
    guard `git-push` grant. The scope is a claim-board plan with an `Operator-approval:` reference, or a
    coordinator-assigned task file under `data/coordination/handoffs/`. The push must be fast-forward only and within
    the push budget (item 1). It never goes to `main` or `release/*`, and it never force-pushes, resets,
    runs `filter-branch`, or deletes a remote branch. The guard records each such push. Pushes to `main`, history
    rewrites and force pushes still need the operator.
  - (b) Running an existing toolchain is never in the `deps` scope. That covers `npm run …`, `npx playwright test`,
    `pytest`, `ruff`, `tsc`, builds and tests. `deps` covers only installing, removing or upgrading packages
    (`pip`, `npm` or `apt` install, uninstall or upgrade) and lockfile changes. The guard hook must classify commands
    this way.
  - (c) The mechanics, namely the guard hook classification and push-without-grant under an approved plan, are a
    follow-up PR gated on 21.0.0 being ACTIVE, by item 3's path. Until it merges, the guard enforces as today. The `hands_off_policy.py` gate in PRs #2115, #2118 and #2125 must key on the `| 21.0.0 |`
    version row; there is no `| 20.4.0 |` row.

  *Cause (§20): 2026-10-25 16:14 ET, Cursor, following 20.2.0, asked the operator on Telegram for a `git-push` grant to
  push routine page-repair branches and a `deps` grant to run `npm run build` and Playwright.*
- **9 The complete list of what reaches the operator (§17):**
  - (a) Ratifying `AGENTS.md` or `AI_WORK_POLICY.md` (§20): the operator reads the amendment in the Command Center
    (Approvals, the `policy:<PR>` item) and approves it there, which records
    `APPROVE_AGENTS_POLICY_<x> <pr> <head_sha>` for the head SHA shown in the operator decision ledger; a stale SHA
    is refused. Until that ledger is a granted store, the operator posts the same line as a PR comment. The
    ratified PR is then merged by the operator (held class, §25.10).

  - (b) Broker and MBI: never delegable (§0 rules 1–2, §28.6, the Schwab mode, locks and kill switches).
  - (c) Credentials and secrets (§24.7).
  - (d) Design approvals (§28.13).
  - (e) Alerts and escalations: a P1, a refused weakening (item 3), a self-heal escalation (§28.14), or clearing a STOP
    latch after a rollback.

  Everything else ships with no operator input. Spending money (funding a model or data plan) is not delegated by this
  section. *Cause (§20): operator 2026-10-25, "fully done, fully automatic, no input by me … unless there's an issue".*
- **10 No self-review (25.0.0).** A review, an `Adversarial-review: MERGE` receipt, a health contract's `REVIEWED`
  status (§23.19) or any other sign-off counts only when its reviewer id differs from the author's agent and session:
  the operator, or another agent identity. An author who reviews its own work records `SELF` and that review counts
  for nothing. Guard, hook, CI-enforcement, and merge and deploy tooling changes need the operator (item 3). The
  coordinator push override (item 1) never applies to a held-class PR. *Cause (§20): review 2026-10-27 M3 — 116 of
  167 contracts were `REVIEWED` by a team label with no operator or independent reviewer, and two agent reviews could
  pass a guard change.*
