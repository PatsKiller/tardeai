# Social Scalp Route Matrix

_Deterministic routing for social-discovery candidates. Implemented in
`scripts/social_route_policy.py::route_social_candidate`; covered by
`tests/test_social_route_policy.py`._

## Principles

* **Social-only remains WATCH / WAIT only.** An unverified social surge can never become a
  GO-style actionable alert (P0-2) and can never route to GO.
* **Verified catalyst + RVOL + micro-float can route to momentum_scalp** (GO eligible, still
  subject to every downstream risk gate and per-order operator confirmation / 2FA).
* **Large-float social squeeze routes to meme_squeeze_momentum / manual review** — never
  auto-GO.
* **No social signal can bypass risk gates. No LLM can unlock execution.** LLMs and social
  sentiment are advisory only.
* The existing operator confirmation / 2FA path is unchanged and out of scope.

## Routing matrix

| Condition | Route | Actionability | Reason code |
|-----------|-------|---------------|-------------|
| Income / retirement / dividend tag | `portfolio_agents` | MANUAL_REVIEW | PORTFOLIO_INCOME_TAG |
| Missing/stale Finviz or no RVOL/price | `watch_only` | WAIT | MISSING_FINVIZ_DATA |
| Verified + RVOL≥8 + gap≥5 + squeeze evidence | `meme_squeeze_momentum` | MANUAL_REVIEW | VERIFIED_SQUEEZE_SETUP |
| Verified + RVOL≥5 + float≤20M + price≤25 | `momentum_scalp` | **GO** | VERIFIED_MICROCAP_MOMENTUM |
| Verified + large float (>20M) + RVOL≥5 | `meme_squeeze_momentum` | MANUAL_REVIEW | VERIFIED_LARGE_FLOAT_MOMENTUM |
| Verified but price/float out of all bounds | `reject` | AVOID | OUT_OF_STRATEGY_BOUNDS |
| Social-only, meets scalp metrics | `watch_only` | WAIT | AWAITING_CATALYST_VERIFICATION |
| Social-only, otherwise | `watch_only` | WATCH | SOCIAL_ONLY_UNVERIFIED |

`requires_verified_catalyst` is true for every GO/scalp/squeeze route. **Unverified catalyst
can never reach GO** — verified by a metric sweep in the test.

## Return shape

```json
{ "route": "...", "actionability": "...", "strategy_id": null,
  "reason_codes": [], "requires_verified_catalyst": true, "social_only": false,
  "trace_id": "soc-YYYYMMDD-SYM-xxxxxxxx", "evidence": {} }
```

## Wiring + lineage (P0-5 + P0-6)

`scripts/social_scalp_scanner.py` computes the route per candidate, logs it, includes it in
the WS broadcast, and **suppresses any GO alert whose route is not GO** (social-only /
watch_only / manual-review can never fire a GO alert even at a high raw score). A stable
`discovery_trace_id` is generated per candidate and threaded scan → `scalp_scan_results` →
`trade_ai_scans` → `strategy_signals` → proposal → paper trade (additive migration
`scripts/migrate_discovery_trace_id.py`; degrades safely when columns are absent).

## Hybrid large-float social scout (2026-06-28)

A verified social/momentum name whose float is ABOVE the micro-cap ceiling (>20M) is **retained,
not discarded** — and clearly labelled so the operator never mistakes it for a standard
low-float momentum scalp.

| Condition | route | actionability | strategy_id | float_class | scout_label | operator_label |
|-----------|-------|---------------|-------------|-------------|-------------|----------------|
| Verified + RVOL≥5 + **float≤20M** + price≤25 | momentum_scalp | **GO** | momentum_scalp | micro_float | — | — |
| Verified + RVOL≥5 + **float>20M** + price≤50 | large_float_social_scout | MANUAL_REVIEW | large_float_social_scout | large_float | large_float_social_scout | LARGE FLOAT SOCIAL SCOUT |
| Verified + RVOL≥8 + gap≥5 + squeeze + float>20M | meme_squeeze_momentum | MANUAL_REVIEW | meme_squeeze_momentum | large_float | large_float_social_scout | LARGE FLOAT SOCIAL SCOUT |
| Verified + very large float + price>50 | portfolio_agents | MANUAL_REVIEW | — | large_float | — | — |
| Social-only (unverified), any float | watch_only | WATCH/WAIT | — | (per float) | — | — |

`route_social_candidate` now emits `float_class`, `scout_label`, `manual_review_required`, and
`operator_label`. Large-float scouts are **MANUAL_REVIEW**, carry `manual_review_required=true`,
are **never** routed to `momentum_scalp`, and are **never** eligible for the momentum_scalp paper
fast-path (the `large_float_social_scout` strategy is non-intraday by config, and the fast ATM
runner rejects any non-`momentum_scalp`/non-GO route). New config: `large_float_social_scout.yaml`.

### Durable persistence + route-aware injection
Route fields (`route`, `route_actionability`, `route_strategy_id`, `route_reason_codes`,
`catalyst_verified`, `catalyst_source`) are persisted on `scalp_scan_results` and `trade_ai_scans`
(additive migration `migrate_social_route_fields.py`). `continuous_runner` injects social
candidates **route-aware**, not by score: only verified micro-cap GO names enter the live scoring
path as tradeable; large-float scouts enter as labelled manual-review; social-only/watch names are
not injected. `strategy_signal_sync` enforces the durable route (and the float≤20M+verified
fallback) so a large-float or social-only candidate can never become a standard momentum_scalp signal.
