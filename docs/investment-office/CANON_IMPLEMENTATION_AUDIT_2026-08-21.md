# Investigation Report: Canonical Investment Frameworks — Claimed vs Actual

**Date:** 2026-08-21  
**Authority:** READ_ONLY_ADVISORY  
**Scope:** `/home/johnclaw/tradeai-wt-cio-iic-d` + CURRENT `b04f0016` (same `research_governance` tree)  
**Method:** Uncharitable code/path audit. Catalog ID ≠ implementation. Library ≠ trade gate. Prompt mention ≠ decision influence.  
**Operator choice:** Full evidence audit report → land as docs PR after approve.

**Global fact (gates everything):**  
`config/cio_research_source_catalog.json` marks Core Ten + AFML + Ilmanen as:

```text
full_text_status: NOT_FOUND_IN_FILE_LIBRARY
claim_status: SOURCE_CLAIM_INCOMPLETE
```

Research governance explicitly: methodology books **may block research promotion**; they **can never generate a trade** (`docs/investment-office/RESEARCH_GOVERNANCE.md`).

---

## Part 1 — Architecture Scorecard

| Framework | Documented | Implemented (code) | Influencing decisions | Score (0–5) | Confidence |
|-----------|------------|--------------------|----------------------|-------------|------------|
| **Malkiel** Random Walk | Yes (catalog + R7 frame) | Citation pack only | **No** trade gate | **1** | H |
| **Graham** Intelligent Investor | Yes (catalog) | Tags / PE display | **No** MoS/intrinsic gate | **1** | H |
| **Housel** Psychology of Money | Yes (R7 citation-only) | CONTEXT_MODIFIER | Soft disposition/FOMO sizing only | **1.5** | H |
| **Bogle** Common Sense | Yes (catalog + IPS index holdings) | Index as holding/benchmark | **No** “why better than index” gate | **1.5** | H |
| **Ferri** ETF Book | Yes (incomplete claim) | `mechanics/etf.py` TE/premium/CU | Research/CIO context if NAV; not AP arb | **2** | H |
| **Thau** Bond Book | Yes (incomplete; code cites Tuckman) | `mechanics/fixed_income.py` duration/DV01/convexity | Prose/screener; not FI optimizer | **2** | H |
| **Harris** Trading & Exchanges | Yes (catalog + docs) | Spread% gates; T1 VPIN **OFF**; L2 scaffold | Spread blocks promo/options; **not** ranking | **2** | H |
| **McMillan** Options Strategic | Catalog only | — (unattributed engines) | Options engines use IV/Greeks **without** McMillan | **0 as McMillan / 3 as practice** | H |
| **Natenberg** Vol & Pricing | Catalog only | — (unattributed) | Skew/IV-rank in engines; not Natenberg doctrine | **0 as Natenberg / 3 as practice** | H |
| **Aronson** Evidence-Based TA | Prose “blocks weak promotion” | No Aronson module; DSR/PBO/RC stand in | Gates **research facts**, not live ranking | **2** | H |
| **de Prado** AFML | Catalog + real libs | purged CV, CPCV, DSR, PBO | Research promotion ladder; **no** meta-labeling; not orders | **3** | H |
| **Ilmanen** Expected Returns | Catalog only | — | **No** risk-premia allocator | **0.5** | H |

---

## Part 2 — Malkiel

| Question | Finding |
|----------|---------|
| No-edge identification | **Weak.** Zone/RSI WAIT/AVOID ≠ EMH “no edge.” |
| Benchmark self-comparison | Display/RS vs SPY exists; **not** CIO active-rec gate. |
| When indexing superior | **No** Bogle/Malkiel gate. |
| Penalize forecast overconfidence | Agent calibration score exists; **not** operator/forecast humility on product path. |
| Prediction vs probability vs uncertainty | IIC uses `DATA_UNAVAILABLE` honesty; no calibrated probability engine on reentry. |

