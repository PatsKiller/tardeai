# 08 · Memory Influence Path — from 0 % to > 80 % without an unsafe loop

```
Status:      PROPOSED
as_of:       2026-09-27T18:00:00-04:00
Measured at: 8f2a178d5 (origin/main) / served 8f2a178d5-main-exact-phase2-20260927-171004.
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0 remains the unconditional rail; this document
             changes what memory may shape in COGNITION and ADVICE, never in broker behaviour.
Package:     cognitive_transformation_20260927 — read 00 first.
Answers:     operator brief §8 (shadow → advisory → weighted → enforced; > 80 % influence safely).
```

## 1. Two flags, one rail

`MEMORY_BEHAVIOR_INFLUENCE` (MBI) is 0 everywhere by design `[DOC-CLAIM: 09-27 §1]`; a latent `=1`
drop-in existed and was shadowed `[DOC-CLAIM: 09-26 audit]`. AGENTS.md distinguishes `MBI_COGNITION`
(what the agent thinks and advises) from `MBI_BEHAVIOR` (sizing, orders, stops, weights, broker writes),
and the CIO future-state doc targets `MBI_COGNITION=1` with `MBI_BEHAVIOR=0` `[DOC-CLAIM: CIO_FUTURE_STATE_FULL_MATURITY]`.
This document is the graduated path for **cognition**. The behaviour rail is not weakened by any mode
below, and the operator's list in the brief (allocation, risk, holdings) is read as *allocation advice,
risk advice, holdings reviews*: the outputs the platform already produces as READ_ONLY_ADVISORY.

**Challenge to "MEMORY_BEHAVIOR_INFLUENCE = 0".** Zero is the safe value for behaviour and the wrong
value for cognition. A platform whose memory never shapes what it says is not safer; it is a platform
that repeats itself (seven producers) and contradicts itself (128k candidates) with confidence.

## 2. The four modes, defined by what memory may do

| Mode | Memory may … | Memory may not … | Receipt field |
|---|---|---|---|
| **Shadow** | be consulted and logged; a counterfactual "what memory would have said" is computed and stored | change any output | `influence.mode=SHADOW, consulted=true, changed_decision=false` |
| **Advisory** | appear in the output as a named section ("memory says …", with lineage) and set flags (`RECONSIDER`, `CONTESTED`, `STALE`) | change the primary stance or ranking | `mode=ADVISORY` |
| **Weighted** | contribute a bounded weight to stance, ranking, question choice or research priority (default cap 0.35 of the score); block generation on `HIT_FRESH` (03) | override evidence-derived verdicts alone; touch behaviour fields | `mode=WEIGHTED, weight=…` |
| **Enforced** | be required: a decision that ignores a promoted lesson, an open contradiction or a fresh contrary fact is refused and re-queued with the reason | still never touch `BEHAVIOR_FIELDS` | `mode=ENFORCED` |

Modes are **per surface × per silo**, stored in `config/memory_influence_policy.json`
(`DataSourceAuthority`-style approval record per row), read by the façade (01), never by a caller
directly. A mode change is an operator approval item (13). Rollback of any mode is one config row.

## 3. Per-surface ladder

| Surface | Today `[DOC-CLAIM]` | W1 | W2 | W3 | W4 | W5 target |
|---|---|---|---|---|---|---|
| Research (question choice, retrieval, refresh) | fingerprint reuse only | shadow | weighted (03 enforced: HIT_FRESH answers from record) | enforced | enforced | enforced |
| CIO decisions / advice (wake dispositions, views) | MBI=0; beliefs written, few consumed | shadow (counterfactual per wake) | advisory | weighted | weighted | enforced where divergence budget holds |
| Watchlists (directives, refresh priority) | thesis attach fail-soft | shadow | advisory | weighted | enforced | enforced |
| Holdings reviews | raw `hermes_external_research` | shadow | advisory (GIR section on the card) | weighted | weighted | enforced |
| Options advisory (thesis gate, CIO review) | M2 prior decisions behind a flag | shadow | advisory | weighted | weighted | weighted (options stay one step behind CIO) |
| Allocation advice (proposals, sizing *suggestions* in advisory text) | none | shadow | advisory | advisory | weighted | weighted |
| Risk advice (invalidations, contradiction flags) | none | shadow | advisory | enforced (contradiction/staleness vetoes) | enforced | enforced |
| Behaviour (sizing, orders, stops, weights, broker) | **0** | **0** | **0** | **0** | **0** | **0** |

## 4. Measurement — what ">80 %" means and how it is computed

