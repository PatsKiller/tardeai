# Approved Home v007 additive data contract

`GET /api/v2/market-risk/latest` gains optional `home_v007: HomeMarketRiskContext@v1`. Existing fields keep their contracts. The STOPPED-OUT NOW hotfix (`ReentryRegularQuote@v1` / `PgReader.regular_session_quotes`) ships separately FIRST; this reader extension never changes confirmed stage bars.

- `symbols[SYMBOL]`: `quote`, `day_change`, `since_exit`, `analysis_references`, guarded `headlines`, `next_event`, canonical `cio`, `conviction`, separate `market_risk_stance`, `volume_vs_20d`, `since_exit_history`.
- `positions[]`: existing symbol/account label, observed quote/day change, account-percent denominator, stored-stop distance and captured source. A missing read differs from a successful read with no stored stop. Distances describe existing records; no stop is created, changed or recommended.
- `risk`: existing score history/current delta, all nine canonical category chips, and next declared evaluation. The time comes from the existing DST-safe registry schedule reader; it is explicitly a declaration, not proof that the scheduler is installed or will succeed.
- `hedge`: existing exposure/lagging trigger progress, using the SAME existing Defense values/thresholds and momentum source clock; observed inverse-fund moves, never a suggested position/order.
- `budgets[]`: existing measurement, plain breach/clear condition, and exact `source_binding={as_of,sha256}` over account label/budget/actual/limit/unit/as_of. This binds a future operator-only presentation decision; it grants no authority.
- `gaps[]` and `read_errors[]`: source/field members with stable HOMEV007 remediation keys. No sample values fill a source gap. Raw database diagnostics are not echoed.

Exit-only facts for symbols outside the exited-symbol watch, and CIO facts for inverse quote-comparison rows only, are explicitly `not_applicable`; they do not generate false missing-instrumentation gaps.

Every measured fact carries `value`, `state`, `as_of`, `source`, `age_seconds`. Missing/unclocked/future data stays explicitly unknown with `reason` and `remediation`. Quote facts also carry session/session_date/expected_session_date/basis. A fresh canonical unavailable observation blocks cached old-session substitution; extended prints must belong to the active extended session.

Day change uses the preceding completed NYSE close; after-hours reference-close movement is never mislabeled the whole day's move. Since-exit/analysis-reference distances use existing exit/stage observations only. Volume compares the observed session volume with twenty PRIOR completed-session volumes; the result states sample dates and that it is not time-adjusted.

CIO stance/conviction uses the existing GUID-confirmed `cio_truth.stances_for_symbols` reader, including store/shadow label, stale flag and oldest material-input age. Deterministic market-risk advice remains separately labeled and never replaces a missing canonical CIO record. The registered stance projection does not expose a current-stance rationale; the UI receives an explicit source gap. Existing score history does not retain earlier category observations, so category-change prose likewise remains explicitly unavailable rather than invented.

Intentional budget decisions must use the existing operator-session + same-origin CSRF route, with explicit UTC expiry, actor/audit receipt and source binding. They are acknowledgment/temporary presentation snooze only: underlying breach truth and an Intentional-until/history record must remain visible. E owns that API implementation; until its reviewed subtype/readback is provided, this contract exposes `operator_decision.state=unavailable` with a remediation, never a fake functional button. No risk limit or policy is changed.

All sources are existing canonical read models/stores. The join creates a bounded read-only connection before its first query, closes it, and performs no broker/provider/model/notification calls or writes. Tests use synthetic prices/accounts/headlines and injected readers; the private portfolio mockup is never opened or committed.
