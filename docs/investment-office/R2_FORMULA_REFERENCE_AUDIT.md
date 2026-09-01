# R2 Formula Reference Audit

Honest registry. Canon books (`thau_bond_book`, `tuckman_serrat_fixed_income`,
`ferri_etf_book`, `damodaran_on_valuation`, `expectations_investing_rappaport_mauboussin`)
are `SOURCE_CLAIM_INCOMPLETE` / `NOT_FOUND_IN_FILE_LIBRARY`. This file does
**not** claim exact book pages.

Machine-readable rows: `scripts/lib/research_governance/mechanics/references.py`.

Every mechanic records: formula, source ids + claim status, convention, units,
implementation file, golden test, known limitations.

Independent golden vectors are hand-computable closed forms (zero-coupon 1y
ACT/365, 2y par 30/360 US, Gordon TV, PE-free DCF identities). Finite-difference
checks corroborate DV01 and convexity.

Review status: `PASS` only when the matching golden test is green.
