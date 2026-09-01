# Executive Role Charter — Trade AI Investment Office

Status:      ACTIVE
as_of:       2026-08-13T15:38:32-04:00
Measured at: efcc51365 / not measured

> Canonical source of truth for executive/specialist role identity in the converged product.
> Operates under the existing `READ_ONLY_ADVISORY` constitution. No broker/order/2FA authority anywhere.

## 1. Office map

| Executive | Role | Stable ID (runtime) | Process ID | systemd | OpenClaw | State |
| --- | --- | --- | --- | --- | --- | --- |
| **Alex** | **Chief Investment Officer (CIO)** | `alex` | `alex_cio_synthesis`, `alex_cio_escalation` | `@alex.timer` | `agents/alex` | SHADOW → live advisory |
| **Morgan** | **Chief Wealth Officer (CWO)** | `morgan` | `morgan_wealth_synthesis` | `@morgan.timer` | `agents/morgan` | SHADOW |
| **—** | **Chief Financial Officer (CFO)** | *(missing)* | *(none)* | *(none)* | *(none)* | **DEFINED, NOT IMPLEMENTED** |
| Steph | Senior Portfolio & Wealth Strategist | `steph` | `steph_allocation_review` | `@steph.timer` | `agents/steph` | SHADOW |
| Maria | Research Director / Senior Analyst | `maria` | `maria_research_critique` | `@maria.timer` | `agents/maria` | live (research) |
| Guardian | Independent Risk Officer | `risk_agent` | `guardian_risk_critique` | `@risk_agent.timer` | `guardian` (skeleton) | DESIGNED |
| Ledger | Tax & Account-Constraint Specialist | `tax_agent` | `ledger_tax_critique` | `@tax_agent.timer` | `ledger` (skeleton) | DESIGNED |
| Hermes | Independent Research / Challenge Layer | `hermes` | `hermes_external_research` | `@hermes.timer` + n | `hermes` | live |

Evaluation / knowledge-governance layers (NOT executive offices, no recommendation authority): **Darwin** (`darwin`), **Sentinel** (`sentinel`), **Iris** (`iris`), Nightly Reflection (`reflection`).

## 2. ID ↔ display mapping (preserve stable IDs, migrate display only)

| Stable ID | Display name | Notes |
| --- | --- | --- |
| `risk_agent` | **Guardian** | watch pipeline + catalog + systemd use `risk_agent`; process/OpenClaw use `guardian`. Do NOT rename the stable ID. |
| `tax_agent` | **Ledger** | watch pipeline + catalog + systemd use `tax_agent`; Wave-3 `definitions.py` and OpenClaw use `ledger`. Reconcile in Phase 3 (runtime wiring) — no destructive rename now. |
| `alex` | **Alex (CIO)** | Was labeled "Chief Investment & Wealth Officer"; corrected to CIO (wealth is CWO). |

## 3. Authority: one final investment recommendation

- **Alex (CIO) is the sole producer of the final investment recommendation.** Only `alex` carries the `cio_synthesis` job type and `CIO_SYNTHESIS` output kind (structurally enforced in `scripts/agent_runtime/agents/definitions.py`).
- CWO (Morgan), CFO (future), Steph, Maria, Guardian, and Ledger produce **inputs/constraints** — not competing final recommendations.
- Topics outside investment strategy (household goals → CWO; treasury/liquidity → CFO) remain inputs unless Alex explicitly adopts them into a recommendation.
- Guardian does not mutate risk policy; Ledger does not execute or select lots; both are advisory.

## 4. CFO contract (defined; implementation deferred)

CFO does not currently exist. It will be implemented deliberately, not by renaming another agent.

- **Input domains (deterministic):** treasury/liquidity posture, near-term cash-flow requirements, reserves, planned contributions/distributions, required cash for taxes/commitments, account funding & withdrawal sequencing, known liabilities, cash available vs unavailable for investment.
- **Triggers:** material cash/liquidity change; planned contribution/distribution; tax/commitment cash requirement; funding/withdrawal event.
- **Artifact schema:** `cfo-liquidity-review-v1` — `{ as_of, cash_total, cash_reserved, cash_investable, near_term_obligations[], funding_sequence[], constraints[] }`.
- **Authority:** `READ_ONLY_ADVISORY`; denied `order.*, broker.*, approval.*, 2fa.*, position.write`.
- **Status:** DEFINED only. Implementation deferred to the evidence-spine (Phase 2) and specialist-committee (Phase 4) phases.

## 5. Handoff contract (unchanged, verified)

`scripts/lib/cio_agent_handoff_queue.py` already enforces the boundary:

```text
ALLOWED_TASK_TYPES   = cio_question, specialist_reconciliation, evidence_review,
                       fundamental_research, catalyst_review, watch_review,
                       allocation_review, retirement_review, income_review,
                       liquidity_review, risk_review, tax_account_review,
                       wealth_synthesis, goal_tracking, liquidity_planning,
                       multi_account_coordination, tax_coordination, estate_review, wake
FORBIDDEN_TASK_TYPES = execute_trade, submit_order, modify_position, approve_risk,
                       change_stop, run_shell, restart_service, deploy_code,
                       modify_config, send_telegram
```

No handoff may carry execution, order, risk-approval, config, shell, or Telegram authority.

## 6. Reconciliation ledger (open items)

1. **`tax_agent` vs `ledger`** — two layers use different stable IDs for the same office. Resolution: keep `tax_agent` as the runtime stable ID, display "Ledger"; unify in Phase 3 orchestration.
2. **CFO missing** — defined in §4, implement in Phase 2/4.
3. **Guardian/Ledger OpenClaw workspaces are skeletons** — display identity exists in `.openclaw`, runtime wiring deferred.