**Verdict:** Documented aspiration. **Not embedded** in CIO product/reentry.

---

## Part 3 — Graham

| Question | Finding |
|----------|---------|
| Explain undervalued | Street-target / narrative prose only. |
| Track intrinsic value | Options ITM math ≠ Graham IV; reverse-DCF lite narrative; Damodaran mechanics research-only. |
| Speculative vs Investment | Strategy enum `speculative_growth` ≠ Graham doctrine. |
| MoS violation detection | **Absent** as gate on reentry/opportunity. |

**Hot path:** `derive_intel_state` = price vs zone + RSI band. **Zero** PE/MoS/quality valuation requirement.

**Verdict:** Multiples **shown**; almost never **required**. Graham is a shelf label.

---

## Part 4 — Housel

| Bias | Status |
|------|--------|
| Loss aversion (named) | **Absent** |
| Disposition effect | **PARTIAL** — shadow advisory (`behavioral_detection.json` SHADOW; Rule 2 disabled) |
| Recency bias | **Absent** |
| Overconfidence | Wrong object (agent calib), not operator bias |
| FOMO | **Sizing haircut** only (`fomo_penalty` in inference layers) |
| Narrative bias | **Absent** as detector |

Feedback journal → continuity blurb + NEED_DATA enqueue; **does not** re-score books. R7: behavioral = `CONTEXT_MODIFIER`, never standalone sell.

**Verdict:** Citation theater + thin heuristics ≠ Housel implementation.

---

## Part 5 — Bogle

- IPS/core_index may **hold** SPY/VTI/SCHD.
- RS vs SPY used for relative strength / Hermes sector factor.
- **No code gate:** “Why is this better than just owning the index?” before active recommend.
- Freeform *can* chat comparisons; nothing **blocks** without an answer.

**Verdict:** Index is a **holding/benchmark**, not a **recommendation hurdle**. Bogle not implemented as discipline.

---

## Part 6 — Ferri / ETF

| Capability | Status |
|------------|--------|
| Premium/discount vs official NAV | Mechanics + CIO research context (UNAVAILABLE without NAV) |
| Tracking error | Mechanics golden-tested |
| Creation/redemption | `creation_unit_notional` only — **no** AP basket/arb |
| Leveraged/inverse decay | **Absent** in mechanics |
| Treat ETF like stock? | Often yes on equity reentry/opportunity path |

**Verdict:** Partial mechanics library; **not** Ferri-faithful ETF intelligence on portfolio decisions.

---

## Part 7 — Thau / Fixed Income

- Real: `macaulay_modified_dv01_convexity`, FRED T10Y2Y/BAA10Y catalogs.
- Weak: LLM prose, bond ETF screener labels; **no** live duration/credit portfolio optimizer.
- AIF financial-senses often shadow-off.

**Verdict:** Partial research mechanics; thin portfolio coupling.

---

## Part 8 — Harris (Highest Priority)

| Capability | Status |
|------------|--------|
| Spread% block promotion/options | **Yes** when spread present |
| Liquidity alone downgrade ranking | **No** — not in Hermes weights / opportunity book |
| `evaluate_liquidity_eligibility` | **Defined but never called** on multi-setup router producers |
| Order book / L2 | Scaffold / conserving |
| Adverse selection / VPIN / T1 | **`t1.enabled: false`** — hard OFF |
| Execution quality rules | Explicitly **non-gating** analytics |
| “Good idea, impossible execution” | **Not** a first-class CIO downgrade on reentry desk |

**Verdict:** Crude spread/ADV screens ≠ Harris. Microstructure rigor is **dormant**.

---

## Part 9 — Options (McMillan / Natenberg)

- **INFLUENCING** as industry practice: IV rank mins, Greeks, skew25, credit-spread/CSP engines (`options_engine.py`, lifecycle, desk).
- HV/IV–HV gates **weak** in options_pipeline.
- **Zero** McMillan/Natenberg attribution or doctrine modules.
- Equity CIO reentry/opportunity largely **ignore** options surface.

