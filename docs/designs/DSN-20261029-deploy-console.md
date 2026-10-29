---
id: DSN-20261029-deploy-console
title: Deploy console — actionable in-flight board + LLM-driven push/merge/force controls
status: PROPOSED
approval: operator (force-promote/rollback are §17/§27.3 MAJOR; Approve/Hold reuse the existing Telegram-tap authority)
source: operator 2026-10-29 — "actionable buttons that can be driven by LLM … push, merge, force live"
phases:
  - id: DSN-20261029-deploy-console-P1
    title: In-flight board + tooltips (read-only)
    status: PROPOSED
    tasks:
      - id: DSN-20261029-deploy-console-P1-T1
        title: Backend open-PR projection (state · mergeable · CI · why held) + frontend in-flight table + ⓘ tooltips
        status: PROPOSED
  - id: DSN-20261029-deploy-console-P2
    title: Approve / Hold / Refresh-hints write path
    status: PROPOSED
    tasks:
      - id: DSN-20261029-deploy-console-P2-T1
        title: Operator-session, CSRF-protected POST that adds/removes operator-merge (same authority as the Telegram tap) + refresh-shard-hints
        status: PROPOSED
  - id: DSN-20261029-deploy-console-P3
    title: Force promote / rollback (passkey-gated)
    status: PROPOSED
    tasks:
      - id: DSN-20261029-deploy-console-P3-T1
        title: WebAuthn passkey + typed-phrase force-promote and rollback (§27.3/§25.10) — its own reviewed PR
        status: PROPOSED
---

# Deploy console — design of record

## What it is

The System → Releases & Schedules page becomes a **deploy console**: the in-flight (open) PRs that are not
serving become visible with their state, next state, and actionable buttons. The LLM drives the *pipeline* —
it validates CI, computes the exact head SHA, stages the label/receipt — and the operator drives the
*authority* (tap for safe actions, passkey + typed phrase for the risky direction).

## Authority mapping (nothing new; each button reuses an existing rail)

| Button | Action | Authority | LLM role |
|---|---|---|---|
| Approve | add `operator-merge` bound to head SHA → Mergify queues | operator tap (== today's Telegram Approve) | validate CI green + compute SHA |
| Hold | remove label / set held | operator tap | prepare |
| Refresh hints | re-run `ci_shard_duration_hints` refresh from the green ci-gate artifact | operator tap | stage command |
| Resolve conflict | open both-sides sheet; operator picks, LLM writes | operator decides, LLM writes (coordinator path) | diff + propose |
| 🛑 STOP deploy | latch deploy STOP | one click (§27.3 safe direction) | confirm state |
| ⚡ Force promote | `emergency_manual_promote.sh <sha>` | **passkey + typed phrase** (§27.3 / §25.10) | stage SHA + receipt |
| ↻ Rollback | re-point CURRENT at prior known-good SHA | **passkey + typed phrase** | stage SHA + prove rollback target |

## Why three PRs, in this order

- **P1 (read-only)** is shippable immediately and is the foundation: no write path, no new authority.
- **P2 (Approve/Hold)** adds a write path that reuses the operator-merge label write the Telegram tap already
  performs — same authority, new surface. Low risk, still operator-gated by session auth.
- **P3 (force promote / rollback)** is **MAJOR (§17/§27.3)**: it moves a host-CLI-only act onto a web surface and
  therefore needs WebAuthn passkey + typed phrase, its own reviewed PR, and operator approval. It cannot ride in
  P1/P2.

## Sequencing constraint (honest)

`apps/command-center-v3/src/pages/ReleasesSchedules.tsx` is already in conflict in PRs #2113 and #2220. P1 and
P2 must either (a) wait for those to merge, or (b) land the in-flight board as a *separate* component/page that
does not edit the conflicting lines, to avoid making two existing conflicts worse. This design chooses (b): the
in-flight board is a new component mounted on the page, not an in-place rewrite of the existing tables.

## Honesty

- "Actionable and LLM-driven" means the LLM stages the action and the operator fires it — the LLM never
  self-authorizes a merge, push, or promote (§0 rule 9, §25.10). That boundary is the point of the design, not a
  limitation.
- Force-promote and rollback remain `passkey + typed phrase` — the operator's alone, exactly as §27.3 binds.
