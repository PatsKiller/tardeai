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
