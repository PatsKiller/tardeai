# Inspector Integration Points

Every lifecycle row across all panels should have "View Lifecycle" → opens inspector.

| Panel | Row Key | Inspector Query |
|-------|---------|----------------|
| ATM Control Room positions | paper_trade_id | ?paper_trade_id=N |
| Proposal Hygiene | proposal_id + symbol | ?proposal_id=N |
| Lifecycle Trace | trace_id | ?trace_id=X |
| StopTrailingControl | paper_trade_id | ?paper_trade_id=N |
| StopChangeAudit | paper_trade_id | ?paper_trade_id=N |
| JournalLearningWorkspace | symbol | ?symbol=X |
| Trade Journal | paper_trade_id | ?paper_trade_id=N |
| Prospects / Trade AI | symbol | ?symbol=X |
