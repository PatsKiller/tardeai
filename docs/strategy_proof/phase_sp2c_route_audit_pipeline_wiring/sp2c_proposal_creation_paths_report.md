# Proposal Creation Paths

| File | Function | Source | Route Audit |
|------|----------|--------|-------------|
| scripts/auto_proposal_generator.py | create_auto_proposal | screener signals | wired |
| scripts/incubator_proposal_promoter.py | promote (main loop) | incubator candidates | wired |
| scripts/paper_trade_logger.py | create_paper_proposal_from_scan | manual scan-based | wired |
| scripts/paper_trade_logger.py | create_paper_proposal_from_signal | manual signal-based | wired |