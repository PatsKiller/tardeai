# SP-2C Other Proposal Creation Paths Review

## All Paths Found

| # | File | Function | Wired | Notes |
|---|------|----------|-------|-------|
| 1 | auto_proposal_generator.py | create_auto_proposal | Yes | Primary screener→signal→proposal path |
| 2 | incubator_proposal_promoter.py | promote loop | Yes | Incubator→proposal promotion |
| 3 | paper_trade_logger.py | create_paper_proposal_from_scan | Yes | Manual scan-based creation |
| 4 | paper_trade_logger.py | create_paper_proposal_from_signal | Yes | Manual signal-based creation |

## No Other Paths Found

- No API endpoint creates proposals without going through one of these 4 functions
- `/api/v2/paper-proposals/from-signal` calls paper_trade_logger
- `/api/v2/paper-proposals/promote-from-incubator` calls incubator_proposal_promoter

## Deferred Paths: None