**Verdict:** Options **practice** exists; **named canon** does not. Uneven HV rigor.

---

## Part 10 — Aronson (Critical)

| Question | Finding |
|----------|---------|
| New ranking model validation | YAML/heuristic weights common; RG ladder for **research evidence** promotion |
| False discovery prevention | DSR/PBO/White/BH in `research_governance` — **when** used on governed facts |
| Signal retirement | Research-fact degrade/retire; **not** Aronson TA-signal retirement on live ranking |
| Live vs backtest | Edge-decay panels/analytics; **not** hard veto on CIO cards |

**Verdict:** Strong **library** for research facts. Day-to-day equity/CIO path is **not** Aronson-protected.

---

## Part 11 — de Prado

| Piece | Status |
|-------|--------|
| Purged CV / embargo / CPCV | Code + acceptance tests |
| DSR / PBO | Code; gate research promotion |
| Meta-labeling | **ABSENT** |
| Feature importance / probabilistic forecasts on CIO | **Absent** on product path |
| Walk-forward | Partial (CV + ad-hoc backtests) |

**Verdict:** Best-implemented **methodology** canon — still **research-promotion**, not portfolio authority. Incomplete vs full AFML (no meta-labeling).

---

## Part 12 — Ilmanen

No equity/quality/value/momentum/carry/vol **premia scoring engine** wired to CIO recommendations. Catalog ID only.

**Verdict:** Absent as decision doctrine. Narratives dominate over return-driver attribution.

---

## Part 13 — Autonomous CIO decision mix (code-path estimate)

| Bucket | % | Hot-path evidence |
|--------|--:|-------------------|
| Deterministic rules | **58** | `derive_intel_state`, `adjudicate_reentry`, `diff_products`, S1–S8 predicates |
| Static rankings / fixed weights | **12** | RSI bands, NEAR_PCT=3, SOURCE_RANK, hermes weights (parallel) |
| Heuristics / thresholds | **12** | Cash/concentration/rankΔ≥3, freeform regex |
| Fresh research | **7** | Rebuilds books; does **not** grant RE_ENTER |
| Historical memory | **4** | Lessons restrict; IIC continuity; MEMORY_BEHAVIOR_INFLUENCE≈0 |
| Autonomous discovery | **4** | Hermes/watch → queue feed |
| Agent collaboration / LLM | **3** | Freeform/plan enrich prose; S3/S7 “not re-ranked” |

**Uncharitable summary:** Hot path ≈ **zone + RSI + status-diff pager**, wrapped in IIC prose.

---

## Part 14 — Advisory agents

| Capability | Actual |
|------------|--------|
| Summarize | **Yes** — freeform/IIC/desk cards |
| Discover new opportunities | Partial — Hermes/screeners/queue; not Graham/Ilmanen discovery |
| Challenge / invalidate theses | Weak — NEED_DATA + feedback continuity; no adversarial review loop |
| Blind spots / alternative explanations | Not systematic |
| Framework injection (Graham/Bogle/Harris) | **Absent** from desk/freeform prompts |

Agents largely **summarize and route**; they do **not** run canon-grounded investigation as a required step.

---

## Autonomous CIO Score (0–10)

| Dimension | Score | Note |
|-----------|------:|------|
| Research | 5 | Hermes + RG libs; incomplete claims |
| Memory | 3 | Continuity/journal thin vs compounding |
| Reasoning | 4 | Deterministic + LLM prose |
| Discovery | 4 | Screen/Hermes; not premia discovery |
| Portfolio Management | 4 | Concentration/cash/IPS thin |
| Feedback Learning | 2 | Continuity ≠ preference learning |
| Explainability | 6 | IIC + DATA_UNAVAILABLE honesty |
| Cross-Agent Coordination | 3 | Soft; books not re-ranked by agents |

