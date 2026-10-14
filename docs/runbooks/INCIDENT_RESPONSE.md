# Incident response runbook — Trade AI on ms01

```
Status:      ACTIVE (procedure; the incident store and CC incident view it would write to are PLANNED)
as_of:       2026-10-14T18:45:00-04:00
Measured at: served 3e9dc5e14 / origin/main a1b1c5c93; host ms01-openclaw
Owner:       operator (incident commander); agents assist read-only
Policy:      AGENTS.md 7.0.0 §0, §10 "Incident and rollback", §17, §24.10 (execution-ops grant)
```

Written after the SPCX incident of 2026-10-14, which had no incident record, owner, severity or exit criteria
(WS8-01): resting broker stops filled at 14:24–14:39 ET, 48 stop alerts were suppressed, the first page came from
the SIEM backstop at 14:45 ET, after the fills (WS3-03, WS3-09). This runbook is the procedure. There is **no
incident store and no CC incident view yet** (WS5-20, PLANNED); until there is, the record is a file (§3).

## 1. Severity — set by what is at risk, not by who reported it

| Sev | Meaning | Examples | First response |
|---|---|---|---|
| **SEV1** | money at risk now, or the operator cannot be told | unexpected fill or position change; foreign working order; stop near/triggered/unknown with holdings; broker auth or token compromise; alert plane down (notifier stale, Telegram failing) | operator now; contain first (§4) |
| **SEV2** | a trading-relevant surface is wrong or blind | broker data stale in market hours; trading lock state unexpected; Postgres down; disk/inodes > 90%; n8n or executor stalled > 15 min | operator within 30 min |
| **SEV3** | degraded, no money or notification risk | non-trading lane failing; DLQ growth; LLM provider outage; drift | next working session |

When unsure, take the higher severity.

## 2. Roles

- **Incident commander (IC): the operator.** Decides containment, every operator-only action (AGENTS.md §17) and
  closure. An agent never acts as IC.
- **Investigator (agent):** read-only evidence: receipts, ledgers, logs, SELECTs. No broker calls, no credential
  reads, no sends, no flag changes (§0 rules 1–3, §2A, §24.7).
- **Operator-of-record for a unit (agent, only with a grant):** an `execution-ops` grant (≤ 6 h, markets closed,
  names unit + actions + incident) for broker-adjacent units (§24.10); `service` / `cron` grants for others.

## 3. The incident record (until the incident store exists)

Create `~/n8n-maturity-verification/incidents/<YYYYMMDD>-<slug>/INCIDENT.md` (host, not git) with:

```
id: <YYYYMMDD>-<slug>     sev: SEV1|SEV2|SEV3     ic: operator     opened: <ET timestamp>
status: OPEN | CONTAINED | RESOLVED | CLOSED
exit criteria: <what must be true to close>
timeline: (ET, one line per event, each with its evidence path)
actions: (who, what, grant id, result)
```

Every agent action appends one timeline line with its evidence. A postmortem is written into the same folder
within 3 days of RESOLVED (§7).

## 4. Contain — by incident class

| Class | Contain (operator unless stated) | Never |
|---|---|---|
| Unexpected broker activity | check the broker app directly; deactivate the API app if needed (done 2026-10-14, `config/schwab_access_mode.yaml` `forbidden`); kill switch (CC stop routes need same-origin only, no step-up) | an agent placing, cancelling or changing an order or stop |
| Trading code misbehaving | once #1734 is served: create the PANIC file `~/.local/state/tradeai/TRADING_LOCKED` (locks every broker write; `docs/runbooks/TRADING_LOCK.md`) | writing the unlock file for anyone |
| Alert plane down | verify on the phone; read `incident_notifier_last.json`, `notification_intent_receipts.jsonl`; restart the notifier's dependency, not the notifier's rules | raising caps or muting categories to "make it quiet" |
| n8n stalled or wrong | deactivate the workflow (packet, `cron` grant); uncomment the lane's `# RETIRED … n8n-cutover` cron line (`docs/ops/ROLLBACK_COMMANDS.md`) | editing a workflow in the n8n UI |
| Bad release | `bash scripts/cio_phase2_exact_main_deploy.sh rollback` (release grant) | an agent editing files inside a release directory. A containment edit there is an operator decision under a `config-write` grant, recorded in the incident timeline and followed by a release that makes it durable (2026-10-14 18:11, grants `96a0ab8c`/`d3a80ca0`, made durable by #1737; gap assessment §6) |
| Secret exposure | rotate (`docs/runbooks/KEY_ROTATION.md`); agents never read or copy the credential (§24.7) | pasting values anywhere |
| Disk / DB | `docs/runbooks/DB_RETENTION.md`, `docs/runbooks/DB_HANG_PREVENTION.md`; ENOSPC opens ledger breakers that need release | deleting data (§0 rule 6: archive) |

## 5. Investigate — where the evidence is (read-only)

| Question | Source |
|---|---|
| What is served? | `curl -s 127.0.0.1:7777/v3/build-meta.json`; `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` |
| What alerted, and what was suppressed? | `notification_intent_receipts.jsonl`, `communication_events` / `communication_deliveries`, `alert_events`, `system_health_events` (SELECT in a read-only session), `telegram_outbox` channel `reports_archive` |
| What did n8n fire? | ledger `persistent-state/data/governance/n8n_coordination_ledger.sqlite` (`mode=ro`) `runs` by `requested_by`; relay `data/runtime/n8n_relay/relay_log.jsonl`; n8n errors (`execution_entity`, SELECT) |
| What did the health agent do? | `logs/health_agent_remediation.jsonl`, `data/runtime/health_agent_daemon_state.json` |
| Who granted what? | `bin/guard log`; `~/.cursor/approvals/grants.json` (read only) |
| Positions / fills | broker-confirmed records only via the data broker projections; while Schwab is paused, those are stale by design (WS8-03) |

## 6. Communicate

The IC is told through the ops bot (P1 intents). Agents send nothing themselves except through `send_telegram` with
an operator-action P1 intent (dedupe off) when the runbook says to ask for a decision (§9.1). Status lines in the
incident record are the source for any later summary.

## 7. Resolve, close, learn

- **RESOLVED** when the exit criteria hold with evidence (a receipt, a query result), not when the noise stops.
- **CLOSED** after the postmortem: timeline, detection time (first signal → operator told), containment time,
  root causes, what alerted and what should have, and one tracked action per cause (PR or decision).
- Feed the lesson to AGENTS.md through an amendment PR when it changes a rule (§20).

## 8. Known gaps this runbook cannot close (from the 2026-10-14 review)

No incident store or CC view (WS5-20); no off-box dead-man or second channel (WS3-18, WS3-20); broker orders the
host did not place are invisible (WS8-02); one human on call with ~44 approvals a day (WS8-12); no runbook link
on any alert (WS8-16 — the `runbook_id` check in AGENTS.md §23.24, PROPOSED). Tracking:
`docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md` §9.
