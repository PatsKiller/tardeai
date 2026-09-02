Status:      ACTIVE  
as_of:       2026-09-02T09:05:00-04:00  
run_id:      sop-1.2.0-20260902  
prompt_version: 1.0.0  
Canonical repo path: docs/implementation/maturity-program/sop-1.2.0-20260902/STAGE_00_PREFLIGHT.md  
Authority:   Stage 0 measurement + proposed claims only. No remote sync. No PR. No promote.  
Verdict:     **PASS (preflight isolation)** · **STOPPED_ON_AUTHORITY_BOUNDARY** before AGENTS.md 1.2.0 activation / remote / Drive write / branch-protection

# Stage 0 · Fresh-state preflight and constitutional read

## Checkpoint fields

| field | value |
|---|---|
| exact base SHA | `4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9` |
| current head SHA | `4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9` (identical) |
| worktree | `/home/johnclaw/tradeai-wt-sop-120-governance` |
| branch | `governance/sop-1.2.0-seven-controls` |
| dirty-before | empty |
| dirty-after (this stage) | this evidence directory only (not yet committed) |
| money / orders / production / schedulers / guardrails changed | **NO** |
| next authority boundary | Operator phrase required before: remote push, PR open, AGENTS.md **ACTIVE** 1.2.0, Drive write, branch-protection change, promote |

Historical anchor `4bcba2cf…` **equals** freshly fetched `origin/main` (0 commits ahead). Any prepared release based on that SHA is **not stale relative to main tip**; served CURRENT (`6d6609915…`) **lags main** and is a separate drift class (reported, not fast-forwarded).

## 1 · Identity [VERIFIED]

```
origin/main          4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9
worktree HEAD        4bcba2cf7168f1cc9b1b7ffd18ab749b2eed44a9   PINNED
hub checkout         077d1b2d8 (detached) + untracked archive/weekly/  — dirty/lagging; ROUTED AROUND
served CURRENT       BUILD_SHA 6d6609915171fe6a153daf71d413df88b6483864  ≠ origin/main
$PROJ / hub          not fast-forwarded (forbidden without separate approval)
.env in worktree     ABSENT (no copy/symlink performed)
core.hooksPath       .githooks
```

## 2 · Policy [VERIFIED]

| artifact | version | status | SHA-256 |
|---|---|---|---|
| `AGENTS.md` | **1.1.0** | **ACTIVE** | `425f1953a3f1f0cfe40d3b4b33902655513442b2fe57993105e83a6f5c9b7546` |
| known prior (prompt) | 1.1.0 | ACTIVE | matches byte-exact |
| prompt target | **1.2.0** | initially **PROPOSED** | not present on tip |