---

## Top 25 gaps (claims vs reality)

1. Canon “institutional_canon” registered but **full text NOT_FOUND** / **SOURCE_CLAIM_INCOMPLETE**.  
2. Graham MoS **not** a reentry/opportunity gate.  
3. No intrinsic-value tracker for equities on CIO path.  
4. No speculative-vs-investment doctrine gate.  
5. Bogle: no “better than SPY/VTI/SCHD” **required** answer.  
6. Malkiel: no explicit no-edge / EMH regime detector.  
7. Housel biases mostly **absent** (recency, narrative, named loss aversion).  
8. Behavioral R7 **cannot sell**; disposition is SHADOW.  
9. Harris T1/VPIN **disabled**.  
10. Liquidity eligibility function **orphaned** on router.  
11. Liquidity **not** in ranking weights.  
12. No “good idea / bad execution” CIO downgrade class.  
13. Execution quality rules **non-gating**.  
14. Ferri: no leveraged-ETF decay model.  
15. Ferri: no creation/redemption arb engine.  
16. Thau: duration/convexity not portfolio governors.  
17. Ilmanen risk premia **absent**.  
18. Aronson not applied to live ranking models.  
19. de Prado meta-labeling **absent**.  
20. McMillan/Natenberg names unused despite options engines.  
21. Options surface largely ignored by equity reentry desk.  
22. Fresh research **annotates** but does not adjudicate RE_ENTER.  
23. Agent “collaboration” ≈ **3%** influence; books not re-ranked.  
24. Feedback journal adapts **copy**, not capital logic.  
25. IIC “FRESH_RESEARCH” provenance can label deterministic rank churn.

---

## Independent-auditor verdicts (uncharitable)

| Author | Would conclude |
|--------|----------------|
| **Malkiel** | You trade technical proximity, not humility about randomness. Missing no-edge discipline. |
| **Graham** | Valuation theater. No margin of safety. Speculative setups dressed as process. |
| **Housel** | Catalog citation ≠ behavior. Operator psychology barely instrumented. |
| **Bogle** | You hold indexes but do not force active ideas to beat them. |
| **Ferri** | Partial ETF math; treat many ETFs as stocks; leveraged decay missing. |
| **Thau** | Bond calculator shelfware relative to equity product engine. |
| **Harris** | Spreads sometimes; true microstructure OFF. Orphaned liquidity gates. |
| **McMillan** | Options desk exists without your doctrine branded or complete. |
| **Natenberg** | Some vol surface use; HV rigor uneven; not a vol-regime CIO. |
| **Aronson** | Good stats library for research facts; live signal factory still heuristic. |
| **de Prado** | Best student in the class — CV/PBO/DSR real — but incomplete (no meta-labeling) and walled off from orders. |
| **Ilmanen** | Return drivers not the language of recommendations. |

**Exemplary pockets (narrow):** research_governance statistical toolkit; options IV/Greek proposal gates; DATA_UNAVAILABLE honesty on IIC; READ_ONLY_ADVISORY discipline.

---

## Status

Landed as documentation-only audit (this file). Cross-linked from
`BOOK_KNOWLEDGE_INVENTORY.md` and system-state evidence index. **No runtime
code changes** in the audit PR.

### Optional follow-up Builds (not this audit)

| Priority | Build |
|----------|--------|
| P0 | Wire liquidity eligibility into ranking + CIO downgrade; enable/monitor T1 or delete dead claims |
| P0 | Index-hurdle field required before active recommend (Bogle gate) |
| P1 | Graham MoS / quality gate on opportunity+reentry |
| P1 | Apply RG promotion receipts to any new ranking weight change |
| P2 | Housel bias detectors beyond disposition; feedback→preference learning |
| P2 | Ilmanen premia tags on recommendations |
| P2 | Meta-labeling + signal retirement for live heuristics |

---

*End of investigation plan/report. Awaiting approval to land as docs.*
