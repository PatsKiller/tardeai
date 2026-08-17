# Factor / overlap model

Detects when several holdings represent essentially the same economic bet.

## Loadings

Every loading must carry `factor`, `loading`, `method`, `window`, `as_of`,
`quality`, and a governed `source`. Sources: `verified_regression`,
`approved_vendor`, `explicit_etf_lookthrough`, `sector_industry_mapping`,
`duration_credit_characteristics`. Unsupported → `UNAVAILABLE`.

## Similarity components (transparent, not one magic score)

- Holdings overlap (Jaccard + overlap by weight)
- Return correlation (Pearson; insufficient history → `UNAVAILABLE`)
- Sector overlap (overlap by weight)
- Factor-vector similarity (cosine over shared sourced loadings)

Theme exposures never double-count as mutually exclusive allocations, and
theme overlap is kept distinct from GICS/industry overlap.
