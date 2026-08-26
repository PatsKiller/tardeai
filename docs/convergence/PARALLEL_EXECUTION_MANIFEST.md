# R20-R24 Parallel Execution Manifest

**Integrator:** `wt-r20-r24` on `convergence/r20-r24`
**Integrator HEAD:** recorded at freeze commit
**Base (this program):** `e683e90f9a24b9cd56399054da33cc6c3b4ba8bb`
**origin/main (production pin, not this branch):** `6088254efa4aedd6a023dcc193a78559996829db`
**Authority:** READ_ONLY_ADVISORY; MEMORY_BEHAVIOR_INFLUENCE=0
**HTTP freeze:** **CONTROL_PLANE_API_V1_BASELINE** (`084674c5`)
**Field vocabulary:** ControlPlane@v1.0.0
**R21_BASELINE_ACCEPTED:** true

| Stream | Owner | Scope | Status | Handoff |
|---|---|---|---|---|
| R20 | Integrator | runtime/specialist evidence | AUDIT_COMPLETE — not office LIVE | docs/_evidence/r20 |
| R21 | CODEX / integrated | CONTROL_PLANE_BACKEND summary GET | BASELINE_ACCEPTED | 084674c5 |
| R21.1 | CODEX (later) | detail + lineage + extra proof | PENDING (local preview c3b105a7) | additive only |
| R22 | worker `r22` | Agent Office + Workflow Trace | SUMMARY_APIS_CONSUMED | feat/r22-agent-office-workflow @ d10247b9 |
| R23 | worker `r23` | Research/Data/Identity/Notifications | SUMMARY_APIS_CONSUMED | feat/r23-admin-observability @ be18e724 |
| R24 | worker `r24` | Learning/Maturity/Audit | SUMMARY_APIS_CONSUMED | feat/r24-learning-maturity-ui @ 52c11090 |
| QA | worker `qa` | fixtures/compat/authority/secrets/routes | PASS | docs/_evidence/qa |

## Untracked-file classification (do not git clean / rm)

Program worktrees inspected 2026-08-26. Classification is owner-of-path, not a delete list.

| Path | Owner | Notes |
|---|---|---|
| `/home/johnclaw/trade-ai-v12-rebuild/wt-r20-r24` | INTEGRATOR | `convergence/r20-r24` — **clean** (no untracked at classify time) |
| `/home/johnclaw/trade-ai-v12-rebuild/wt-r22-agent-office` | R22 | `feat/r22-agent-office-workflow` — **clean** |
| `/home/johnclaw/trade-ai-v12-rebuild/wt-r23-admin-observability` | R23 | `feat/r23-admin-observability` — **clean** |
| `/home/johnclaw/trade-ai-v12-rebuild/wt-r24-learning-maturity` | R24 | `feat/r24-learning-maturity-ui` — **clean** |
| `/home/johnclaw/worktree-r21` | R21 | `feat/r21-control-plane-backend` @ 00cdaac3 — **clean** |
| `/home/johnclaw/r21-1-detail` | R21 | `feat/r21.1-detail-lineage` — **clean**; treat as preview until Codex handoff |
| `/home/johnclaw/worktree-r20` | R20 | `r20-live-runtime-audit` — **clean** |
| `/home/johnclaw/trade-ai-v12-rebuild/wt-r18-data` | OTHER_WORKTREE | `feat/r19-specialist-office-activation` — **clean**; R19 local, not CURRENT |
| `/home/johnclaw/worktrees/r24-learning-audit` | OTHER_WORKTREE | `feat/r24-learning-audit` — audit baseline tree, not UI worker |
| `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` | OTHER_WORKTREE | `feat/two-way-watchlist-curation` — ~190 dirty/untracked docs/config/scripts. **Do not add. Do not clean.** |

**UNKNOWN:** none on program trees. UNKNOWN paths must remain untouched until resolved.

## R21 Codex mission (closed for summary; open for R21.1)

Summary GET-only service layer is accepted at 084674c5.

R21.1 (later, additive): agent detail, workflow detail, lineage adapters, more contract/fault tests.

R21 must NOT own: frontend pages, NavRail, App.tsx route cutover, maturity methodology
redesign, investment intelligence, specialist orchestration, notification policy,
canonical persistence redesign.

## Rules

- No worker pushes. No PRs. No CI per stream.
- Workers return WORKSTREAM_HANDOFF.
- Integrator owns paths in `INTEGRATOR_OWNED_PATHS.md`.
- Live Command Center routes remain untouched.
- Ready-for-sync is false until all streams + dry-run + replay + fault + acceptance.
- Do not display LIVE merely because the API exists.