**Memory Influence Rate (MIR)** per surface = decisions/advice outputs whose receipt shows
`consulted=true AND mode ∈ {ADVISORY, WEIGHTED, ENFORCED} AND memory content is present in the output`
÷ all outputs on that surface. Target ≥ 0.80 platform-wide by W5 exit, with Research and Risk
expected near 1.0 and Behaviour fixed at 0 by rail.

Companion measures (all from receipts; the shadow measure lane `cio-memory-shadow-measure` already
computes cross-agent agreement `[CODE]`):
- **Divergence** = outputs where memory's counterfactual disagrees with the evidence-only output.
- **Outcome delta** = settled-outcome accuracy of memory-influenced vs evidence-only outputs (matched
  by subject and horizon).
- **Regret** = influenced outputs later contradicted by a settled outcome or adjudication.

## 5. Promotion and demotion criteria (per surface × silo)

| From → To | Requires (all measured over the window) | Window |
|---|---|---|
| Shadow → Advisory | ≥ 200 receipts (or 30 days); compliance (01 §6) ≥ 0.95; divergence explained (no unbounded class); 0 behaviour-field touches | 30 d |
| Advisory → Weighted | outcome delta ≥ 0 with n ≥ 50 settled; regret ≤ 5 %; calibration error not worse | 30 d |
| Weighted → Enforced | outcome delta > 0 at 95 % confidence, n ≥ 100; regret ≤ 2 %; contradiction adjudication live (03 §6); conformance (05) CONFORMANT | 60 d |
| any → previous (automatic demotion) | regret > 2× threshold, or divergence budget exceeded (§6), or compliance < 0.90, or a receipt shows a behaviour field touched (also a P0 page) | immediate |

Promotion is proposed by the audit and approved by the operator; demotion is automatic and reported.

## 6. Safeguards against unsafe feedback loops

1. **Outcome-gated learning.** Memory learns only from *settled outcomes* (belief writer on the sweep),
   never from its own influenced outputs. An influenced decision cannot become a "confirming outcome"
   for the fact that influenced it until an external outcome settles (`LEARNED_FROM` edges point to
   `OUT:`, never `DEC:`).
2. **Provenance separation.** Every output section is labelled memory-derived or evidence-derived; the
   context (01) carries both; the view must cite both. A memory-only stance is `UNSUPPORTED` until
   evidence exists (the `no_match` shelf-life rule generalised).
3. **Contradiction veto.** In Weighted/Enforced modes an open contradiction on the fact blocks its
   weight (it is advisory only) until adjudicated.
4. **Staleness veto.** A fact past `next_due` contributes no weight; it contributes a `STALE` flag and a
   research request (03).
5. **Operator turn priority.** An operator statement on the subject outranks memory weight (AGENTS.md
   §7); it appears in the context and the output first.
6. **Diversity floor.** At most `1 − fresh_evidence_quota` (default 0.65) of a decision's cited inputs
   may be memory-derived; the rest must be evidence newer than the last decision on the subject —
   prevents a closed loop of the platform citing itself.
7. **Divergence budget.** If memory-influenced outputs diverge from evidence-only outputs on more than
   X % of a surface's decisions in 7 days (default 20 %) without matching outcome improvement, the
   surface demotes one mode and pages L4.
8. **Kill switch.** `MEMORY_INFLUENCE_GLOBAL=SHADOW` in the policy file drops every surface to shadow
   in one write; the façade re-reads policy per context open.
9. **Independent measurement.** The MIR/divergence/regret report is produced by the audit lane, not by
   the silo (producer ≠ reviewer ≠ scorer).
10. **The behaviour rail** is tested by a hermetic gate (the 09-21 plan's E4-style test: a synthetic
    memory that "wants" a size change must produce a `BehaviorWriteRefused`), registered in
    `run_cio_hardening_ci.py` GATES.

## 7. What memory influences on each surface (the operator's list)

- **Research** — which question is asked next (ladder MISS first), what is *not* asked again, what
  the delta prompt says changed, which contradiction must be addressed.
- **Allocation (advice)** — the proposal text names prior decisions and their outcomes on the subject,
  the promoted lessons that apply, and the confidence; weighting shapes ranking among proposals, never
  size.
- **Risk (advice)** — invalidation conditions and contradictions surface as vetoes and flags.
- **Holdings** — the review card leads with what changed since the last review (episodic), not a fresh
  analysis.
- **Watchlists** — directive priority and refresh cadence reflect freshness and contested state.
- **Options (advisory)** — the thesis gate pins the version it read; prior options decisions on the
  underlying are cited.
- **CIO decisions** — dispositions must honour prior dispositions (M5), promoted lessons and open
  contradictions; the counterfactual is stored for every wake from W1.
