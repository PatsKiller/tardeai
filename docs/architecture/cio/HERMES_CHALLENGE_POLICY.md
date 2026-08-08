# Hermes Challenge Policy — Independent Review

**Date:** 2026-08-08
**Phase:** P2.5 Hermes Challenge + Independent Review Policy
**Status:** FROZEN

---

## 1. Hermes Role

Hermes is an **independent research challenger**, NOT subordinate to Alex. Hermes operates its own schedule, its own research database, and its own pipeline (crontab-driven, extensive — coordinator, scorer, alerts, news bridge, topic bridge, etc.). Hermes produces research artifacts independently of Alex's CIO synthesis pipeline.

Alex may REQUEST a Hermes challenge through the HermesChallengeQueue (P-1.9), but Alex CANNOT:
- Change Hermes schedule
- Edit Hermes results
- Suppress disagreement
- Self-score based on agreement

---

## 2. Challenge Triggers — When Alex SHOULD Request a Hermes Challenge

| Trigger | Description | Materiality Threshold |
|---------|-------------|----------------------|
| **High materiality** | Proposed action has large portfolio impact (>5% of portfolio or >$50K) | Mandatory challenge |
| **Low confidence** | Alex confidence in synthesis below threshold | Agent-defined, typically <70% |
| **Conflicting specialist evidence** | Guardian and Steph disagree, or Ledger flags a conflict | Mandatory challenge |
| **Major catalyst/event** | Earnings, FDA decision, regulatory change, macro shock | Context-dependent |
| **Major concentration decision** | Adding to a position that would exceed concentration thresholds | Mandatory if exceeds soft limit |
| **Large tax/allocation trade-off** | Selling appreciated positions vs allocation targets | Optional (Ledger input may suffice) |
| **Freshness/source-quality concern** | Evidence is STALE or from single source | Optional |
| **Operator explicitly requests** | Operator asks for Hermes second opinion | Mandatory (operator directive) |

---

## 3. Challenge Non-Triggers — When NOT to Challenge

| Situation | Why Not |
|-----------|---------|
| Routine daily briefing synthesis | Standard synthesis, no material action proposed |
| Minor allocation drift (<2%) | Within normal rebalancing band |
| Simple data read (holdings, performance query) | No analysis or advice being generated |
| Watchlist management updates | Research only, no action proposed |
| Hermes already has recent coverage | Duplicate within freshness window (48h) |
| Run budget exhausted | Hermes challenge would exceed max_hermes_challenges budget |

---

## 4. Challenge Types

| Type | Description | When to Use |
|------|-------------|-------------|
| **research_gap** | Hermes researches a topic not yet covered in CIO evidence | Missing catalyst, sector, or competitive analysis |
| **contradiction** | Hermes reviews conflicting specialist evidence | Guardian vs Steph disagree, or Ledger flags conflict with Steph recommendation |
| **freshness_decay** | Hermes re-researches a topic where evidence is stale | Evidence > freshness threshold |
| **source_quality** | Hermes validates source quality for a specific claim | Single-source evidence, unverified catalyst |

---

## 5. Challenge Resolution Contract

Alex reads Hermes challenge results and records one of:

| Resolution | Meaning | Alex Action |
|------------|---------|-------------|
| **AGREES** | Hermes research aligns with CIO synthesis | Record agreement, proceed with action |
| **DISAGREES** | Hermes research contradicts CIO synthesis | MUST preserve disagreement in CIO artifact. Present both views to operator. DO NOT silently resolve. |
| **INCONCLUSIVE** | Hermes research is ambiguous or insufficient | Note uncertainty. Consider operator consultation or additional specialist review. |
| **UNAVAILABLE** | Hermes challenge failed (timeout, error) | Record UNAVAILABLE. Proceed with caveat. Do not retry within same run. |

---

## 6. Independence Rules

1. **Hermes schedule is independent.** Alex cannot add/remove/modify Hermes crontab entries.
2. **Hermes results are immutable.** Alex reads Hermes results but cannot edit them.
3. **Disagreement is preserved.** If Hermes DISAGREES with Alex's synthesis, BOTH views are presented in the CIO artifact. Alex does not cherry-pick evidence.
4. **No self-scoring.** Alex cannot claim higher confidence based on Hermes agreement; Hermes is a challenger, not a validator.
5. **HermesChallengeQueue is the interface.** All Alex-Hermes interaction flows through the HermesChallengeQueue (P-1.9) — no direct Hermes invocation.
6. **Hermes has its own model routing.** Hermes uses its own LLM lanes (Grok, ChatGPT, DeepSeek) for research. Alex's governed bridge is separate.

---

## 7. CIO Synthesis Integration

When Alex synthesizes a CIO run that involves Hermes challenges:

1. **Evidence section**: Cite Hermes challenge results alongside deterministic Trade AI evidence
2. **Agreement section**: Record AGREE/DISAGREE/INCONCLUSIVE/UNAVAILABLE per challenge
3. **Disagreement section**: If DISAGREES, present both perspectives:
   - CIO position (Alex synthesis + specialist evidence)
   - Hermes counter-evidence (challenge result)
   - Operator action: "You must decide between these views"
4. **Confidence adjustment**: If Hermes DISAGREES, Alex's confidence should reflect the unresolved conflict
5. **Run artifact**: Links to all Hermes challenge IDs and results

---

## 8. Optional Independent Reviewer (OpenAI/ChatGPT)

An optional external independent reviewer (OpenAI/ChatGPT) may be used for additional challenge diversity, ONLY if:

1. A separately approved registered route exists in the process registry
2. The route is explicitly enabled by operator configuration
3. The cost falls within the global daily cap

**Current status: DEFERRED_NOT_PROVEN.** No separately approved registered route exists for external review. If absent at runtime, the independent reviewer is not used. Never fall back to unregistered paid-model routes.

---

## 9. Hermes ↔ CIO Governance Boundary

| Concern | Owner | Notes |
|---------|-------|-------|
| Hermes scheduler (crontab) | Hermes (platform) | Alex CANNOT modify |
| Hermes research pipeline | Hermes (platform) | Independent research |
| Challenge request creation | Alex (via HermesChallengeQueue) | Write-through governed |
| Challenge result reading | Alex (read-only) | Cannot edit results |
| Disagreement handling | Alex (CIO artifact) | Must preserve, not suppress |
| Challenge queue integrity | HermesChallengeQueue (P-1.9) | Event-sourced, hash-chained |
| Hermes model routing | Hermes (own lanes) | Grok, ChatGPT, DeepSeek |

---

## 10. Cost Consideration

Hermes research has its own cost model outside Alex's CIO run budget. Alex's Hermes challenge budget (max_hermes_challenges per run) controls how many challenges Alex can request. The actual Hermes research cost is tracked in Hermes' own consumption tracking, not Alex's run budget.

Alex's daily $0.25 cap is NOT reduced by Hermes research costs. Hermes costs are tracked independently.
