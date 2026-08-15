# Book & Research Knowledge — Inventory (PR-R1)

Source registry + existing-code map + gaps. This document is informational; it
does not grant authority and does not claim any full text has been read.

## Source registry

Canonical machine-readable seed: `config/cio_research_source_catalog.json` and
`scripts/lib/research_governance/source_catalog.py`.

- Original ten: Malkiel, Graham/Zweig, Housel, Bogle, Ferri, Thau, Harris,
  McMillan, Natenberg, Aronson.
- Additional institutional canon (10): López de Prado (AFML), Ilmanen,
  Grinold/Kahn, Damodaran, Marks, Hull (derivatives mechanics), Tuckman/Serrat
  (fixed income), Lo (Adaptive Markets), Schilit/Perler (Financial Shenanigans),
  **Expectations Investing (Rappaport & Mauboussin)**.
- Separately governed practitioner/seasonality source: **Stock Trader's
  Almanac** (special calendar governance; not a substitute for institutional
  book #20).
- Primary research (13): White (2000), Sullivan/Timmermann/White (1999),
  Sullivan/Timmermann/White calendar-effects (2001), Bailey/López de Prado
  (2014), Bailey/Borwein/López de Prado/Zhu (2017), Harvey/Liu/Zhu (2016),
  López de Prado CPCV (2017), Kyle (1985), Amihud (2002), Lee/Ready (1991),
  Almgren/Chriss (2001), Corwin/Schultz (2012), Harvey (2017).

Total canonical catalog: 20 institutional books + 1 practitioner source + 13
primary research papers. `source_catalog.py` enforces an exact expected-ID
manifest with a parity/hash check; a missing or duplicate ID fails RGA-1.

`full_text_status` is `NOT_FOUND_IN_FILE_LIBRARY` for every current source, and
each such source carries `claim_status=SOURCE_CLAIM_INCOMPLETE`. The validator
checks STATE/PROVENANCE coherence (status matches the evidence), not permanent
absence: a source that later acquires lawful full text must instead provide a
location/reference, source hash, permitted license class, and `verified_at`.

## Existing-code map (what already exists in the repo)

- CIO advisory lifecycle: `scripts/lib/cio_*.py` (run store, dispatcher, worker,
  action ledger, outcome store, evidence ref) — Phases 0–10.
- Retrieval/knowledge engines (OFF-LIMITS until R4): `scripts/rag_retrieval.py`,
  `scripts/lib/advisory/kb_lessons.py`, `scripts/agent_runtime/knowledge.py`,
  `scripts/lib/hermes_research_backend.py`.
- Seasonality engine (OFF-LIMITS until R4): `scripts/lib/cio_seasonality_engine.py`.
- Strategy knowledge (OFF-LIMITS until R4): `scripts/lib/cio_strategy_knowledge.py`.

## Gaps this subsystem closes

1. No registry of **all attempted variants** (losers included) → `trial_registry.py`.
2. No explicit **OOS consumption** semantics → `trial_registry.py` + `models.OOSWindow`.
3. No **DSR / PBO / Reality Check / multiple-testing** governance layer →
   `deflated_sharpe.py`, `pbo.py`, `bootstrap_reality_check.py`, `multiple_testing.py`.
4. No **purged/embargoed CV** discipline → `cv.py`.
5. No **promotion ladder** separating research lifecycle from release acceptance →
   `promotion_gate.py` (RG-*) vs `acceptance.py` (RGA-*).
6. No **retrieval contract** → `retrieval_contract.py` (adapter-first; wiring to R4).
7. No **scope guard** enforcing branch-safety → `pr_scope_guard.py`.

## What is NOT in R1

R2 (fixed-income/ETF/valuation mechanics), R3 (Almanac reproduction, RGA-15),
and R4 (live integration into Alex/Advisory, RGA-16) are deferred. No shared
CIO/retrieval file is modified in R1.
