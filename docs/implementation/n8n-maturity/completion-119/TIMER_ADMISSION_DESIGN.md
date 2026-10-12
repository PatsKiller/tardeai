# Timer-native admission proposal for the 119-lane train

Status: DRAFT / DESIGN_ONLY_UNRATIFIED. Evidence: SOURCE_ONLY. Installed units, enabled instances, drop-ins, locks, NEXT_DUE and runtime proof are NOT_MEASURED. This document changes no gate, scheduler, reviewer, unit or authority. The 119-row packet includes 36 systemd identities; its companion JSON records only committed fragment metadata.

The operator chose to design n8n admission for timer lanes. Current R1 admission remains cron-only. A future amendment must explicitly admit eligible timer-backed ingest, governed-model and learning processes, preserve their declared timer identity and prohibit fabricated cron rows. Broker/order/stop/secret/sender/daemon and independent watchdog/recovery exclusions remain intact. Agent-instance, policy-ratification and financial-owner rows still require their existing owner decisions.

## Admission shape and ownership

A future candidate retains `scheduler.kind: systemd`, the exact timer and service identifiers, an explicit scheduler-owner state, and SOURCE_ONLY fragment provenance. A separate dispatch intent can request a named CURRENT host process through the existing relay/gateway/executor with dry-run arguments and `live_arg: null`. n8n receives no systemctl, SSH, shell, DB, model/provider choice, secret or notification capability. Health contracts require the usual operator review; this proposal cannot ratify itself.

Shadow retains the native scheduler. A future canary must retain the legacy scheduler, reuse its proven lock and compare host receipts and outputs. A cutover packet must name the single new scheduler owner and exactly which legacy trigger will be disabled. Never enable two authorities and count lock contention as successful work. Native safety and recovery keep independent ownership.

Calendar timers may be candidates for a later n8n schedule only after exact semantic comparison. Activation-relative timers stay native-owned until a design proves equivalent activation, boot, restart and catch-up semantics. n8n may coordinate a process without owning its trigger. That exception must be declared, rather than translated to an approximate minute offset.

## Required semantic proof

| Property | Required evidence and failure behavior |
|---|---|
| OnCalendar | Preserve every expression, explicit or inherited timezone, weekday/weekend rule and overnight business date. Compare expected fires around both DST transitions; unresolved timezone is not UTC by assumption. |
| Monotonic timing | Preserve OnBootSec, OnUnitActiveSec and completion/activation anchors separately. CIO's boot2min/activation2min and GIR's boot10min/activation1h are not wall-clock cron. |
| Persistence | Prove missed-fire catch-up, restart behavior and duplicate prevention. An omitted Persistent setting is unresolved, not a fabricated false value. |
| Jitter and accuracy | Preserve RandomizedDelaySec and AccuracySec as separate properties; omission is unresolved. Agent templates use15min calendar,120s jitter,30s accuracy and Persistent=false. |
| Instance identity | Resolve the instance, template, all drop-ins and ConditionPathExists. Default-disabled prepare-only agent templates grant no instance enablement or agent backend authority. |
| Execution | Trace service to controller to every child, interpreter and cwd. CURRENT at one level does not prove the child root. Keep each existing timeout, market gate, cost cap and independent failure boundary. |
| Lock and idempotency | Show the exact original lock, same lock under candidate execution, durable lock-skip state and unique scheduled-event/run identifiers. Missing lock proof prevents canary. |
| Dependencies | Use same-business-day host receipts and output freshness. Missing, failed, skipped-lock or stale predecessor holds the stage. `After=` and offset timing alone are insufficient. |
| Health | Executor receipt and business output remain authoritative. Offline preview produces no fake output; NO_SIGNAL and NOT_MEASURED remain visible. |
| Env/model closure | Recursively prove explicit environment names and existing governed process routing. n8n has only its scoped relay bearer; no provider keys or new model choices. |

## Current source gaps

Nine exact source fragment pairs are missing or incomplete: aegis-surveillance, db-retention-timer, tradeai-maturity-feeds, hermes-update-check, portfolio-price-cache, slo-burn-rate, hermes-shadow-scorer, hermes-backlog-health-check and hermes-librarian-backlog-loop. Their installed fragments cannot be inferred from registry text. Seven agent-runtime identities use the committed `config/systemd/agent_runtime/tradeai-agent-runtime@.{timer,service}` template where present; instance overrides remain unmeasured. Some other fragments still name a development checkout interpreter or WorkingDirectory, so they remain explicit path-review items.

The CIO reactive cron and timer rows name one entrypoint. Both now have truthful source receipts, but that is not proof of one scheduler owner. Their ownership/duplicate decision must precede admission. A native fragment that already uses CURRENT also needs recursive child proof.

## Exact future operator packet

1. Name the reviewed policy amendment and eligible lane IDs; keep all never-admission exclusions unchanged.
2. Attach installed timer/service/drop-in metadata, exact CURRENT identity and read-only scheduler census. Re-measure rather than reuse this source packet.
3. Attach exact calendar/monotonic, DST/overnight, catch-up, duplicate, same-lock, failure and predecessor test results; include observed runtime distributions and queue load.
4. Provide DRAFT contracts and candidate registry/allowlist diffs with owner review. No reviewer field is filled by this train.
5. Name the exact source SHA/PR, release grant and host-scheduler grant separately. State the natural-shadow and canary gates, windows and abort conditions.
6. Archive the original units/scheduler entries before changes. Rollback disables the candidate owner and restores the exact original trigger/config from the archived packet; source rollback is a reviewed revert of train commits. No runtime rollback is needed for this source-only train.

The companion `TIMER_SOURCE_METADATA.json` and per-lane candidate packets are review inputs, not a release or cutover instruction.
