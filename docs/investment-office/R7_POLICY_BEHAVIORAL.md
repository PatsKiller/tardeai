# R7 — Policy / Regulatory + Behavioral Frameworks

Type-specific producers for gates that already exist on the R1 ladder.

**POLICY_OR_REGULATORY** requires authoritative source, jurisdiction,
effective date, and *computed* freshness (`verified_at` / `current_as_of` /
`next_reverify_at`). Missing any of those is `UNAVAILABLE`, not a guess.

**BEHAVIORAL_FRAMEWORK** is citation-only context (Housel / Marks / Malkiel
catalog ids). Influence is `CONTEXT_MODIFIER`. Never a standalone sell.
`partisan_conclusion` is always null. No book full text.

Authority: `READ_ONLY_ADVISORY`.
Modules: `policy.py`, `behavioral.py`
