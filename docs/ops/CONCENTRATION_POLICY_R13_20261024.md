# R13 concentration policy and source readers

Authority: operator decision 2026-10-24, Addendum 3 in the coordinator's
conflict-engine-build request and R13 table in EXCEPTIONS_MATRIX. The single
current key is `config/investment_policy_statement.json` →
`constraints.concentration_policy`. Broad diversified funds: 25%; narrow or
thematic funds: 12%; stocks: 12%; leveraged or inverse funds: 5%; look-through
company: 12%; look-through sector: 25%. The warning band starts at 90% of each
limit. Breach requires weight strictly greater than the limit.

`scripts/lib/ips_policy.py` reads that object. It supplies policy metadata,
instrument classification, a per-position assessment, a strict-GUID whole-book
assessment, and pure composition over `cio_truth.resolve`. Weights use the sum of
that GUID's holdings across accounts divided by the same portfolio total, cash
included. No account-filtered denominator or ticker-name inference is introduced.
Disagreeing account instrument facts produce an unknown class.

Fund evidence requires explicit leverage/inverse flags, source, as_of, complete
coverage, total holding count, largest holding and top-ten weight. Fewer than 30
holdings or top-ten weight above 50% is narrow. Otherwise 30–49 is narrow, with a
dated, attributed operator classification supported in the evidence object.
At least 50 and largest below 10% is broad. Unmatched or missing statistics stay
unknown. A sample length never supplies a fund's total holding count. The helper
does not fetch providers, repair caches or create a store.

The curator's trim condition now asks whether the held name exceeds its measured
class cap. A measured broad fund at 16.8% is within 25%, and 23% is in its warning
band; an explicitly typed stock at 22.6% breaches 12%. Missing class evidence
cannot manufacture a concentration trim and remains a named gap. Positions
context preserves raw type and evidence instead of guessing them.

`risk_gate` uses the IPS stock and sector source defaults, retaining existing
explicit environment overrides and account-policy controls. The source change
does not arm a lane, invoke the gate against live accounts, or place an order.
Missing default data does not substitute a number. Portfolio-facts and CIO policy
readers expose the same policy; historical captured legacy configs remain
readable only when they explicitly contain an old value.

The production fund cache inspected during this task had ten constituent rows
for SCHD and SCHG without total count, completeness or a dated full statement.
It cannot prove either broad class. The current SCHG sample also has a largest
weight above 10% and top-ten weight above 50%, so the example warning outcome
must not be claimed from that sample. Full evidence or a permitted recorded
operator classification is needed; no ticker exception was inserted.

W7 should compose `ips_policy.apply_concentration(cio_truth.resolve(...),
evidence_by_guid=...)` in its owned reader. The returned top-level
`concentration_policy`, per-name classifications, limits, warning bands, status
and gaps are display-ready. The legacy capital alert is labelled historical and
removed from current alert authority. W10 should use `policy_for_security` for
`context.concentration_policy`; its R13 gate and look-through coverage gates
remain engine-owned. W6 owns Advisory adoption. No additional conflict endpoint
or classifier is created here.

Validation uses deterministic fixtures, hidden-psycopg2 affected suites, the
four no-new-debt ratchets, lane registry, CIO completeness, docs inventory and
the native frontend build. A private copied-state composition checks unchanged
input fingerprints and reports actual classification gaps. Logs and exact
counts are kept in the local delivery receipt and PR description. No live gate,
provider, browser or runtime acceptance is implied by source checks.
