# Factor / overlap model

Detects when several holdings represent essentially the same economic bet.

## Loadings

Every loading must carry `factor` (the mapping key), `loading`, `method`,
`window`, `as_of`, a validated `quality`, and a governed `source`. Sources:
`verified_regression`, `approved_vendor`, `explicit_etf_lookthrough`,
`sector_industry_mapping`, `duration_credit_characteristics`. A record missing
any required metadata is `UNAVAILABLE` — never a partially-fabricated loading.

## Fact promotion (governed, not asserted)

`holdings_jaccard` is a `ModelEstimate` (derived, `MODEL_INFERENCE`) unless
both instrument inputs carry a **validated upstream provenance envelope** —
`provenance` with a fact-capable `source_type`, immutable `source_ids`,
`READ_ONLY_ADVISORY` authority, and validated `quality` + `as_of`. A bare
caller-supplied `source_type`/`as_of`/`quality` is asserted metadata and can
never mint an `APPROVED_MARKET_DATA` Fact. Raw request holdings/factors stay
`ModelEstimate`.

## Similarity components (transparent, not one magic score)

- Holdings overlap (Jaccard + overlap by weight)
- Return correlation (Pearson; insufficient history → `UNAVAILABLE`)
- Sector overlap (overlap by weight)
- Factor-vector similarity (cosine over shared fully-specified loadings)

Theme exposures never double-count as mutually exclusive allocations, and
theme overlap is kept distinct from GICS/industry overlap.
