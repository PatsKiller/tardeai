# Evidence & Provenance — Trade AI Investment Office

> Canonical evidence spine for the converged investment office.
> Every material fact an agent or Alex (CIO) states must trace to an
> `EvidenceRef@v1` envelope. No LLM establishes portfolio facts; LLMs synthesize
> verified, sourced facts.
>
> **Financial authority: `READ_ONLY_ADVISORY`.** No broker/order/stop/2FA writes.
> This document is a mirror of runtime truth, not a second source of it.

---

## 1. The evidence envelope: `EvidenceRef@v1`

Defined in [`scripts/lib/cio_evidence_ref.py`](../../scripts/lib/cio_evidence_ref.py).
One envelope per material value/claim:

| Field | Meaning |
| --- | --- |
| `ref_id` | stable id for this ref |
| `domain` | registry evidence domain (see §3) |
| `symbol` / `account` / `scope` | what the fact is *about* (scope ∈ portfolio, sleeve, sector, symbol, account, household, none) |
| `source` | canonical file/DB/table path |
| `source_record_id` | record key within the source |
| `source_timestamp` | when the source record was produced (UTC ISO) |
| `observed_at` | when the office observed/read it |
| `freshness_state` | `FRESH` / `STALE` / `UNKNOWN` / `NOT_TIMESTAMPED` / `NOT_APPLICABLE` (temporal) |
| `quality_state` | `AVAILABLE` / `PARTIAL` / `STALE` / `DATA_UNAVAILABLE` / `CONFLICTED` / `ERROR` / `NOT_APPLICABLE` (semantic) |
| `deterministic_calculation_version` | version of the deterministic calc that produced the value |
| `value_hash` | sha256 of the value (canonical JSON, key-sorted) |
| `limitations[]` | explicit caveats; never left empty when the value is partial/proxy |

`freshness_state` and `quality_state` are **deliberately separate**: a fact can be
FRESH but PARTIAL (e.g. holdings-derived cash — timely, but not verified broker
buying power), or STALE but AVAILABLE (an old but complete tax lot).

Every ref is provider-call-free and side-effect-free. Value hashes are
deterministic; the same logical value hashes identically regardless of dict
order.

---

## 2. Quality gate: FACT → SOURCE → AGE → QUALITY → SPECIALIST → CIO

Every `InvestmentDecision` (and every report figure) must be able to render this
chain end-to-end. `render_chain()` in `cio_evidence_ref.py` emits:

```
FACT: {"symbol":"V","market_value":121k,"weight_pct":9.4} (h=…)
  -> SOURCE: data/portfolios/state/holdings.json
  -> AGE: 91s (FRESH)
  -> QUALITY: AVAILABLE
  -> SPECIALIST: Maria (Research Director)
  -> CIO: Alex
```

`gate_action()` fails closed: an absent required domain, or any ref whose
`quality_state` is blocking (`DATA_UNAVAILABLE` / `ERROR` / `STALE` / `CONFLICTED`),
blocks the action. Absence of evidence is never turned into a recommendation.

---

## 3. Domain coverage matrix

The 20 institutionally-required domains map onto the canonical
`config/cio_domain_capability_registry.json` (registry `1.0.0-gate-c`). Machine
check: `scripts/lib/cio_domain_coverage.py::domain_coverage_report()`.

Roll-up: **10 SUPPORTED, 4 PARTIAL, 1 BROKEN, 4 UNSUPPORTED, 1 NOT_DECLARED** (of 20).

| Required domain | State | Registry backing |
| --- | --- | --- |
| holdings_and_accounts | PARTIAL | portfolio ✅, holdings_detail ✅, transactions ✅, account_constraints ⛔ |
| cash_investable_reserved | SUPPORTED | cash_buying_power ✅, liquidity ✅ |
| tax_lots_cost_basis | PARTIAL | cost_basis ✅, tax_lots ⛔ |
| broker_reconciliation | SUPPORTED | broker_reconciliation ✅ |
| portfolio_performance | UNSUPPORTED | performance ⛔ |
| benchmark | **NOT_DECLARED** | *(none)* |
| risk_concentration_protection | PARTIAL | risk ✅, defense_stops_protection ⛔ |
| watch_intelligence | SUPPORTED | watch_intelligence ✅ |
| defense | UNSUPPORTED | defense_stops_protection ⛔ |
| rotation_sectors_industries | BROKEN | rotation 💥, sectors ✅, market_regime ⛔, industry_context ⛔ |
| reentry | SUPPORTED | reentry ✅ |
| analyst_actions | SUPPORTED | analyst_actions ✅ |
| fundamentals_valuation | UNSUPPORTED | fundamentals ⛔ |
| technicals_price_action | UNSUPPORTED | technicals ⛔ |
| catalysts_earnings_events | SUPPORTED | catalysts ✅ |
| hermes_research | SUPPORTED | hermes_research ✅ |
| income_dividends | SUPPORTED | income ✅ |
| model_portfolio_policy | SUPPORTED | model_portfolio ✅, investment_policy ✅ |
| cfo_liquidity_constraints | SUPPORTED* | liquidity ✅, cash_buying_power ✅ |
| cwo_wealth_goals | PARTIAL | retirement ✅, operator_profile ✅, goals ⛔ |

