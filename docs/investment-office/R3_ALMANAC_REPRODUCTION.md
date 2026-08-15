# R3 Almanac Reproduction

Governed Stock Almanac reproduction (RGA-15).

- Public STA investor-alert citations only (title / URL / date).
- No book pages, no newsletter body.
- Three layers never collapsed: source claim → Trade AI reproduction → current application.
- Calendar claims challenged as a **family** (STW / White Reality Check), not winner-only.
- 2026 is a mechanical `midterm_year` (`year % 4 == 2`). `partisan_conclusion` is always null.
- August is **not** hardcoded bearish; it enters the weak-month set only from stats.
- Influence cap ≤10% language. Never a standalone sell. Never creates TRIM.
- Fixture: `tests/fixtures/us_equity_monthly_sample.csv` (deterministic, not a vendor print).

Module: `scripts/lib/research_governance/almanac.py`
