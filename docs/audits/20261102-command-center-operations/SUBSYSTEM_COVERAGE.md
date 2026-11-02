# Monitoring coverage by subsystem

Exhaustive lane membership is in inventory/inventory.json. Partial monitoring is not a health claim.

| Subsystem | Coverage | Evidence / gap and action |
|---|---|---|
| n8n/workflows/dispatch/webhooks |Partial |Ledger/output contracts exist; native stage omissions, receipt identity/count/rule and stderr gaps. #2444, CC-FAIL-JOB. |
| Host cron |Partial |358entries reconciled; many mtime/incomplete wrapper signals, no established cron orphan. CC-OBS-MTIME-NOT-SUCCESS. |
| systemd timers/services |Partial |103ACTIVE unknown in reader; clocks not output;8declaration contradictions,5unregistered timers. #2444, OI-148, systemd/service tickets. |
| Missed-run watchdog |Detecting, delivery incomplete |Fresh CRIT; HELD/prior actual delivery distinct; editor repeat conflict. CC-ALERT-REPEAT. |
| Failure pager |Event-driven, not qualified end-to-end |Invoked handler, latest event ROUTED not delivered. CC-ALERT-CHANNELS. |
| Merge digest/reconcile |Monitored, failed |Enabled timers, failedservices18:58Z, registry drift. #2487. |
| Agent routing/runtime/queues |Partial |Claims/receipts exist; draft Releases trust/join defects; executor-loss output unknown. CC-UX-STATE, CC-DIAG-FAILURE. |
| CIO lifecycle/research/memory |Partial |Some measured completions; lifecycle missing traceback/researchreceipt gaps. CC-DIAG-FAILURE, CC-OBS-RECEIPT. |
| Prospect/intelligence |Partial |Mutable marker does not prove immutable executor success; receipt repair in review. CC-OBS-RECEIPT. |
| Conflict |Partial; collector authority unresolved |Pure comparison receipt repaired; OI-135 remainsOPEN. |
| Broker/stop/execution |Not adjudicated beyond metadata |64protectedlanes; no protected subsystem/log/endpoint/credential investigation. CC-GOV-PROTECTED-INSTRUMENTATION. |
| Independent alert host/alternate channels |Not independently qualified |OI-149/OI-150; no host or routes provisioned. CC-ALERT-CHANNELS. |
| Self-heal code repair |Not operational |Code present, paused/uninstalled/disarmed; no qualified attempt. CC-SELFHEAL-READY. |
| Main-red CI rerun |Code present, runtime absent |Timer/service absent, no receipt. CC-SELFHEAL-READY. |
| Dashboard clocks |Partial |Separate P&L/positions/quotes clocks, missing as_of cannot become capture time. CC-DASH-FRESHNESS. |

Every critical service needs explicit owner, threshold, diagnostic receipt, alert route and recovery
proof. Generic process liveness never substitutes for useful output.