`AI_WORK_POLICY.md` present; SHA-256 `e98d583a4fe2568b4264edcf4bc30dd00eb0f2015935677618780cdc5b77b97a`.  
Version history on tip: 1.0.0 MAJOR approved (#841); 1.1.0 MINOR ratified (#843).

**Authority note:** drafting `Policy-Version: 1.2.0` / `Status: PROPOSED` is in-scope for local governance work. Making it **ACTIVE**, pushing, or opening a PR that asserts activation requires operator authorization with the correct change class (MINOR vs MAJOR). Touching authority-bearing sections (§0, role authority, financial rails) → stop for classified approval.

## 3 · Policy / hook self-tests [VERIFIED]

```
pytest tests/test_ai_work_policy_hooks.py tests/test_agents_policy_v1.py  →  58 passed
```

Manual empty-stdin `.githooks/pre-push` with `TRADEAI_REMOTE_PUSH_AUTHORIZED=0` exited 0 (not a real push invocation). **Do not treat that as a pass**; the pytest suite is the verified control.

## 4 · Existing mechanisms (extend; do not parallel) [VERIFIED present]

| capability | existing | notes |
|---|---|---|
| Agent routing config | `config/agents.yaml`, `config/agents.json`, `agent_runtime*.json` | **Router/maturity**, not client-adapter registry |
| Git hooks | `.githooks/pre-commit`, `pre-push`; `install_ai_work_policy.sh` | Worktree inherits `core.hooksPath=.githooks` |
| Worktree helper | `scripts/new-worktree.sh` | **DEFECT vs SOP Stage 5:** symlinks `.env` by default; prints `git add -A` |
| Drive AGENTS mirror | `scripts/mirror_agents_md_to_drive.sh` + #842 | Stable file-id update path exists |
| Drive manifest evidence | commit `eac13cfd0` on `docs/agents-drive-manifest-4bcba2cf` | **PRESERVE** — supersede/cherry-pick decision deferred to Stage 7/Drive checkpoint |
| Maturity program prior | `docs/implementation/maturity-program/mp-20260901-210554/` | Historical STOP on hub≠main; policy path since completed through 1.1.0 |
| Session receipt / file leases | **NOT_VERIFIED as canonical SOP shape** | No `SessionReceipt` / `LeaseCoordinator` module found in first-pass search; handoff queues and claims exist in other domains |
| `agent-governance` CI job | **ABSENT** | `cio-hardening` and other workflows exist; dedicated always-on governance workflow not found |

## 5 · Open PRs (count only; Stage 1 expands) [VERIFIED]

```
open_pr_count = 34
includes #777 fix/cash-freshness (ACTIVE collision risk with cash surfaces)
includes many stale DRAFTs (defense/watch/moomoo ActiveTrader)
```

No PRs mutated. Overlap matrix → Stage 1 deliverable.

## 6 · Proposed file / store claims (Integrator = this agent for shared governance)

**Claimed for this tranche (proposed; not yet leased mechanistically):**

- `docs/implementation/maturity-program/sop-1.2.0-20260902/**` (evidence)
- `config/agent_clients.yaml` (+ schema) — **new** client registry (distinct from `config/agents.yaml` router)
- `scripts/lib/agent_session_receipt.py`, `scripts/lib/agent_file_lease.py` (or extend existing if deeper search finds one)
- `scripts/agent_session_start.py` (governed launcher)
- harden `scripts/new-worktree.sh` (Stage 5)
- `.github/workflows/agent-governance.yml`
- `tests/test_agent_clients_registry.py`, `test_agent_session_receipt.py`, `test_agent_file_lease.py`, `test_new_worktree_sop.py`
- `AGENTS.md` — **PROPOSED 1.2.0 only** after change-class declaration
- Drive mirror tests / manifest schema under `docs/ops/` / `docs/manifests/`

**Explicitly NOT claimed / not touched:**

- holdings, broker, order, scheduler/cron/systemd, wake-consult behavior, cash_letter dollars, lane_registry mass sweep
- `#777` merge/rebase
- hub `$PROJ` fast-forward
- CURRENT promote
- peer worktrees / `archive/weekly/` on hub

**Hot-file serialization (pending Stage 1 matrix):** `AGENTS.md`, `.github/workflows/*`, `scripts/run_cio_hardening_ci.py`, `config/agents.yaml` — integrator-only.

## 7 · Role attestation

| role | this session |
|---|---|
| Chief Architect / Integrator (governance files) | **assumed** (single technical agent) |
| Independent verifier | **INDEPENDENT_VERIFICATION_PENDING** |
| Operator | **not assumed** — remote/Drive/activate/promote denied |

## Commands run (exit codes)

| command | exit |
|---|---|
| `git fetch origin main` | 0 |
| `git worktree add … 4bcba2cf7` | 0 |
| `sha256sum AGENTS.md` | 0 (matches known prior) |
| `pytest tests/test_ai_work_policy_hooks.py tests/test_agents_policy_v1.py` | 0 (58 passed) |
| `gh pr list --state open` | 0 (34 PRs) |

## Unresolved / blockers

1. **CURRENT ≠ origin/main** — served pin lags; not remediated.  
2. **Hub checkout ≠ origin/main** — routed around; optional `FAST_FORWARD_CANONICAL_CHECKOUT` still operator-only.  
3. **No mechanical lease service yet** — Stage 4 must implement or bind to a found coordinator.  
4. **`new-worktree.sh` violates SOP Stage 5 defaults** — must harden without breaking documented automation that expects `.env` (opt-in only).  
5. **Policy 1.2.0 change class** — declare MINOR vs MAJOR before editing authority-bearing AGENTS sections.

## Next

Proceed to **Stage 1** (open-PR collision inventory, local docs only).  
Do **not** push, open PR, write Drive, or activate policy.
)