✅ SUPPORTED · ⛔ UNSUPPORTED (no adapter) · 💥 BROKEN (adapter produces wrong data)

### Known semantic gaps (adapter-present but not yet canonical)

- **`cfo_liquidity_constraints`*** — `liquidity` and `cash_buying_power` are
  SUPPORTED, but neither distinguishes **reserved cash** from **investable cash**.
  The CFO contract (§4 of the Executive Role Charter) requires
  `cash_reserved` / `cash_investable`; no canonical field exists yet. This is the
  Phase 2/6 CFO wiring task.
- **`benchmark`** — no benchmark domain is declared. Portfolio-vs-benchmark
  reporting cannot be source-proven until a canonical benchmark index/series is
  registered.
- **`fundamentals` / `technicals` / `performance` / `account_constraints` /
  `tax_lots` / `goals` / `market_regime` / `industry_context` / `defense_stops_protection`**
  — declared in the registry but UNSUPPORTED (no adapter wired). They resolve to
  `DATA_UNAVAILABLE` at collection time, honestly, rather than being fabricated.
- **`rotation`** — adapter is BROKEN (no `rotation_ladders.json` producer).
  Sector *weights* remain computable via `sectors` (SUPPORTED), but *leadership /
  regime* signals are unavailable until the rotation producer is repaired.

---

## 4. Permanent guards (regression-protected prior failures)

These nine defects were found and fixed in the 2026-08-12 data-integrity audit;
each has a regression test that must stay green. They are re-asserted here as the
constitution's permanent guards.

| # | Guard | Failure it prevents | Test surface |
| --- | --- | --- | --- |
| G1 | operator-intent labels never manufacture ADD/AVOID verdicts | watchlist `HTGC → ADD @0.50` from a human label | `test_advisory_desk_phase*` |
| G2 | aggregate portfolio evidence never inflates symbol-specific evidence counts | watchlist `ev 3` where all 3 were aggregate | `test_advisory_desk_phase*` |
| G3 | `INSUFFICIENT_DATA` cannot carry high action confidence | allocation rows at `0.70–0.75` | `test_advisory_desk_phase*` |
| G4 | watchlist data uses canonical current paths | CIO read a non-existent `data/watchlist/state/` path | `test_gate_d_evidence_gate` |
| G5 | duplicate agent evidence is deduped | GD showed 3 identical `agent_opinion` rows | `test_advisory_desk_phase7` |
| G6 | analyst score corruption is plausibility-gated | `recom_score 160.15` mis-stored as rating | `test_advisory_desk_phase*` |
| G7 | market-cap units are validated | `$104,926,140M` (millions stored as billions) | `test_advisory_desk_phase*` |
| G8 | price / 52-week fallback fields are source-correct | empty `1d` / `Off 52w` fields | `test_advisory_desk_phase*` |
| G9 | stale caches never appear current | freshness computed against thresholds | `test_gate_d_evidence_gate`, `cio_evidence_ref` |

`gate_action()` and `EvidenceRef` extend G2/G3/G9 structurally: evidence counts,
confidence, and freshness are now derived, never hardcoded.

---

## 5. Deterministic collection

`scripts/lib/cio_financial_snapshot.py` (`CIOFinancialSnapshot`) is the
deterministic collector. It:

- iterates the registry, collecting only SUPPORTED domains;
- marks BROKEN/UNSUPPORTED domains `DATA_UNAVAILABLE` (never fabricated);
- checks each domain's freshness against its registry threshold;
- seals an immutable snapshot with a content hash (domain states only, no wall-clock).

`scripts/lib/cio_evidence_spine.py` (`build_evidence_spine`) assembles the
operator-facing multi-domain spine (portfolio/cash/risk/holdings/catalyst/
technicals/hermes/thesis/learning).

---

## 6. Checkpoint 2 proof (live canonical state)

`scripts/cio_evidence_checkpoint2.py` reads the live `data/portfolios/state` and
produces 15 cases (5 held equities, 3 ETFs/funds, 3 watch names, 2 closed/re-entry,
1 cash-deployment, 1 sector-rotation), each a full `EvidenceRef` chain.

Observed on 2026-08-13 against the live state:

- **source_traceability: 100%** of refs carry a source and a deterministic value hash.
- **fabricated_fields: 0** — missing symbols resolve to `DATA_UNAVAILABLE`, never invented.
- Real findings surfaced, not hidden:
  - `cash_buying_power` is `PARTIAL` — holdings-derived, not verified broker buying power.
  - `rotation` is `DATA_UNAVAILABLE` — adapter BROKEN, no `rotation_ladders.json`.
  - **~30.9% of book is `Uncategorized`** sector — `sector_cache.json` lacks entries
    for large ETF/fund positions (SCHD/JEPI/BND/SPCX/DIV/DIVI).

---

## 7. Rules inherited from the constitution

- Numerical values are deterministic/source-backed. An LLM may only *choose among*
  deterministic admissible options, never invent a weight/dollar from prose.
- Any missing/stale/contradictory material evidence is surfaced explicitly as one
  of `DATA_UNAVAILABLE` / `STALE` / `PARTIAL_EVIDENCE` / `CONTRADICTORY_EVIDENCE` /
  `DEFERRED_FOR_RESEARCH`.
- No silent provider fallback; unknown caller/process/model fails closed.
- Report figures never print "clean" when the source is flagged inconsistent.
