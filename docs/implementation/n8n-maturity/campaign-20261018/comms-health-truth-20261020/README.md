# Communications delivery health truth

Status: DRAFT — implemented locally; runtime unproven
as_of: 2026-10-20T15:15:00Z
Measured at: source `d1b209678311b5cec0d2981cfda8466b022c10df`; baseline `720fce06c09ca7e7c21224364ab789505be40f5a`

The health strip counted only the latest 500 delivery rows and treated unavailable data as zero. The replacement reads a versioned aggregate over all retained rows and displays its actual observation window. Failed refreshes keep last-good values explicitly STALE, with age; missing, malformed, incomplete or invalid-clock responses are UNAVAILABLE. A successful empty aggregate remains a valid zero.

Reuses the applicable Communications work from PR #1866 at `8dc305afec0718a595629ecdc47354b4b458f364`; extends it to consume the actual fetch hook stale flag. This change adds no send, acknowledgement, broker or n8n execution route. Other page panels retain their existing behavior.

`evidence.json` indexes lossless baseline/candidate browser receipts, targeted tests and format-only AST proof. The identical browser fixture produced four assertion failures and one passing control on baseline, then five passes on the candidate. A sandbox Chromium startup failure is preserved separately and does not count as red-first.

Local implementation only: independent review and complete exact-head acceptance are pending. No deployment, runtime grant, live database probe or business-output proof is claimed. Old already-loaded UI clients need a refresh to gain these semantics.

Independent review identified a fixture clock race: two `Date` calls could straddle a millisecond boundary and violate the exact aggregation-window contract. The CI fixture now captures one timestamp for both fields. Frozen baseline/candidate evidence is unchanged; this correction changes no production code.
