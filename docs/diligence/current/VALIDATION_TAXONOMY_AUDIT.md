# Validation Taxonomy Audit

**Status: PASS** | files scanned: 34 | violations: 0  
_Generated: 2026-06-29T02:48:13.921189+00:00_  
_Source: `python3 scripts/audit_validation_taxonomy.py --json`_  

Operator-facing lifecycle term is **validation**. Forbidden operator-facing phrases: `paper fast path`, `paper approval`, `paper sample`, `paper-ready`, `paper maturity`, `paper submit`, `paper-only`.

Allowed legacy contexts: DB table names (paper_trades, paper_trade_proposals); adapter/module names (proposal_paper_submitter, paper_trade_logger, momentum_scalp_paper_fast_path); alpaca_paper account identifier; explicit legacy/alias/deprecated lines.

## Violations

None — operator-facing docs/config/reports use validation taxonomy.

> Operator-facing taxonomy is VALIDATION. Legacy paper_* names are allowed only as documented storage/adapter/compat aliases.

