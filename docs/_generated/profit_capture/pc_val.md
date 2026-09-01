# Profit-Capture Rule Quality Validation

Status:      ACTIVE
as_of:       2026-06-14T03:30:37-04:00
Measured at: efcc51365 / not measured

**Verdict: PASS** (14/14)

| check | pass | detail |
|-------|------|--------|
| hardened schema fields exist | ✅ | missing=[] |
| quality-gated run present | ✅ | run_id=ppbt_auto_20260614, rows=12 |
| raw n AND reliable n reported | ✅ | 12 rows |
| confidence keyed to reliable n | ✅ | low-reliable rows are 'insufficient' |
| premature cost path-measured where path exists | ✅ | 10 path_measured rule rows; all known=true=True |
| estimate quality honestly labelled | ✅ |  |
| intrabar paths ingested | ✅ | 9546 bars / 31 trades |
| rule graft verdicts blocked | ✅ | max_reliable_n=10 (floor 20) |
| shadow recommendations blocked | ✅ | ['DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE', 'DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE', 'DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE', 'DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE', 'DO_NOT_GRAFT_INSUFFICIENT_EVIDENCE'] |
| endpoint strict JSON | ✅ | 278197 bytes |
| no NaN/Inf in payload | ✅ | clean |
| endpoint exposes reliable n / estimate / graft | ✅ |  |
| UI panel surfaces reliable n + graft | ✅ | tsx references present |
| no broker/order/GO-WAIT/strategy mutation | ✅ | [] |
