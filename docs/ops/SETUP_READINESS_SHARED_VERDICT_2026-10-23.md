# SetupReadiness@v1 — one "driven by / ready / missing" verdict (2026-10-23)

**Why.** Operator 2026-10-23 08:54 ET, SAIQ: the Active Trader alert said *"catalyst: none found (Hermes researched
08:25 — no clear catalyst) · Verified catalyst: FAILED"*, while the Trade AI Opportunities row printed a Yahoo
headline as the catalyst. Both read the same scan row (`catalyst_verified=false`, `catalyst_confidence=0.0`,
`catalyst_source=yahoo_finance`); each surface rendered it its own way. Operator follow-up: every alert must say
what drove it, whether it is ready, and if not, exactly what is missing.

**What.** `scripts/lib/momentum_setup_evidence.py` (the single source) gains:

| Function | Returns |
|---|---|
| `catalyst_verdict(evidence.catalyst, hermes_record)` | `VERIFIED` · `HERMES_FOUND` · `UNVERIFIED_HEADLINE` · `NONE_FOUND` · `UNKNOWN`, with label, kept text, reason (scan verification + Hermes note with research time) |
| `setup_readiness(evidence, hermes=, veto_reasons=)` | `SetupReadiness@v1`: `status` READY / NOT_READY / UNKNOWN, `passed`/`required`, `driven_by[]` (value, rule, ✓/✗ per fact), `missing[]`, `blockers[]` (AT veto codes, reported not recomputed), `summary` |
| `format_readiness(readiness)` | Two plain lines: `Driven by: …` and `Ready: YES/NO — …` |

A headline is printed as *the* catalyst only when it is `SOURCE_VERIFIED`; otherwise it is kept and labelled
"unverified headline". "Ready" means all five source facts proven and no veto — never an approval or an order.

**Who reads it.**

- `GET /api/v2/trade-ai/scanner` — every actionable row carries `setup_readiness` (built from the row's own
  MomentumSetupEvidence@v1 block + today's Hermes record from the persistent state root).
- `lib/scanner_candidate_projection.py` — every Trade AI and Active Trader observation carries `readiness`
  (AT observations also carry `veto_reasons`).
- `lib/unified_momentum_alert.py` (Gate 4, shadow) — `render()` prints the two readiness lines and labels an
  unverified headline; the AT and social-scalp adapters attach the evidence block.

SAIQ at 08:52 renders: `Ready: NO — needs 5/5, has 4/5 · missing: verified catalyst: unverified headline — scan
marked it NOT verified (yahoo_finance, confidence 0); Hermes 08:25: no clear catalyst (no primary source)`.

Tests: `tests/test_setup_readiness_20261023.py` (gate `config/ci_gates/setup_readiness_20261023.json`).
