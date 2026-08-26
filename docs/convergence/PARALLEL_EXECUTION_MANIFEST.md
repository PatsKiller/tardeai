# R20-R24 Parallel Execution Manifest

**Integrator:** `wt-r20-r24` on `convergence/r20-r24`
**Integrator HEAD:** recorded at freeze
**Base (this program):** `e683e90f9a24b9cd56399054da33cc6c3b4ba8bb`
**origin/main (production pin, not this branch):** `6088254efa4aedd6a023dcc193a78559996829db`
**Authority:** READ_ONLY_ADVISORY; MEMORY_BEHAVIOR_INFLUENCE=0
**Shared contract:** **ControlPlane@v1.0.0**

| Stream | Owner | Scope | Status | Handoff |
|---|---|---|---|---|
| R20 | Integrator | runtime/specialist evidence | AUDIT_COMPLETE | docs/_evidence/r20 |
| R21 | **CODEX** | CONTROL_PLANE_BACKEND — canonical read-only APIs | HOLD — envelope ≠ ControlPlane@v1.0.0 | docs/_evidence/r21/R21_HANDOFF_REVIEW.json |
| R22 | worker `r22` | Agent Office + Workflow Trace pages (fixtures) | ACCEPT_PAGES | feat/r22-agent-office-workflow |
| R23 | worker `r23` | Research/Data/Identity/Notifications pages | ACCEPT_PAGES | feat/r23-admin-observability |
| R24 | worker `r24` | Learning/Maturity/Audit pages | ACCEPT_PAGES | feat/r24-learning-maturity-ui |
| QA | Integrator (optional later) | contract/fault/replay | pending | pending |

## R21 Codex mission (do not expand)

Implement GET-only service layer for:

RuntimeStatus, AgentRuntimeStatus, WorkflowTrace, ResearchAttentionStatus,
CanonicalStoreStatus, IdentityStatus, NotificationStatus, LearningEvidenceStatus,
MaturityDimension, AuditCapabilityClaim

matching **ControlPlane@v1.0.0**.

R21 must NOT own: frontend pages, NavRail, App.tsx route cutover, maturity methodology
redesign, investment intelligence, specialist orchestration, notification policy,
canonical persistence redesign.

Optional later consume (not a requirement, not a competing product):
`feat/r19-specialist-office-activation` `scripts/api_v3_control_plane.py` on origin/main-line.
If reused, it must be adapted to ControlPlane@v1.0.0 and registered by Integrator.

## Rules

- No worker pushes. No PRs. No CI per stream.
- Workers return WORKSTREAM_HANDOFF.
- Integrator owns paths in `INTEGRATOR_OWNED_PATHS.md`.
- Live Command Center routes remain untouched.
- Ready-for-sync is false until all streams + dry-run + replay + fault + acceptance.
