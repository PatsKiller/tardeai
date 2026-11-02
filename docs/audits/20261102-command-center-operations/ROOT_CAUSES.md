# Root causes and remediation checkpoint

IN PROGRESS. Source tests do not establish production recovery.

| Symptom and impact | Cause / evidence | Fix and validation | Ticket |
|---|---|---|---|
| Inflated unknown jobs and hidden service coverage | [CODE] NEVER_SCHEDULED falls through; systemd recurrence/census absent; mtime and incomplete wrappers are not completion. | b48296dad explicit populations; reuse #2444 census/writer/path fixes. Independent watcher/model review MERGE. Not deployed. | CC-OBS-NEVER-SCHEDULED-COUNT; CC-OBS-SYSTEMD-SCHEDULE |
| Three output_unverifiable labels hide different causes | [CODE] disposition drops output_verdict.why. | b6b6bd396/88a5fa664 exposes counts_inconsistent, attempt_receipt_missing, rule_missing; pure diagnostic envelope; independent MERGE. | CC-DIAG-FAILURE |
| Macro output exists but contract fails | [CODE] produced event dates compared to attempted release-series units. |42294e8a1 same-unit date counters;55author tests including real verifier/mutation; independent MERGE. | CC-FAIL-JOB |
| Prospect lacks immutable attempt | [CODE] mutable last receipt bypasses shared attempt writer. |07376f655 integrates writer, but independent review BLOCK: count validation after overwrite and writer refusal can still return success. Author repair required. | CC-OBS-RECEIPT |
| Conflict report has no output rule | [CODE] enforcement on, matching report contract absent. |bed851780 pure runner report contract and identity guard; guarded tests and independent MERGE. OI-135 collector authority remains OPEN. | CC-FAIL-JOB |
| Timeout discards available diagnostics | [CODE] kill/drain and TimeoutExpired capture dropped output. Executor_lost is a separate unknown outcome. |9b646338c redacted bounded capture;8new+60regressions reported; independent retention probes. | CC-DIAG-FAILURE |
| Native workflows active but no admitted receipts | [CODE] four declarations lack scheduler.stage. |Reuse #2444 rather than duplicate; review/activation/new natural receipt still needed. | CC-FAIL-MISSED |
| CRIT looks unimportant or never repeats | [CODE] incident versus current-send/prior-delivery conflated; editor20h dedupe conflicts with reminder cadence. |b482view; e6ad137a1 scoped identity/family cooldown, two independent MERGE reviews; no live send. | CC-ALERT-REPEAT |
| Pager unregistered / notifier not installed | [CODE] pager is event-driven; digest/reconcile replaced retired per-PR timer. [VERIFIED] actual services failed18:58Z. |b482correct identity; #2487bounded query repair; registration/runtime acceptance open. | CC-UX-STATE |
| Self-heal disarmed | [VERIFIED] code exists,5requests/0attempts, no active fixer cron. [CODE] lane grant and stale prose gate refuse arming. |Qualified worker/real authority/install required, not a renamed heading. | CC-SELFHEAL-READY |
| Health missing becomes green0; high health red | [CODE] missing coercion and risk-direction gauge used for health. |1529cd017gauge repair; independent BLOCK found large hero still green for unhealthy/invalid score, author repairing. | CC-UX-STATE |
| Incidents claim P1 sent without proof | [CODE] escalation-array presence substituted for delivery. |1529strict deliveredtrue, partial warning, severity/owner/blocker; independent incident checks pass; whole patch held for hero. | CC-UX-STATE |
| Releases lacks coordinator facts | [CODE] GitHub merge status lacks normalized tasks/reviews/CI/next. |Draft#2494/#2495; exact9a0independent BLOCK for fallback working/future heartbeat/blankhead and same-session claim join; repair requested. | CC-UX-STATE |
| Header blanks / TODAY stale | [CODE] failed/empty/loading precedence incomplete; P&L/positions/quotes have distinct clocks. |#2484local repair and separate producer-clock trace underway. TODAY root cause unconfirmed; fresh positions do not prove fresh P&L. | CC-DASH-FRESHNESS |
| YELLOW persists, Acknowledge absent | [CODE] QQQ provenance can appear newer than source session;878b4cb55fix reviewed. Acknowledge belongs to open ORANGE/RED episodes; YELLOWsummary has no episode. |Root28backend tests, model checks,10real-component mocked browser cases; no live acknowledgement or threshold change. | CC-DASH-FRESHNESS |
| Standing uploads still grant dependent | [VERIFIED] #2459reviewed/CIgreen, ratification pending; GitHub Issues disabled410 blocks tracking-Issue mechanism. #2493blocked, #2492actual auto-review upload denial remains stopped. |Real policy/approval-source/guard adoption and denied-action resolution required; no alternate route or forged operator comment. | CC-PUSH-ADOPTION |

Lifecycle, disk hygiene and old fan-in retained exit1 but no stderr/traceback; their underlying exceptions
remain unknown. Lost-executor metadata cannot prove why a child vanished or whether it produced effects.
Historical diagnostics cannot be invented. See the full failure report and receipt addendum.
